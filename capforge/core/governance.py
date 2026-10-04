"""CapForge Risk Engine & Capability Firewall.

Implements risk classification (discussion.mdx §26) and
runtime capability permission enforcement (discussion.mdx §27).
"""

from __future__ import annotations

import ast
import logging
import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from capforge.core.models import (
    Capability,
    ExecutionRequest,
    PromotionMode,
    PromotionPolicy,
    RiskLevel,
)

logger = logging.getLogger("capforge.governance")


# ---------------------------------------------------------------------------
# Human Review Ticket Model
# ---------------------------------------------------------------------------


class HumanReviewTicket(BaseModel):
    """Auditable review ticket for high-risk or escalated capabilities."""

    ticket_id: str = Field(default_factory=lambda: f"ticket_{uuid.uuid4().hex[:8]}")
    capability_id: str
    version: str
    risk_level: RiskLevel
    escalation_reason: str
    code_snippet: str | None = None
    status: str = "PENDING"  # PENDING, APPROVED, REJECTED
    reviewed_by: str | None = None
    review_notes: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None


# ---------------------------------------------------------------------------
# Risk Engine
# ---------------------------------------------------------------------------


class RiskAssessment(BaseModel):
    """Result of a risk assessment on a capability."""

    capability_id: str
    version: str
    risk_level: RiskLevel
    risk_score: float  # 0.0 - 1.0
    factors: list[str] = Field(default_factory=list)
    requires_human_approval: bool = False
    auto_promote_allowed: bool = True


class RiskEngine:
    """Classifies capabilities into LOW/MEDIUM/HIGH risk tiers based on
    permissions, data sensitivity, and external side effects.

    LOW    → Auto-promote (policy-controlled)
    MEDIUM → Extended tests required
    HIGH   → Human approval mandatory
    """

    # Weights for permission dimensions
    PERMISSION_WEIGHTS: dict[str, dict[str, float]] = {
        "filesystem": {"none": 0.0, "read": 0.1, "write": 0.4},
        "network": {"none": 0.0, "restricted": 0.15, "full": 0.35},
        "github": {"none": 0.0, "read": 0.05, "write": 0.3},
        "database": {"none": 0.0, "read": 0.1, "write": 0.5},
        "external_apis": {"none": 0.0, "restricted": 0.1, "full": 0.3},
    }

    # Thresholds
    LOW_THRESHOLD = 0.25
    HIGH_THRESHOLD = 0.55

    def __init__(self, review_tickets: list[HumanReviewTicket] | None = None):
        self.review_tickets: list[HumanReviewTicket] = review_tickets if review_tickets is not None else []

    def get_ticket(self, ticket_id: str) -> HumanReviewTicket | None:
        """Find a review ticket by ID."""
        for t in self.review_tickets:
            if t.ticket_id == ticket_id:
                return t
        return None

    def list_tickets(self, status: str | None = None) -> list[HumanReviewTicket]:
        """List review tickets with optional status filtering."""
        if status:
            return [t for t in self.review_tickets if t.status.upper() == status.upper()]
        return self.review_tickets

    def approve_ticket(
        self,
        ticket_id: str,
        reviewer: str = "security_lead",
        notes: str = "Approved by human governor",
    ) -> HumanReviewTicket:
        """Approve a flagged high-risk capability review ticket."""
        ticket = self.get_ticket(ticket_id)
        if not ticket:
            raise KeyError(f"Review ticket '{ticket_id}' not found.")
        ticket.status = "APPROVED"
        ticket.reviewed_by = reviewer
        ticket.review_notes = notes
        ticket.resolved_at = datetime.now(UTC)
        logger.info(f"Approved review ticket {ticket_id} for {ticket.capability_id} by {reviewer}")
        return ticket

    def reject_ticket(
        self,
        ticket_id: str,
        reviewer: str = "security_lead",
        notes: str = "Rejected by human governor",
    ) -> HumanReviewTicket:
        """Reject a flagged high-risk capability review ticket."""
        ticket = self.get_ticket(ticket_id)
        if not ticket:
            raise KeyError(f"Review ticket '{ticket_id}' not found.")
        ticket.status = "REJECTED"
        ticket.reviewed_by = reviewer
        ticket.review_notes = notes
        ticket.resolved_at = datetime.now(UTC)
        logger.warning(f"Rejected review ticket {ticket_id} for {ticket.capability_id} by {reviewer}")
        return ticket

    def assess(self, capability: Capability) -> RiskAssessment:
        """Perform a risk assessment on a capability."""
        score = 0.0
        factors: list[str] = []

        # 1. Permission-based risk
        perms = capability.permissions
        for dim, levels in self.PERMISSION_WEIGHTS.items():
            perm_value = getattr(perms, dim, "none")
            weight = levels.get(perm_value, 0.0)
            if weight > 0:
                score += weight
                factors.append(f"{dim}={perm_value} (+{weight:.2f})")

        # 2. External side effects (tools requiring network egress)
        for tool in capability.tools_required:
            if "network" in tool.permissions:
                score += 0.1
                factors.append(f"tool '{tool.name}' requires network")
                break

        # 3. Code complexity heuristic (lines of code)
        loc = len(capability.code_body.strip().splitlines())
        if loc > 100:
            score += 0.1
            factors.append(f"code_lines={loc} (complex)")

        # 4. Provenance trust
        if capability.provenance.trust_level < 0.5:
            score += 0.15
            factors.append(f"low_trust_provenance={capability.provenance.trust_level:.2f}")

        # 5. AST static security inspection & dynamic escalation
        ast_violation = False
        if capability.code_body and capability.code_body.strip():
            try:
                tree = ast.parse(capability.code_body)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        func_name = ""
                        if isinstance(node.func, ast.Name):
                            func_name = node.func.id
                        elif isinstance(node.func, ast.Attribute):
                            func_name = node.func.attr

                        if func_name in ("eval", "exec", "compile", "__import__"):
                            ast_violation = True
                            factors.append(f"AST anomaly: prohibited call '{func_name}()'")
                        elif func_name == "open" and perms.filesystem == "none":
                            ast_violation = True
                            factors.append("AST anomaly: filesystem open() called with filesystem='none'")

                    elif isinstance(node, (ast.Import, ast.ImportFrom)):
                        names = (
                            [alias.name for alias in node.names]
                            if isinstance(node, ast.Import)
                            else [node.module or ""]
                        )
                        for mod in names:
                            if mod in ("subprocess", "pty", "commands"):
                                ast_violation = True
                                factors.append(f"AST anomaly: prohibited system module '{mod}'")
                            elif mod in ("socket", "urllib", "requests", "httpx") and perms.network == "none":
                                ast_violation = True
                                factors.append(f"AST anomaly: unauthorized network module '{mod}' with network='none'")
                            elif mod in ("shutil",) and perms.filesystem == "none":
                                ast_violation = True
                                factors.append(
                                    f"AST anomaly: unauthorized filesystem module '{mod}' with filesystem='none'"
                                )
            except Exception as e:
                ast_violation = True
                factors.append(f"AST parse error: {e}")

        # Clamp initial score
        score = min(1.0, score)

        # Dynamic Escalation if AST violations detected
        if ast_violation:
            score = max(score, 0.85)
            level = RiskLevel.HIGH
        elif score <= self.LOW_THRESHOLD:
            level = RiskLevel.LOW
        elif score <= self.HIGH_THRESHOLD:
            level = RiskLevel.MEDIUM
        else:
            level = RiskLevel.HIGH

        # Create audit review ticket for HIGH risk
        if level == RiskLevel.HIGH:
            ticket = HumanReviewTicket(
                capability_id=capability.id,
                version=capability.version,
                risk_level=level,
                escalation_reason="; ".join(factors),
                code_snippet=capability.code_body[:200] if capability.code_body else None,
            )
            self.review_tickets.append(ticket)

        return RiskAssessment(
            capability_id=capability.id,
            version=capability.version,
            risk_level=level,
            risk_score=round(score, 3),
            factors=factors,
            requires_human_approval=(level == RiskLevel.HIGH),
            auto_promote_allowed=(level == RiskLevel.LOW),
        )

    def evaluate_promotion(
        self,
        capability: Capability,
        policy: PromotionPolicy | None = None,
    ) -> tuple[bool, RiskAssessment, HumanReviewTicket | None]:
        """Evaluate whether a capability can be promoted according to policy.

        Returns:
            (can_promote, assessment, ticket_if_created)
        """
        policy = policy or PromotionPolicy()
        assessment = self.assess(capability)

        risk_order = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}
        cap_risk = risk_order.get(assessment.risk_level, 2)
        threshold_risk = risk_order.get(policy.risk_threshold, 0)

        can_promote = False
        if policy.mode == PromotionMode.AUTO:
            can_promote = True
        elif policy.mode == PromotionMode.AUTO_LOW_RISK:
            can_promote = cap_risk <= threshold_risk
        elif policy.mode == PromotionMode.HUMAN_REVIEW:
            can_promote = False

        ticket: HumanReviewTicket | None = None
        if not can_promote:
            existing = [
                t
                for t in self.review_tickets
                if t.capability_id == capability.id and t.status == "PENDING"
            ]
            if existing:
                ticket = existing[0]
            else:
                ticket = HumanReviewTicket(
                    capability_id=capability.id,
                    version=capability.version,
                    risk_level=assessment.risk_level,
                    escalation_reason=(
                        f"Promotion policy '{policy.mode.value}' requires review "
                        f"(risk: {assessment.risk_level.value})"
                    ),
                    code_snippet=capability.code_body[:500] if capability.code_body else None,
                )
                self.review_tickets.append(ticket)

        return can_promote, assessment, ticket



# ---------------------------------------------------------------------------
# Capability Firewall
# ---------------------------------------------------------------------------


class FirewallDecision(BaseModel):
    """Result of a firewall check on a capability execution request."""

    allowed: bool
    capability_id: str
    version: str
    blocked_reason: str | None = None
    risk_level: RiskLevel = RiskLevel.LOW


class CapabilityFirewall:
    """Runtime security boundary between agents and learned capabilities.

    Verifies:
      - Who requested it (agent_id)
      - Which capability / version
      - Which permissions are required
      - What risk level
      - Whether the capability is ACTIVE (not quarantined/deprecated)
    """

    def __init__(
        self,
        risk_engine: RiskEngine | None = None,
        blocked_capabilities: set[str] | None = None,
        max_risk_level: RiskLevel = RiskLevel.HIGH,
    ) -> None:
        self.risk_engine = risk_engine or RiskEngine()
        self.blocked_capabilities: set[str] = blocked_capabilities or set()
        self.max_risk_level = max_risk_level

    def check(
        self,
        capability: Capability,
        request: ExecutionRequest,
    ) -> FirewallDecision:
        """Evaluate whether a capability execution should be allowed."""

        # 1. Explicit block list
        if capability.id in self.blocked_capabilities:
            return FirewallDecision(
                allowed=False,
                capability_id=capability.id,
                version=capability.version,
                blocked_reason=f"Capability '{capability.id}' is on the block list.",
                risk_level=capability.risk_level,
            )

        # 2. Status check — only ACTIVE or EXPERIMENTAL allowed
        from capforge.core.models import CapabilityStatus

        if capability.status in (CapabilityStatus.QUARANTINED, CapabilityStatus.DEPRECATED):
            return FirewallDecision(
                allowed=False,
                capability_id=capability.id,
                version=capability.version,
                blocked_reason=f"Capability status is {capability.status.value}. Execution denied.",
                risk_level=capability.risk_level,
            )

        # 3. Risk level gate
        risk = self.risk_engine.assess(capability)
        risk_order = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}
        if risk_order.get(risk.risk_level, 0) > risk_order.get(self.max_risk_level, 2):
            return FirewallDecision(
                allowed=False,
                capability_id=capability.id,
                version=capability.version,
                blocked_reason=f"Risk level {risk.risk_level.value} exceeds maximum allowed {self.max_risk_level.value}.",
                risk_level=risk.risk_level,
            )

        # 4. Zero-tolerance AST containment check
        if any("prohibited call" in f or "prohibited system module" in f for f in risk.factors):
            return FirewallDecision(
                allowed=False,
                capability_id=capability.id,
                version=capability.version,
                blocked_reason="Firewall rejected capability due to prohibited dynamic code execution or uncontained system call in AST.",
                risk_level=risk.risk_level,
            )

        # 5. Multi-tenant namespace boundary check
        if request.allowed_namespaces is not None:
            if capability.namespace not in request.allowed_namespaces:
                return FirewallDecision(
                    allowed=False,
                    capability_id=capability.id,
                    version=capability.version,
                    blocked_reason=f"Capability namespace '{capability.namespace}' is not permitted for agent. Allowed: {request.allowed_namespaces}",
                    risk_level=risk.risk_level,
                )

        logger.info(
            "firewall_allowed",
            extra={
                "capability_id": capability.id,
                "version": capability.version,
                "agent_id": request.agent_id,
                "risk_level": risk.risk_level.value,
            },
        )

        return FirewallDecision(
            allowed=True,
            capability_id=capability.id,
            version=capability.version,
            risk_level=risk.risk_level,
        )

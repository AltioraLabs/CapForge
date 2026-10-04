"""Tests for CapForge Promotion Policy & Governance Gates (Priority 2)."""

import pytest

from capforge import CapForgeClient
from capforge.core.governance import HumanReviewTicket, RiskEngine
from capforge.core.models import (
    Capability,
    CapabilityStatus,
    PromotionMode,
    PromotionPolicy,
    RiskLevel,
    ToolPermissions,
)
from capforge.runtime.agent_adapter import CapForgeAgent


def _make_capability(cap_id: str, perms: ToolPermissions | None = None) -> Capability:
    return Capability(
        id=cap_id,
        name=cap_id.replace("_", " ").title(),
        description="Test capability",
        code_body="def run(x=1):\n    return {'result': x}\n",
        permissions=perms or ToolPermissions(),
        status=CapabilityStatus.CANDIDATE,
    )


def test_promotion_policy_auto():
    """Verify AUTO mode approves and promotes regardless of risk."""
    engine = RiskEngine()
    cap = _make_capability("auto_tool")
    policy = PromotionPolicy(mode=PromotionMode.AUTO)

    can_promote, assessment, ticket = engine.evaluate_promotion(cap, policy)
    assert can_promote is True
    assert ticket is None


def test_promotion_policy_auto_low_risk_pass():
    """Verify AUTO_LOW_RISK mode allows LOW risk capabilities to auto-promote."""
    engine = RiskEngine()
    cap = _make_capability("low_risk_tool")  # perms none -> LOW risk
    policy = PromotionPolicy(mode=PromotionMode.AUTO_LOW_RISK, risk_threshold=RiskLevel.LOW)

    can_promote, assessment, ticket = engine.evaluate_promotion(cap, policy)
    assert assessment.risk_level == RiskLevel.LOW
    assert can_promote is True
    assert ticket is None


def test_promotion_policy_auto_low_risk_escalate_high_risk():
    """Verify AUTO_LOW_RISK escalates HIGH risk to PENDING_REVIEW and creates a review ticket."""
    engine = RiskEngine()
    # High risk permissions (write filesystem + write database)
    perms = ToolPermissions(filesystem="write", database="write")
    cap = _make_capability("high_risk_tool", perms=perms)
    policy = PromotionPolicy(mode=PromotionMode.AUTO_LOW_RISK, risk_threshold=RiskLevel.LOW)

    can_promote, assessment, ticket = engine.evaluate_promotion(cap, policy)
    assert assessment.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH)
    assert can_promote is False
    assert ticket is not None
    assert ticket.capability_id == "high_risk_tool"
    assert ticket.status == "PENDING"
    assert len(engine.list_tickets(status="PENDING")) >= 1


def test_promotion_policy_human_review_mode():
    """Verify HUMAN_REVIEW mode always halts auto-promotion."""
    engine = RiskEngine()
    cap = _make_capability("regulated_finance_tool")
    policy = PromotionPolicy(mode=PromotionMode.HUMAN_REVIEW)

    can_promote, assessment, ticket = engine.evaluate_promotion(cap, policy)
    assert can_promote is False
    assert ticket is not None
    assert ticket.capability_id == "regulated_finance_tool"


def test_sdk_review_approval_and_rejection():
    """Verify SDK methods approve_capability and reject_capability work end-to-end."""
    with CapForgeClient() as client:
        # Create a capability and register as PENDING_REVIEW
        cap = _make_capability("client_review_tool")
        cap.status = CapabilityStatus.PENDING_REVIEW
        client.registry.register(cap)

        # Manually create a ticket
        ticket = HumanReviewTicket(
            capability_id="client_review_tool",
            version="1.0.0",
            risk_level=RiskLevel.HIGH,
            escalation_reason="Human review required by policy",
        )
        client.agent.risk_engine.review_tickets.append(ticket)

        pending = client.list_pending_reviews(status="PENDING")
        assert any(t.ticket_id == ticket.ticket_id for t in pending)

        # Approve
        approved = client.approve_capability(
            ticket.ticket_id,
            reviewer="compliance_officer",
            notes="Audit verified safe",
        )
        assert approved.status == "APPROVED"
        assert approved.reviewed_by == "compliance_officer"

        # Check capability is now ACTIVE
        updated_cap = client.get("client_review_tool")
        assert updated_cap.status == CapabilityStatus.ACTIVE

        # Test Rejection on another tool
        cap2 = _make_capability("client_reject_tool")
        cap2.status = CapabilityStatus.PENDING_REVIEW
        client.registry.register(cap2)

        ticket2 = HumanReviewTicket(
            capability_id="client_reject_tool",
            version="1.0.0",
            risk_level=RiskLevel.HIGH,
            escalation_reason="Policy rejected",
        )
        client.agent.risk_engine.review_tickets.append(ticket2)

        rejected = client.reject_capability(
            ticket2.ticket_id,
            reviewer="ciso",
            notes="Unsanitized network access",
        )
        assert rejected.status == "REJECTED"

        updated_cap2 = client.get("client_reject_tool")
        assert updated_cap2.status == CapabilityStatus.QUARANTINED


def test_agent_handle_task_with_human_review_policy():
    """Verify CapForgeAgent.handle_task respects HUMAN_REVIEW policy and enters PENDING_REVIEW."""
    agent = CapForgeAgent()
    spec = {
        "id": "vault_signer",
        "name": "Vault Signer",
        "description": "Sign cryptographic payloads",
        "code_body": "def run(msg='test'):\n    return {'signature': 'sig_' + str(msg)}\n",
    }

    trace = agent.handle_task(
        task_intent="sign secure vault payloads",
        task_inputs={"msg": "hello"},
        knowledge_spec=spec,
        promotion_policy=PromotionPolicy(mode=PromotionMode.HUMAN_REVIEW),
    )

    assert trace.pending_review is True
    assert trace.review_ticket_id is not None

    # Capability should be in registry as PENDING_REVIEW, not ACTIVE
    cap = agent.registry.get("vault_signer")
    assert cap is not None
    assert cap.status == CapabilityStatus.PENDING_REVIEW

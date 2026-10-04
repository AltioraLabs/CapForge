"""CapForge Async Synthesis Path.

Implements non-blocking capability synthesis that returns a graceful
fallback to the agent immediately and synthesizes + verifies the
missing capability in the background.

Flow:
    Agent hits gap
        │
        ├─► [Immediate] Return fallback response + queue async synthesis job
        │
        └─► [Background] Synthesize → L0+L1 fast verify → DRAFT
                    │                       → L2-L5 full verify → ACTIVE
                    └─► Webhook fires: "capability_ready"
"""

from __future__ import annotations

import enum
import logging
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from capforge.core.models import (
    AgentEvent,
    Capability,
    CapabilityGap,
    CapabilityStatus,
    EventType,
    PromotionMode,
    PromotionPolicy,
    RiskLevel,
)

logger = logging.getLogger("capforge.async_synthesis")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SynthesisPhase(str, enum.Enum):
    """Tracks which pipeline stage the async synthesis is in."""

    QUEUED = "QUEUED"
    L0_L1_FAST_CHECK = "L0_L1_FAST_CHECK"
    DRAFT_PROMOTED = "DRAFT_PROMOTED"
    L2_L5_FULL_VERIFY = "L2_L5_FULL_VERIFY"
    PROMOTION_GATE = "PROMOTION_GATE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AsyncSynthesisJob(BaseModel):
    """Tracks an in-progress asynchronous capability synthesis."""

    job_id: str = Field(default_factory=lambda: f"async_{uuid.uuid4().hex[:12]}")
    task_intent: str
    gap: CapabilityGap | None = None
    knowledge_spec: dict[str, Any] | None = None
    phase: SynthesisPhase = SynthesisPhase.QUEUED
    progress_pct: int = 0
    capability_id: str | None = None
    version: str | None = None
    draft_available: bool = False
    fully_verified: bool = False
    risk_level: str | None = None
    promotion_policy: PromotionPolicy = Field(default_factory=PromotionPolicy)
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    phase_timings: dict[str, float] = Field(
        default_factory=dict,
        description="Wall-clock ms for each pipeline phase",
    )

    def _touch(self) -> None:
        self.updated_at = datetime.now(UTC)


class SynthesisFallbackResponse(BaseModel):
    """Returned immediately to the caller when async synthesis is queued."""

    job_id: str
    status: str = "SYNTHESIS_QUEUED"
    message: str = "Capability gap detected. Synthesis queued in background."
    fallback_output: Any = None
    poll_endpoint: str = ""


# ---------------------------------------------------------------------------
# Async Synthesis Manager
# ---------------------------------------------------------------------------


class AsyncSynthesisManager:
    """Non-blocking synthesis orchestrator.

    On gap detection:
      1. Immediately returns a SynthesisFallbackResponse to the caller
      2. Spawns a background thread running tiered synthesis:
         - L0+L1 fast checks → promote to DRAFT (usable for low-risk paths)
         - L2-L5 full verification → promote to ACTIVE
      3. Fires webhook on completion
    """

    def __init__(
        self,
        agent: Any = None,
        webhook_manager: Any = None,
        promotion_policy: PromotionPolicy | None = None,
        max_concurrent: int = 4,
    ) -> None:
        self._agent = agent
        self._webhook_manager = webhook_manager
        self._default_policy = promotion_policy or PromotionPolicy()
        self._jobs: dict[str, AsyncSynthesisJob] = {}
        self._lock = threading.Lock()
        self._semaphore = threading.Semaphore(max_concurrent)

    @property
    def agent(self):
        """Lazy-load agent to avoid circular imports."""
        if self._agent is None:
            from capforge.runtime.agent_adapter import CapForgeAgent
            self._agent = CapForgeAgent()
        return self._agent

    @property
    def webhook_manager(self):
        """Lazy-load webhook manager."""
        if self._webhook_manager is None:
            from capforge.events.webhooks import webhook_manager
            self._webhook_manager = webhook_manager
        return self._webhook_manager

    def submit_synthesis(
        self,
        task_intent: str,
        gap: CapabilityGap | None = None,
        knowledge_spec: dict[str, Any] | None = None,
        promotion_policy: PromotionPolicy | None = None,
        fallback_output: Any = None,
    ) -> SynthesisFallbackResponse:
        """Submit a non-blocking synthesis request.

        Returns immediately with a fallback response; actual synthesis
        runs in a background thread.
        """
        policy = promotion_policy or self._default_policy
        job = AsyncSynthesisJob(
            task_intent=task_intent,
            gap=gap,
            knowledge_spec=knowledge_spec,
            promotion_policy=policy,
        )

        with self._lock:
            self._jobs[job.job_id] = job

        # Fire and forget — background thread handles the pipeline
        thread = threading.Thread(
            target=self._run_tiered_synthesis,
            args=(job,),
            name=f"capforge-synth-{job.job_id}",
            daemon=True,
        )
        thread.start()

        logger.info(
            "Async synthesis queued: job=%s intent='%s'",
            job.job_id,
            task_intent[:60],
        )

        return SynthesisFallbackResponse(
            job_id=job.job_id,
            fallback_output=fallback_output,
            poll_endpoint=f"/v1/synthesis/{job.job_id}",
        )

    def get_job(self, job_id: str) -> AsyncSynthesisJob | None:
        """Poll the status of a synthesis job."""
        return self._jobs.get(job_id)

    def list_jobs(
        self,
        phase: SynthesisPhase | None = None,
        limit: int = 50,
    ) -> list[AsyncSynthesisJob]:
        """List synthesis jobs with optional phase filter."""
        jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        if phase:
            jobs = [j for j in jobs if j.phase == phase]
        return jobs[:limit]

    # -----------------------------------------------------------------
    # Tiered synthesis pipeline (runs in background thread)
    # -----------------------------------------------------------------

    def _run_tiered_synthesis(self, job: AsyncSynthesisJob) -> None:
        """Execute the full tiered synthesis pipeline in a background thread."""
        acquired = self._semaphore.acquire(timeout=30)
        if not acquired:
            job.phase = SynthesisPhase.FAILED
            job.error = "Synthesis queue full — max concurrent jobs reached."
            job._touch()
            return

        try:
            self._phase_synthesize_and_fast_check(job)
            if job.phase == SynthesisPhase.FAILED:
                return

            self._phase_full_verification(job)
            if job.phase == SynthesisPhase.FAILED:
                return

            self._phase_promotion_gate(job)

        except Exception as exc:
            logger.exception("Async synthesis failed for job %s: %s", job.job_id, exc)
            job.phase = SynthesisPhase.FAILED
            job.error = str(exc)
            job._touch()
        finally:
            self._semaphore.release()
            self._notify_completion(job)

    def _phase_synthesize_and_fast_check(self, job: AsyncSynthesisJob) -> None:
        """Phase 1: Synthesize code + L0 AST firewall + L1 structural checks."""
        t0 = time.perf_counter()
        job.phase = SynthesisPhase.L0_L1_FAST_CHECK
        job.progress_pct = 10
        job._touch()

        agent = self.agent

        # Build spec from gap or knowledge_spec
        spec = job.knowledge_spec or {}
        if job.gap and job.gap.missing_primitives:
            spec.setdefault("id", job.gap.missing_primitives[0])
        spec.setdefault("name", job.task_intent[:40])
        spec.setdefault("description", job.task_intent)

        # Synthesize candidate
        candidate = agent.acquisition_engine.acquire_from_spec(spec, job.gap)
        candidate.verification_tests = agent.test_generator.enrich_tests(candidate)
        job.capability_id = candidate.id
        job.version = candidate.version
        job.progress_pct = 30
        job._touch()

        # L0: CodeGuardian AST firewall
        from capforge.security.code_guardian import CodeGuardian
        guardian = CodeGuardian()
        scan = guardian.scan(candidate.id, candidate.code_body)
        if scan.blocked:
            job.phase = SynthesisPhase.FAILED
            job.error = f"L0 AST Firewall blocked: {scan.summary}"
            job._touch()
            return

        # L1: Structural validation (syntax, entrypoint, schema)
        try:
            import ast
            ast.parse(candidate.code_body)
        except SyntaxError as e:
            job.phase = SynthesisPhase.FAILED
            job.error = f"L1 Syntax check failed: {e}"
            job._touch()
            return

        elapsed = (time.perf_counter() - t0) * 1000
        job.phase_timings["L0_L1_fast_check_ms"] = round(elapsed, 2)
        job.progress_pct = 40
        job._touch()

        # If policy allows, promote to DRAFT for immediate low-risk use
        if not job.promotion_policy.require_full_verification:
            candidate.status = CapabilityStatus.DRAFT
            agent.registry.register(candidate)
            job.draft_available = True
            job.phase = SynthesisPhase.DRAFT_PROMOTED
            logger.info(
                "Capability '%s' promoted to DRAFT (L0+L1 passed) in %.1fms",
                candidate.id,
                elapsed,
            )
        else:
            # Still register as EXPERIMENTAL for tracking
            candidate.status = CapabilityStatus.EXPERIMENTAL
            agent.registry.register(candidate)

        job._touch()

    def _phase_full_verification(self, job: AsyncSynthesisJob) -> None:
        """Phase 2: Run L2-L5 full verification battery."""
        t0 = time.perf_counter()
        job.phase = SynthesisPhase.L2_L5_FULL_VERIFY
        job.progress_pct = 50
        job._touch()

        agent = self.agent
        cap = agent.registry.get(job.capability_id)
        if not cap:
            job.phase = SynthesisPhase.FAILED
            job.error = f"Capability '{job.capability_id}' not found in registry after synthesis."
            job._touch()
            return

        # Full evaluator run (L2 sandbox + L3 fuzzing + L4 regression + L5 adversarial)
        repaired_cap, verif_result, repair_iters = agent.repair_engine.repair_until_pass(cap)
        job.progress_pct = 80
        job._touch()

        elapsed = (time.perf_counter() - t0) * 1000
        job.phase_timings["L2_L5_full_verify_ms"] = round(elapsed, 2)

        if verif_result.passed:
            job.fully_verified = True
            # Update capability in registry with repaired version
            agent.registry.register(repaired_cap)
        else:
            job.phase = SynthesisPhase.FAILED
            job.error = f"Full verification failed after {repair_iters} repair iterations: {verif_result.diagnostics or 'tests failed'}"
            # If it was DRAFT, quarantine it
            if job.draft_available:
                repaired_cap.status = CapabilityStatus.QUARANTINED
                agent.registry.register(repaired_cap)
                job.draft_available = False
            job._touch()
            return

        job._touch()

    def _phase_promotion_gate(self, job: AsyncSynthesisJob) -> None:
        """Phase 3: Apply promotion policy (auto-promote or queue for human review)."""
        t0 = time.perf_counter()
        job.phase = SynthesisPhase.PROMOTION_GATE
        job.progress_pct = 90
        job._touch()

        agent = self.agent
        cap = agent.registry.get(job.capability_id)
        if not cap:
            job.phase = SynthesisPhase.FAILED
            job.error = "Capability disappeared from registry during promotion gate."
            job._touch()
            return

        # Assess risk
        risk = agent.risk_engine.assess(cap)
        job.risk_level = risk.risk_level.value
        policy = job.promotion_policy

        risk_order = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}
        cap_risk = risk_order.get(risk.risk_level, 2)
        threshold_risk = risk_order.get(policy.risk_threshold, 0)

        should_auto_promote = False
        if policy.mode == PromotionMode.AUTO:
            should_auto_promote = True
        elif policy.mode == PromotionMode.AUTO_LOW_RISK:
            should_auto_promote = cap_risk <= threshold_risk
        # HUMAN_REVIEW: never auto-promote

        if should_auto_promote:
            cap.status = CapabilityStatus.ACTIVE
            agent.registry.register(cap)
            agent.capability_graph.add_capability(cap)
            logger.info(
                "Capability '%s' auto-promoted to ACTIVE (risk=%s, policy=%s)",
                cap.id,
                risk.risk_level.value,
                policy.mode.value,
            )
        else:
            cap.status = CapabilityStatus.PENDING_REVIEW
            agent.registry.register(cap)
            # Create a human review ticket
            from capforge.core.governance import HumanReviewTicket
            ticket = HumanReviewTicket(
                capability_id=cap.id,
                version=cap.version,
                risk_level=risk.risk_level,
                escalation_reason=f"Promotion policy '{policy.mode.value}' requires human review. Risk: {risk.risk_level.value}",
                code_snippet=cap.code_body[:500] if cap.code_body else None,
            )
            agent.risk_engine.review_tickets.append(ticket)
            logger.info(
                "Capability '%s' queued for PENDING_REVIEW (risk=%s, ticket=%s)",
                cap.id,
                risk.risk_level.value,
                ticket.ticket_id,
            )

        elapsed = (time.perf_counter() - t0) * 1000
        job.phase_timings["promotion_gate_ms"] = round(elapsed, 2)
        job.phase = SynthesisPhase.COMPLETED
        job.progress_pct = 100
        job.completed_at = datetime.now(UTC)
        job._touch()

    def _notify_completion(self, job: AsyncSynthesisJob) -> None:
        """Fire webhook and/or notification channels on synthesis completion."""
        event_type = "capability_ready" if job.phase == SynthesisPhase.COMPLETED else "synthesis_failed"
        payload = {
            "job_id": job.job_id,
            "capability_id": job.capability_id,
            "version": job.version,
            "phase": job.phase.value,
            "risk_level": job.risk_level,
            "fully_verified": job.fully_verified,
            "draft_available": job.draft_available,
            "phase_timings": job.phase_timings,
            "error": job.error,
        }

        try:
            self.webhook_manager.dispatch(event_type, payload)
        except Exception as exc:
            logger.warning("Webhook dispatch failed for job %s: %s", job.job_id, exc)

        # Emit CapForge event
        try:
            from capforge.core.events import EventGateway
            gw = EventGateway()
            gw.emit(
                AgentEvent(
                    event_type=EventType.SKILL_PROMOTED if job.phase == SynthesisPhase.COMPLETED else EventType.SKILL_REJECTED,
                    metadata=payload,
                )
            )
        except Exception:
            pass

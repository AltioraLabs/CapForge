"""CapForge Learning Jobs Runtime and Manager (discussion.mdx §19, §38, §46).

Manages autonomous capability acquisition workflows as trackable, inspectable,
and auditable asynchronous or background jobs.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from capforge.core.models import AgentEvent, EventType
from capforge.runtime.agent_adapter import CapForgeAgent

logger = logging.getLogger("capforge.learning_jobs")


class LearningJob(BaseModel):
    job_id: str = Field(default_factory=lambda: f"job_{uuid.uuid4().hex[:8]}")
    task_intent: str
    knowledge_spec: dict[str, Any] | None = None
    task_inputs: dict[str, Any] = Field(default_factory=dict)
    status: str = "QUEUED"  # QUEUED, RUNNING, COMPLETED, FAILED
    step: str = "initialized"  # gap_detection, synthesis, verification, risk_gate, promotion, completed
    progress_pct: int = 0
    capability_id: str | None = None
    version: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    trace: dict[str, Any] | None = None
    error: str | None = None


class LearningJobManager:
    """In-memory or persistent registry of background learning jobs."""

    def __init__(self, agent: CapForgeAgent | None = None):
        self.agent = agent or CapForgeAgent()
        self._jobs: dict[str, LearningJob] = {}

    def create_job(
        self,
        task_intent: str,
        task_inputs: dict[str, Any] | None = None,
        knowledge_spec: dict[str, Any] | None = None,
    ) -> LearningJob:
        """Create and queue a new capability learning job."""
        job = LearningJob(
            task_intent=task_intent,
            task_inputs=task_inputs or {},
            knowledge_spec=knowledge_spec,
        )
        self._jobs[job.job_id] = job
        logger.info(f"Created learning job {job.job_id} for intent '{task_intent}'")
        return job

    def execute_job_sync(self, job_id: str) -> LearningJob:
        """Execute a learning job through the full lifecycle synchronously."""
        job = self._jobs.get(job_id)
        if not job:
            raise KeyError(f"Learning job '{job_id}' not found.")

        job.status = "RUNNING"
        job.step = "gap_detection"
        job.progress_pct = 20
        job.updated_at = datetime.now(UTC)

        try:
            # Emit job start event
            self.agent.event_gateway.emit(
                AgentEvent(
                    event_type=EventType.TASK_STARTED,
                    agent_id="learning_runtime",
                    run_id=job.job_id,
                    input_data={"task_intent": job.task_intent},
                )
            )

            job.step = "synthesis_and_verification"
            job.progress_pct = 50

            # Run agent lifecycle
            trace = self.agent.handle_task(
                task_intent=job.task_intent,
                task_inputs=job.task_inputs,
                knowledge_spec=job.knowledge_spec,
                agent_id="learning_runtime",
                run_id=job.job_id,
            )

            job.step = "promotion_and_completion"
            job.progress_pct = 85

            if trace.acquired_capability:
                job.capability_id = trace.acquired_capability.id
                job.version = trace.acquired_capability.version
            elif trace.reused_primitives:
                job.capability_id = trace.reused_primitives[0]

            job.trace = trace.model_dump()

            if trace.execution_result and trace.execution_result.status == "FAILED":
                job.status = "FAILED"
                job.error = trace.execution_result.error or "Execution failed"
            elif trace.verification and not trace.verification.passed:
                job.status = "FAILED"
                job.error = "Verification failed: " + (trace.verification.diagnostics or "")
            else:
                job.status = "COMPLETED"
            job.progress_pct = 100

        except Exception as e:
            logger.exception(f"Learning job {job_id} failed: {e}")
            job.status = "FAILED"
            job.error = str(e)
            job.progress_pct = 100

        job.updated_at = datetime.now(UTC)
        return job

    def get_job(self, job_id: str) -> LearningJob | None:
        return self._jobs.get(job_id)

    def list_jobs(self, status: str | None = None) -> list[LearningJob]:
        jobs = list(self._jobs.values())
        if status:
            jobs = [j for j in jobs if j.status.upper() == status.upper()]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

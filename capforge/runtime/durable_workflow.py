"""CapForge Resilient Durable Workflow Engine (discussion.mdx §10, §35).

Provides durable, fault-tolerant workflow execution with step checkpointing,
exponential backoff retries, state persistence, and idempotent resume capabilities.
"""

from __future__ import annotations

import enum
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from capforge.core.events import EventGateway
from capforge.core.models import AgentEvent, EventType, ExecutionRequest, ExecutionResponse
from capforge.runtime.executor import CapabilityExecutor

logger = logging.getLogger("capforge.runtime.workflow")


class WorkflowStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class StepCheckpoint(BaseModel):
    """Execution checkpoint for a durable workflow step."""
    step_id: str
    status: str = "PENDING"  # PENDING, RUNNING, COMPLETED, FAILED, SKIPPED
    attempt_count: int = 0
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class WorkflowStep(BaseModel):
    """Specification of an individual step in a durable workflow."""
    step_id: str
    capability_id: str
    version: Optional[str] = None
    input_mappings: Dict[str, Any] = Field(
        default_factory=dict,
        description="Maps inputs using literal values, '$inputs.<param>', or '$steps.<step_id>.output.<field>'",
    )
    max_retries: int = 2
    retry_delay_sec: float = 0.1
    continue_on_failure: bool = False


class WorkflowDefinition(BaseModel):
    """Declarative definition of a durable multi-step workflow."""
    workflow_id: str
    name: str
    description: str = ""
    steps: List[WorkflowStep] = Field(default_factory=list)
    output_mappings: Dict[str, str] = Field(default_factory=dict)


class WorkflowExecutionState(BaseModel):
    """Durable state record of a workflow run with all checkpoints."""
    run_id: str = Field(default_factory=lambda: f"wf_run_{uuid.uuid4().hex[:10]}")
    workflow_id: str
    status: WorkflowStatus = WorkflowStatus.PENDING
    inputs: Dict[str, Any] = Field(default_factory=dict)
    checkpoints: Dict[str, StepCheckpoint] = Field(default_factory=dict)
    final_output: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DurableWorkflowEngine:
    """Orchestrates durable workflow execution with checkpointing and resume support."""

    def __init__(
        self,
        executor: CapabilityExecutor,
        event_gateway: Optional[EventGateway] = None,
    ):
        self.executor = executor
        self.event_gateway = event_gateway
        self._execution_store: Dict[str, WorkflowExecutionState] = {}
        self._workflow_definitions: Dict[str, WorkflowDefinition] = {}

    def register_workflow(self, workflow: WorkflowDefinition) -> None:
        """Register a reusable workflow definition."""
        self._workflow_definitions[workflow.workflow_id] = workflow

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        return self._workflow_definitions.get(workflow_id)

    def get_workflow_state(self, run_id: str) -> Optional[WorkflowExecutionState]:
        """Fetch current state of a workflow run."""
        return self._execution_store.get(run_id)

    def list_workflow_runs(self, limit: int = 50) -> List[WorkflowExecutionState]:
        return list(reversed(list(self._execution_store.values())))[:limit]

    def _resolve_step_inputs(
        self,
        step: WorkflowStep,
        initial_inputs: Dict[str, Any],
        checkpoints: Dict[str, StepCheckpoint],
    ) -> Dict[str, Any]:
        """Resolve dynamic input values for a step."""
        resolved: Dict[str, Any] = {}
        for param, mapping in step.input_mappings.items():
            if isinstance(mapping, str):
                if mapping.startswith("$inputs."):
                    field = mapping[len("$inputs."):]
                    resolved[param] = initial_inputs.get(field)
                elif mapping.startswith("$steps."):
                    parts = mapping.split(".")
                    # e.g., $steps.<step_id>.output.<field>
                    if len(parts) >= 4 and parts[2] == "output":
                        src_step = parts[1]
                        field = ".".join(parts[3:])
                        cp = checkpoints.get(src_step)
                        if cp and cp.output and isinstance(cp.output, dict):
                            resolved[param] = cp.output.get(field)
                        else:
                            resolved[param] = None
                    else:
                        resolved[param] = mapping
                else:
                    resolved[param] = mapping
            else:
                resolved[param] = mapping
        return resolved

    def _resolve_final_output(
        self,
        workflow: WorkflowDefinition,
        initial_inputs: Dict[str, Any],
        checkpoints: Dict[str, StepCheckpoint],
    ) -> Dict[str, Any]:
        """Assemble workflow output from output_mappings or last successful step output."""
        if workflow.output_mappings:
            out: Dict[str, Any] = {}
            for out_key, mapping in workflow.output_mappings.items():
                if mapping.startswith("$inputs."):
                    field = mapping[len("$inputs."):]
                    out[out_key] = initial_inputs.get(field)
                elif mapping.startswith("$steps."):
                    parts = mapping.split(".")
                    if len(parts) >= 4 and parts[2] == "output":
                        src_step = parts[1]
                        field = ".".join(parts[3:])
                        cp = checkpoints.get(src_step)
                        if cp and cp.output and isinstance(cp.output, dict):
                            out[out_key] = cp.output.get(field)
            return out

        for step in reversed(workflow.steps):
            cp = checkpoints.get(step.step_id)
            if cp and cp.status == "COMPLETED" and cp.output:
                return cp.output
        return {}

    def start_workflow(
        self,
        workflow: WorkflowDefinition,
        inputs: Dict[str, Any],
        run_id: Optional[str] = None,
    ) -> WorkflowExecutionState:
        """Start a new durable workflow execution run."""
        self.register_workflow(workflow)
        rid = run_id or f"wf_run_{uuid.uuid4().hex[:10]}"

        state = WorkflowExecutionState(
            run_id=rid,
            workflow_id=workflow.workflow_id,
            status=WorkflowStatus.RUNNING,
            inputs=inputs,
        )

        for step in workflow.steps:
            state.checkpoints[step.step_id] = StepCheckpoint(step_id=step.step_id)

        self._execution_store[rid] = state

        if self.event_gateway:
            self.event_gateway.emit(AgentEvent(
                event_type=EventType.TASK_STARTED,
                run_id=rid,
                input_data={"workflow_id": workflow.workflow_id, "inputs": inputs},
            ))

        return self._execute_state(state, workflow)

    def resume_workflow(
        self,
        run_id: str,
        workflow: Optional[WorkflowDefinition] = None,
    ) -> WorkflowExecutionState:
        """Resume execution of a paused or failed workflow from the last checkpoint."""
        state = self._execution_store.get(run_id)
        if not state:
            raise ValueError(f"Workflow run '{run_id}' not found.")

        wf_def = workflow or self._workflow_definitions.get(state.workflow_id)
        if not wf_def:
            raise ValueError(f"Workflow definition '{state.workflow_id}' not found.")

        state.status = WorkflowStatus.RUNNING
        state.updated_at = datetime.now(timezone.utc).isoformat()
        state.error = None

        logger.info("Resuming durable workflow run '%s' from checkpoint", run_id)
        return self._execute_state(state, wf_def)

    def cancel_workflow(self, run_id: str) -> WorkflowExecutionState:
        """Cancel a running or paused workflow."""
        state = self._execution_store.get(run_id)
        if not state:
            raise ValueError(f"Workflow run '{run_id}' not found.")

        state.status = WorkflowStatus.CANCELLED
        state.updated_at = datetime.now(timezone.utc).isoformat()
        return state

    def _execute_state(
        self,
        state: WorkflowExecutionState,
        workflow: WorkflowDefinition,
    ) -> WorkflowExecutionState:
        """Internal step-by-step runner with idempotency and retry backoff."""
        for step in workflow.steps:
            cp = state.checkpoints.get(step.step_id)
            if not cp:
                cp = StepCheckpoint(step_id=step.step_id)
                state.checkpoints[step.step_id] = cp

            # Skip completed steps (Idempotent resume!)
            if cp.status == "COMPLETED":
                logger.debug("Step '%s' already completed. Skipping.", step.step_id)
                continue

            cp.status = "RUNNING"
            cp.started_at = datetime.now(timezone.utc).isoformat()

            step_inputs = self._resolve_step_inputs(step, state.inputs, state.checkpoints)
            step_success = False
            last_error = None

            # Retry loop with exponential backoff
            max_attempts = max(1, step.max_retries + 1)
            for attempt in range(max_attempts):
                cp.attempt_count += 1
                try:
                    req = ExecutionRequest(
                        capability_id=step.capability_id,
                        version=step.version,
                        inputs=step_inputs,
                        run_id=state.run_id,
                    )
                    res: ExecutionResponse = self.executor.execute(req)

                    if res.status == "SUCCESS":
                        cp.status = "COMPLETED"
                        cp.output = res.output if isinstance(res.output, dict) else {"result": res.output}
                        cp.error = None
                        cp.completed_at = datetime.now(timezone.utc).isoformat()
                        step_success = True
                        break
                    else:
                        last_error = res.error or f"Capability execution returned {res.status}"
                except Exception as e:
                    last_error = str(e)

                if attempt < max_attempts - 1:
                    backoff = step.retry_delay_sec * (2 ** attempt)
                    time.sleep(backoff)

            if not step_success:
                cp.status = "FAILED"
                cp.error = last_error
                cp.completed_at = datetime.now(timezone.utc).isoformat()

                if not step.continue_on_failure:
                    state.status = WorkflowStatus.PAUSED
                    state.error = f"Step '{step.step_id}' failed: {last_error}"
                    state.updated_at = datetime.now(timezone.utc).isoformat()

                    if self.event_gateway:
                        self.event_gateway.emit(AgentEvent(
                            event_type=EventType.TASK_FAILED,
                            run_id=state.run_id,
                            error_message=state.error,
                        ))
                    return state

        # All steps executed or continued
        state.status = WorkflowStatus.COMPLETED
        state.final_output = self._resolve_final_output(workflow, state.inputs, state.checkpoints)
        state.updated_at = datetime.now(timezone.utc).isoformat()

        if self.event_gateway:
            self.event_gateway.emit(AgentEvent(
                event_type=EventType.TASK_COMPLETED,
                run_id=state.run_id,
                output_data={"final_output": state.final_output},
            ))

        return state

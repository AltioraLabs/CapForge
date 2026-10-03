"""CapForge Dynamic Capability Composition Pipeline (discussion.mdx §20).

Allows agents to compose multiple forged capabilities into deterministic or adaptive
Directed Acyclic Graph (DAG) pipelines with variable interpolation, fallback steps,
and granular execution tracing.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from pydantic import BaseModel, Field

from capforge.core.models import ExecutionRequest, ExecutionResponse
from capforge.runtime.executor import CapabilityExecutor

logger = logging.getLogger("capforge.runtime.pipeline")


class PipelineStep(BaseModel):
    """Specification of a single step within a capability pipeline."""

    step_id: str
    capability_id: str
    version: str | None = None
    input_mappings: dict[str, Any] = Field(
        default_factory=dict,
        description="Maps step input parameters to literal values, '$inputs.<key>', or '$steps.<step_id>.output.<key>'",
    )
    continue_on_failure: bool = False
    fallback_capability_id: str | None = None


class CapabilityPipeline(BaseModel):
    """A multi-step capability execution DAG."""

    pipeline_id: str
    name: str
    description: str = ""
    steps: list[PipelineStep] = Field(default_factory=list)
    output_mappings: dict[str, str] = Field(
        default_factory=dict,
        description="Maps pipeline output keys to '$steps.<step_id>.output.<key>' or '$inputs.<key>'",
    )


class PipelineExecutionResponse(BaseModel):
    """Result of running a multi-step capability pipeline."""

    pipeline_id: str
    status: str  # "SUCCESS" | "FAILED" | "PARTIAL"
    total_execution_time_ms: float
    final_output: dict[str, Any] = Field(default_factory=dict)
    step_results: dict[str, ExecutionResponse] = Field(default_factory=dict)
    error: str | None = None


class CapabilityPipelineRunner:
    """Executes capability composition pipelines with parameter interpolation and fault isolation."""

    def __init__(self, executor: CapabilityExecutor):
        self.executor = executor

    def run_pipeline(
        self,
        pipeline: CapabilityPipeline,
        initial_inputs: dict[str, Any],
        timeout_sec: float = 60.0,
    ) -> PipelineExecutionResponse:
        """Execute all steps in pipeline in topological order."""
        start_time = time.perf_counter()
        step_results: dict[str, ExecutionResponse] = {}
        all_success = True

        for step in pipeline.steps:
            # 1. Resolve inputs for step
            resolved_inputs = self._resolve_inputs(
                step.input_mappings,
                initial_inputs,
                step_results,
            )

            # 2. Execute capability
            req = ExecutionRequest(
                capability_id=step.capability_id,
                version=step.version,
                inputs=resolved_inputs,
                timeout_sec=timeout_sec,
            )
            resp = self.executor.execute(req)

            # 3. Handle fallback if step failed
            if resp.status != "SUCCESS" and step.fallback_capability_id:
                logger.warning(
                    "Pipeline step '%s' failed. Attempting fallback capability '%s'",
                    step.step_id,
                    step.fallback_capability_id,
                )
                fallback_req = ExecutionRequest(
                    capability_id=step.fallback_capability_id,
                    inputs=resolved_inputs,
                    timeout_sec=timeout_sec,
                )
                resp = self.executor.execute(fallback_req)

            step_results[step.step_id] = resp

            if resp.status != "SUCCESS":
                all_success = False
                if not step.continue_on_failure:
                    elapsed = (time.perf_counter() - start_time) * 1000.0
                    return PipelineExecutionResponse(
                        pipeline_id=pipeline.pipeline_id,
                        status="FAILED",
                        total_execution_time_ms=round(elapsed, 2),
                        final_output={},
                        step_results=step_results,
                        error=f"Step '{step.step_id}' failed: {resp.error}",
                    )

        # 4. Resolve final pipeline output
        final_output = self._resolve_outputs(pipeline.output_mappings, initial_inputs, step_results)
        elapsed = (time.perf_counter() - start_time) * 1000.0
        overall_status = "SUCCESS" if all_success else "PARTIAL"

        return PipelineExecutionResponse(
            pipeline_id=pipeline.pipeline_id,
            status=overall_status,
            total_execution_time_ms=round(elapsed, 2),
            final_output=final_output,
            step_results=step_results,
            error=None if all_success else "One or more non-fatal steps failed.",
        )

    def _resolve_inputs(
        self,
        mappings: dict[str, Any],
        initial_inputs: dict[str, Any],
        step_results: dict[str, ExecutionResponse],
    ) -> dict[str, Any]:
        """Interpolate variables like $inputs.key or $steps.step1.output.field."""
        resolved: dict[str, Any] = {}
        for param, mapping in mappings.items():
            if isinstance(mapping, str) and mapping.startswith("$"):
                resolved[param] = self._resolve_expression(mapping, initial_inputs, step_results)
            else:
                resolved[param] = mapping
        return resolved

    def _resolve_outputs(
        self,
        mappings: dict[str, str],
        initial_inputs: dict[str, Any],
        step_results: dict[str, ExecutionResponse],
    ) -> dict[str, Any]:
        """Construct final pipeline dictionary from declared output mappings."""
        out: dict[str, Any] = {}
        for out_key, expr in mappings.items():
            out[out_key] = self._resolve_expression(expr, initial_inputs, step_results)
        return out

    def _resolve_expression(
        self,
        expr: str,
        initial_inputs: dict[str, Any],
        step_results: dict[str, ExecutionResponse],
    ) -> Any:
        """Resolve a dotted path expression."""
        if not expr.startswith("$"):
            return expr

        tokens = expr.lstrip("$").split(".")
        root = tokens[0]

        if root == "inputs":
            val = initial_inputs
            for t in tokens[1:]:
                if isinstance(val, dict):
                    val = val.get(t)
                else:
                    return None
            return val

        elif root == "steps" and len(tokens) >= 3:
            step_id = tokens[1]
            if step_id not in step_results:
                return None
            step_resp = step_results[step_id]

            if tokens[2] == "output":
                val = step_resp.output
                for t in tokens[3:]:
                    if isinstance(val, dict):
                        val = val.get(t)
                    else:
                        return None
                return val
            elif tokens[2] == "status":
                return step_resp.status

        return None

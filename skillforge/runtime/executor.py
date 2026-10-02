"""SkillForge Capability Execution Runtime.

Handles capability dispatch, input parameter validation, sandbox invocation,
and execution outcome logging.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional
from datetime import datetime, timezone

from skillforge.core.models import (
    Capability,
    CapabilityStatus,
    ExecutionRequest,
    ExecutionResponse
)
from skillforge.core.exceptions import CapabilityNotFoundError
from skillforge.registry.store import CapabilityRegistry
from skillforge.verification.sandbox import SandboxRunner


class CapabilityExecutor:
    """Executes registered capabilities with input validation and sandbox containment."""

    def __init__(self, registry: CapabilityRegistry, sandbox: Optional[SandboxRunner] = None):
        self.registry = registry
        self.sandbox = sandbox or SandboxRunner()

    def execute(self, request: ExecutionRequest) -> ExecutionResponse:
        """Execute a capability by ID and optional version constraint."""
        start_time = time.perf_counter()

        # 1. Fetch capability
        cap = self.registry.get(request.capability_id, version=request.version)
        if not cap:
            raise CapabilityNotFoundError(request.capability_id, request.version)

        # 2. Validate required inputs
        for param_name, param_spec in cap.inputs.items():
            if param_spec.required and param_name not in request.inputs:
                if param_spec.default is not None:
                    request.inputs[param_name] = param_spec.default
                else:
                    elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                    return ExecutionResponse(
                        capability_id=cap.id,
                        version=cap.version,
                        status="FAILED",
                        output=None,
                        error=f"Missing required parameter '{param_name}'",
                        execution_time_ms=round(elapsed_ms, 2)
                    )

        # 3. Execute in Sandbox
        run_res = self.sandbox.execute_code(
            code_body=cap.code_body,
            entrypoint=cap.entrypoint_function,
            inputs=request.inputs,
            timeout_sec=request.timeout_sec
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        return ExecutionResponse(
            capability_id=cap.id,
            version=cap.version,
            status="SUCCESS" if run_res["success"] else "FAILED",
            output=run_res["output"],
            error=run_res["error"],
            execution_time_ms=round(elapsed_ms, 2)
        )

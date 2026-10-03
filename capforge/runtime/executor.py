"""CapForge Capability Execution Runtime.

Handles capability dispatch, input parameter validation, firewall checks,
sandbox invocation, and execution outcome logging.
"""

from __future__ import annotations

import logging
import time

from capforge.core.exceptions import CapabilityNotFoundError
from capforge.core.governance import CapabilityFirewall
from capforge.core.models import (
    CapabilityStatus,
    ExecutionRequest,
    ExecutionResponse,
)
from capforge.core.telemetry import trace_manager
from capforge.registry.store import CapabilityRegistry
from capforge.security.trust_chain import TamperDetectedError, TrustChain
from capforge.verification.sandbox import SandboxRunner

logger = logging.getLogger("capforge.runtime")


class CapabilityExecutor:
    """Executes registered capabilities with input validation, firewall enforcement, and sandbox containment."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        sandbox: SandboxRunner | None = None,
        firewall: CapabilityFirewall | None = None,
        trust_chain: TrustChain | None = None,
        failure_threshold: int = 3,
        auto_rollback_enabled: bool = True,
        enforce_trust: bool = False,
    ):
        self.registry = registry
        self.sandbox = sandbox or SandboxRunner()
        self.firewall = firewall or CapabilityFirewall()
        self.trust_chain = trust_chain
        self.enforce_trust = enforce_trust  # If True, unsigned caps are also blocked
        self.failure_threshold = failure_threshold
        self.auto_rollback_enabled = auto_rollback_enabled
        self._consecutive_failures: dict[str, int] = {}

    def execute(self, request: ExecutionRequest) -> ExecutionResponse:
        """Execute a capability by ID and optional version constraint with OpenTelemetry tracing."""
        with trace_manager.start_span(
            f"capability_execute:{request.capability_id}",
            attributes={
                "capability_id": request.capability_id,
                "version": request.version or "latest",
                "agent_id": request.agent_id or "anonymous",
            },
        ) as span:
            resp = self._execute_internal(request)
            span.set_attribute("status", resp.status)
            span.set_attribute("execution_time_ms", resp.execution_time_ms)
            if resp.status != "SUCCESS":
                span.set_attribute("error", resp.error or "")
            return resp

    def _execute_internal(self, request: ExecutionRequest) -> ExecutionResponse:
        start_time = time.perf_counter()

        # 1. Fetch capability
        cap = self.registry.get(request.capability_id, version=request.version)
        if not cap:
            raise CapabilityNotFoundError(request.capability_id, request.version)

        # 2. Firewall check
        decision = self.firewall.check(cap, request)
        if not decision.allowed:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            logger.warning(
                "Firewall blocked execution of %s: %s",
                cap.id,
                decision.blocked_reason,
            )
            return ExecutionResponse(
                capability_id=cap.id,
                version=cap.version,
                status="BLOCKED",
                output=None,
                error=decision.blocked_reason,
                execution_time_ms=round(elapsed_ms, 2),
            )

        # 3. Trust Chain Verification (tamper detection)
        if self.trust_chain:
            try:
                sig_valid = self.trust_chain.verify(cap)
                if not sig_valid and self.enforce_trust:
                    elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                    return ExecutionResponse(
                        capability_id=cap.id,
                        version=cap.version,
                        status="BLOCKED",
                        output=None,
                        error="TRUST_CHAIN: Capability is unsigned. Enable signing at registration.",
                        execution_time_ms=round(elapsed_ms, 2),
                    )
            except TamperDetectedError as e:
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                logger.error("INTEGRITY VIOLATION during execution of '%s': %s", cap.id, e)
                return ExecutionResponse(
                    capability_id=cap.id,
                    version=cap.version,
                    status="BLOCKED",
                    output=None,
                    error=f"INTEGRITY_VIOLATION: {e}",
                    execution_time_ms=round(elapsed_ms, 2),
                )

        # 4. Validate required inputs
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
                        execution_time_ms=round(elapsed_ms, 2),
                    )

        # 4. Execute in Sandbox
        run_res = self.sandbox.execute_code(
            code_body=cap.code_body,
            entrypoint=cap.entrypoint_function,
            inputs=request.inputs,
            timeout_sec=request.timeout_sec,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        logger.info(
            "Executed %s v%s: %s in %.1fms",
            cap.id,
            cap.version,
            "SUCCESS" if run_res["success"] else "FAILED",
            elapsed_ms,
        )

        # Circuit Breaker & Failure Tracking
        if run_res["success"]:
            self._consecutive_failures[cap.id] = 0
            exec_status = "SUCCESS"
            err_msg = None
        else:
            exec_status = "FAILED"
            err_msg = run_res["error"]
            current_fails = self._consecutive_failures.get(cap.id, 0) + 1
            self._consecutive_failures[cap.id] = current_fails
            logger.warning(
                "Capability '%s' failed in runtime (%d/%d consecutive failures)",
                cap.id,
                current_fails,
                self.failure_threshold,
            )

            # Check if threshold reached for auto-rollback
            if self.auto_rollback_enabled and current_fails >= self.failure_threshold and cap.parent_version:
                prior_cap = self.registry.get(cap.id, version=cap.parent_version)
                if prior_cap:
                    logger.error(
                        "Circuit breaker tripped for '%s' v%s after %d failures. Initiating auto-rollback to v%s",
                        cap.id,
                        cap.version,
                        current_fails,
                        prior_cap.version,
                    )
                    # Quarantine failing version
                    cap.status = CapabilityStatus.QUARANTINED
                    self.registry.register(cap)
                    # Activate prior version
                    prior_cap.status = CapabilityStatus.ACTIVE
                    self.registry.register(prior_cap)
                    self._consecutive_failures[cap.id] = 0
                    err_msg = f"{err_msg} [CIRCUIT BREAKER: Auto-rolled back to v{prior_cap.version}]"

        return ExecutionResponse(
            capability_id=cap.id,
            version=cap.version,
            status=exec_status,
            output=run_res["output"],
            error=err_msg,
            execution_time_ms=round(elapsed_ms, 2),
        )

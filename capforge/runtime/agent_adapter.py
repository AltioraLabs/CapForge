"""CapForge Framework-Agnostic Agent Adapter.

Provides the runtime bridge between user tasks, gap detection, autonomous acquisition,
closed-loop verification, promotion, and capability execution.

Integrates the Event Gateway, Experience Filter, Risk Engine, and Capability Graph.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from capforge.acquisition.engine import AcquisitionEngine
from capforge.core.events import EventGateway, ExperienceFilter
from capforge.core.governance import CapabilityFirewall, RiskEngine
from capforge.core.models import (
    AgentEvent,
    Capability,
    CapabilityGap,
    CapabilityStatus,
    EventType,
    ExecutionRequest,
    ExecutionResponse,
    PromotionPolicy,
    VerificationResult,
)
from capforge.discovery.capability_graph import CapabilityGraph
from capforge.discovery.gap_detector import CapabilityGapDetector
from capforge.registry.store import CapabilityRegistry
from capforge.runtime.executor import CapabilityExecutor
from capforge.verification.evaluator import CapabilityEvaluator
from capforge.verification.repair import AutoRepairEngine
from capforge.verification.test_generator import TestGenerator
from capforge.versioning.manager import VersionManager

logger = logging.getLogger("capforge.agent")


class AgentLifecycleTrace(BaseModel):
    task: str
    gap: CapabilityGap
    acquired_capability: Capability | None = None
    verification: VerificationResult | None = None
    repair_iterations: int = 0
    execution_result: ExecutionResponse | None = None
    reused_primitives: list[str] = Field(default_factory=list)
    risk_level: str | None = None
    firewall_blocked: bool = False
    async_job_id: str | None = None
    async_status: str | None = None
    pending_review: bool = False
    review_ticket_id: str | None = None


class CapForgeAgent:
    """The complete CapForge Capability Lifecycle Controller for AI Agents."""

    def __init__(self, registry: CapabilityRegistry | None = None):
        self.registry = registry or CapabilityRegistry()
        self.gap_detector = CapabilityGapDetector(self.registry)
        self.acquisition_engine = AcquisitionEngine()
        self.test_generator = TestGenerator()
        self.evaluator = CapabilityEvaluator()
        self.repair_engine = AutoRepairEngine(self.evaluator)
        self.risk_engine = RiskEngine()
        self.version_manager = VersionManager(self.registry, self.risk_engine)
        self.firewall = CapabilityFirewall(self.risk_engine)
        self.executor = CapabilityExecutor(self.registry, firewall=self.firewall)
        self.event_gateway = EventGateway()
        self.experience_filter = ExperienceFilter()
        self.capability_graph = CapabilityGraph(self.registry)
        self._async_manager = None

    @property
    def async_manager(self):
        if self._async_manager is None:
            from capforge.runtime.async_synthesis import AsyncSynthesisManager
            self._async_manager = AsyncSynthesisManager(agent=self)
        return self._async_manager

    def handle_task(
        self,
        task_intent: str,
        task_inputs: dict[str, Any],
        knowledge_spec: dict[str, Any] | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        async_mode: bool = False,
        promotion_policy: PromotionPolicy | None = None,
        fallback_output: Any = None,
    ) -> AgentLifecycleTrace:
        """Execute the full CapForge Capability Lifecycle for an agent task."""

        # Emit task_started event
        self.event_gateway.emit(
            AgentEvent(
                event_type=EventType.TASK_STARTED,
                agent_id=agent_id,
                run_id=run_id,
                input_data={"task_intent": task_intent},
            )
        )

        trace = AgentLifecycleTrace(
            task=task_intent,
            gap=self.gap_detector.evaluate_task(task_intent),
        )

        target_cap_id = None

        # Step 1: Capability Gap Resolution
        if trace.gap.gap_detected:
            # Emit gap detection event
            self.event_gateway.emit(
                AgentEvent(
                    event_type=EventType.CAPABILITY_GAP_DETECTED,
                    agent_id=agent_id,
                    run_id=run_id,
                    metadata={"missing": trace.gap.missing_primitives},
                )
            )

            # If async mode requested, return fallback immediately without blocking
            if async_mode:
                fallback_resp = self.async_manager.submit_synthesis(
                    task_intent=task_intent,
                    gap=trace.gap,
                    knowledge_spec=knowledge_spec,
                    promotion_policy=promotion_policy,
                    fallback_output=fallback_output,
                )
                trace.async_job_id = fallback_resp.job_id
                trace.async_status = fallback_resp.status
                trace.execution_result = ExecutionResponse(
                    capability_id=trace.gap.missing_primitives[0] if trace.gap.missing_primitives else "pending_synthesis",
                    version="0.0.0",
                    status="ASYNC_SYNTHESIS_QUEUED",
                    output=fallback_output,
                    execution_time_ms=0.0,
                )
                return trace

            # We must acquire and forge a new capability
            spec = knowledge_spec or {
                "id": trace.gap.missing_primitives[0] if trace.gap.missing_primitives else "custom_capability",
                "name": task_intent[:40],
                "description": task_intent,
            }
            candidate = self.acquisition_engine.acquire_from_spec(spec, trace.gap)
            candidate.verification_tests = self.test_generator.enrich_tests(candidate)

            self.event_gateway.emit(
                AgentEvent(
                    event_type=EventType.CAPABILITY_GENERATED,
                    agent_id=agent_id,
                    run_id=run_id,
                    metadata={"capability_id": candidate.id, "version": candidate.version},
                )
            )

            # Step 2: Sandbox Verification & Self-Healing
            repaired_cap, verif_result, iters = self.repair_engine.repair_until_pass(candidate)
            trace.acquired_capability = repaired_cap
            trace.verification = verif_result
            trace.repair_iterations = iters

            self.event_gateway.emit(
                AgentEvent(
                    event_type=EventType.CAPABILITY_VALIDATED,
                    agent_id=agent_id,
                    run_id=run_id,
                    metadata={
                        "capability_id": repaired_cap.id,
                        "passed": verif_result.passed,
                        "tests_passed": verif_result.tests_passed,
                        "tests_run": verif_result.tests_run,
                    },
                )
            )

            # Step 3: Risk Assessment & Lifecycle Promotion
            if verif_result.passed:
                policy = promotion_policy or PromotionPolicy()
                can_promote, risk, ticket = self.risk_engine.evaluate_promotion(repaired_cap, policy)
                trace.risk_level = risk.risk_level.value

                if can_promote:
                    verif, _risk = self.version_manager.promote_to_active(repaired_cap, skip_risk_check=True)
                    target_cap_id = repaired_cap.id

                    # Update capability graph
                    self.capability_graph.add_capability(repaired_cap)

                    self.event_gateway.emit(
                        AgentEvent(
                            event_type=EventType.SKILL_PROMOTED,
                            agent_id=agent_id,
                            run_id=run_id,
                            metadata={"capability_id": repaired_cap.id, "version": repaired_cap.version},
                        )
                    )
                else:
                    repaired_cap.status = CapabilityStatus.PENDING_REVIEW
                    self.registry.register(repaired_cap)
                    trace.pending_review = True
                    trace.review_ticket_id = ticket.ticket_id if ticket else None

                    self.event_gateway.emit(
                        AgentEvent(
                            event_type=EventType.SKILL_REJECTED,
                            agent_id=agent_id,
                            run_id=run_id,
                            metadata={
                                "capability_id": repaired_cap.id,
                                "status": "PENDING_REVIEW",
                                "ticket_id": ticket.ticket_id if ticket else None,
                            },
                        )
                    )
                    return trace
            else:
                self.event_gateway.emit(
                    AgentEvent(
                        event_type=EventType.SKILL_REJECTED,
                        agent_id=agent_id,
                        run_id=run_id,
                        metadata={"capability_id": repaired_cap.id, "reason": "verification_failed"},
                    )
                )
                return trace
        else:
            # Direct reuse from Capability Registry
            matched_pairs = self.gap_detector.matcher.find_matches(task_intent, threshold=0.30)
            if matched_pairs:
                target_cap_id = matched_pairs[0][0].id
            else:
                matches = self.registry.list_capabilities()
                if matches:
                    target_cap_id = matches[0].id
            if target_cap_id:
                trace.reused_primitives.append(target_cap_id)

        # Step 4: Execute Capability in Sandbox
        if target_cap_id:
            req = ExecutionRequest(
                capability_id=target_cap_id,
                inputs=task_inputs,
                agent_id=agent_id,
                run_id=run_id,
            )
            result = self.executor.execute(req)
            trace.execution_result = result

            if result.status == "BLOCKED":
                trace.firewall_blocked = True

            # Emit completion event
            event_type = EventType.TASK_COMPLETED if result.status == "SUCCESS" else EventType.TASK_FAILED
            self.event_gateway.emit(
                AgentEvent(
                    event_type=event_type,
                    agent_id=agent_id,
                    run_id=run_id,
                    output_data={"status": result.status},
                )
            )

        return trace


class LangGraphAdapter:
    """Bridge for integrating CapForge capabilities into LangGraph StateGraphs."""

    def __init__(self, client: Any | None = None, capforge_agent: CapForgeAgent | None = None):
        if capforge_agent is not None:
            self.agent = capforge_agent
            self.client = client
        elif client is not None and hasattr(client, "agent"):
            self.agent = client.agent
            self.client = client
        else:
            self.agent = CapForgeAgent()
            self.client = None

    def create_langgraph_node(self, capability_id: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
        """Create a stateful node callable compatible with LangGraph StateGraph."""
        agent = self.agent

        def tool_node(state: dict[str, Any]) -> dict[str, Any]:
            inputs = state.get("tool_inputs") or state.get("inputs") or {}
            cap = agent.registry.get(capability_id)
            if not cap:
                return {**state, "error": "CAPABILITY_NOT_FOUND", "missing_capability": capability_id}
            req = ExecutionRequest(capability_id=capability_id, inputs=inputs)
            res = agent.executor.execute(req)
            if res.status != "SUCCESS":
                return {**state, "error": res.error or "EXECUTION_FAILED", "result": None}
            return {**state, "result": res.output, "error": None}

        return tool_node

    def create_evolution_node(self) -> Callable[[dict[str, Any]], dict[str, Any]]:
        """Create an autonomous evolution fallback node for LangGraph StateGraph."""
        agent = self.agent

        def evolution_node(state: dict[str, Any]) -> dict[str, Any]:
            task_intent = state.get("task") or state.get("task_intent") or state.get("missing_capability") or "unknown_task"
            inputs = state.get("tool_inputs") or state.get("inputs") or {}
            trace = agent.handle_task(task_intent=task_intent, task_inputs=inputs)
            if trace.execution_result and trace.execution_result.status == "SUCCESS":
                return {
                    **state,
                    "result": trace.execution_result.output,
                    "error": None,
                    "evolved_capability": trace.acquired_capability.id if trace.acquired_capability else None,
                }
            return {**state, "error": "EVOLUTION_FAILED", "result": None}

        return evolution_node


"""CapForge Framework-Agnostic Agent Adapter.

Provides the runtime bridge between user tasks, gap detection, autonomous acquisition,
closed-loop verification, promotion, and capability execution.

Integrates the Event Gateway, Experience Filter, Risk Engine, and Capability Graph.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from capforge.acquisition.engine import AcquisitionEngine
from capforge.core.events import EventGateway, ExperienceFilter
from capforge.core.governance import CapabilityFirewall, RiskEngine
from capforge.core.models import (
    AgentEvent,
    Capability,
    CapabilityGap,
    EventType,
    ExecutionRequest,
    ExecutionResponse,
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

    def handle_task(
        self,
        task_intent: str,
        task_inputs: dict[str, Any],
        knowledge_spec: dict[str, Any] | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
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

            # We must acquire and forge a new capability
            spec = knowledge_spec or {
                "id": trace.gap.missing_primitives[0] if trace.gap.missing_primitives else "custom_capability",
                "name": task_intent[:40],
                "description": task_intent,
            }
            candidate = self.acquisition_engine.acquire_from_spec(spec, trace.gap)
            candidate.verification_tests = self.test_generator.enrich_tests(candidate)

            # Step 2: Sandbox Verification & Self-Healing
            repaired_cap, verif_result, iters = self.repair_engine.repair_until_pass(candidate)
            trace.acquired_capability = repaired_cap
            trace.verification = verif_result
            trace.repair_iterations = iters

            # Step 3: Risk Assessment & Lifecycle Promotion
            if verif_result.passed:
                risk = self.risk_engine.assess(repaired_cap)
                trace.risk_level = risk.risk_level.value

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
            matches = self.registry.list_capabilities()
            if matches:
                target_cap_id = matches[0].id
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

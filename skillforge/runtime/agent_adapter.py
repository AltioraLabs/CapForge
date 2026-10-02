"""SkillForge Framework-Agnostic Agent Adapter.

Provides the runtime bridge between user tasks, gap detection, autonomous acquisition,
closed-loop verification, promotion, and capability execution.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from skillforge.registry.store import CapabilityRegistry
from skillforge.discovery.gap_detector import CapabilityGapDetector
from skillforge.acquisition.engine import AcquisitionEngine
from skillforge.verification.test_generator import TestGenerator
from skillforge.verification.evaluator import CapabilityEvaluator
from skillforge.verification.repair import AutoRepairEngine
from skillforge.versioning.manager import VersionManager
from skillforge.runtime.executor import CapabilityExecutor
from skillforge.core.models import (
    Capability,
    CapabilityGap,
    ExecutionRequest,
    ExecutionResponse,
    VerificationResult
)


class AgentLifecycleTrace(BaseModel):
    task: str
    gap: CapabilityGap
    acquired_capability: Optional[Capability] = None
    verification: Optional[VerificationResult] = None
    repair_iterations: int = 0
    execution_result: Optional[ExecutionResponse] = None
    reused_primitives: list[str] = Field(default_factory=list)


class SkillForgeAgent:
    """The complete SkillForge Capability Lifecycle Controller for AI Agents."""

    def __init__(self, registry: Optional[CapabilityRegistry] = None):
        self.registry = registry or CapabilityRegistry()
        self.gap_detector = CapabilityGapDetector(self.registry)
        self.acquisition_engine = AcquisitionEngine()
        self.test_generator = TestGenerator()
        self.evaluator = CapabilityEvaluator()
        self.repair_engine = AutoRepairEngine(self.evaluator)
        self.version_manager = VersionManager(self.registry)
        self.executor = CapabilityExecutor(self.registry)

    def handle_task(
        self,
        task_intent: str,
        task_inputs: Dict[str, Any],
        knowledge_spec: Optional[Dict[str, Any]] = None
    ) -> AgentLifecycleTrace:
        """Execute the full SkillForge Capability Lifecycle for an agent task."""
        trace = AgentLifecycleTrace(task=task_intent, gap=self.gap_detector.evaluate_task(task_intent))

        target_cap_id = None

        # Step 1: Capability Gap Resolution
        if trace.gap.gap_detected:
            # We must acquire and forge a new capability
            spec = knowledge_spec or {
                "id": trace.gap.missing_primitives[0] if trace.gap.missing_primitives else "custom_capability",
                "name": task_intent[:40],
                "description": task_intent
            }
            candidate = self.acquisition_engine.acquire_from_spec(spec, trace.gap)
            candidate.verification_tests = self.test_generator.enrich_tests(candidate)

            # Step 2: Sandbox Verification & Self-Healing
            repaired_cap, verif_result, iters = self.repair_engine.repair_until_pass(candidate)
            trace.acquired_capability = repaired_cap
            trace.verification = verif_result
            trace.repair_iterations = iters

            # Step 3: Lifecycle Promotion & Regression Safeguard
            if verif_result.passed:
                self.version_manager.promote_to_active(repaired_cap)
                target_cap_id = repaired_cap.id
            else:
                # Could not achieve passing verification
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
                inputs=task_inputs
            )
            trace.execution_result = self.executor.execute(req)

        return trace

"""CapForge Capability Gap Detector.

Evaluates task requirements against the active Capability Registry.
Detects missing capabilities and formulates an actionable acquisition specification.
"""

from __future__ import annotations

from capforge.core.models import CapabilityGap
from capforge.discovery.analyzer import DecomposedTask, TaskAnalyzer
from capforge.registry.search import CapabilityMatcher
from capforge.registry.store import CapabilityRegistry


class CapabilityGapDetector:
    """Detects when an agent lacks necessary capabilities for a task."""

    def __init__(self, registry: CapabilityRegistry):
        self.registry = registry
        self.matcher = CapabilityMatcher(registry)
        self.analyzer = TaskAnalyzer()

    def evaluate_task(self, task_intent: str) -> CapabilityGap:
        """Analyze a user task and determine if a capability gap exists."""
        decomposed: DecomposedTask = self.analyzer.analyze(task_intent)

        available_primitives: list[str] = []
        missing_primitives: list[str] = []

        for prim in decomposed.required_primitives:
            matches = self.matcher.find_matches(prim, threshold=0.60, limit=1)
            if matches:
                available_primitives.append(prim)
            else:
                missing_primitives.append(prim)

        # Check for direct match of the whole task intent
        task_matches = self.matcher.find_matches(task_intent, threshold=0.50, limit=1)
        if task_matches and task_matches[0][1] >= 0.50:
            gap_detected = False
            missing_primitives = []
        else:
            gap_detected = len(missing_primitives) > 0

        # Suggested acquisition sources
        sources: list[str] = []
        if decomposed.target_service_or_entity != "generic_service":
            clean_svc = decomposed.target_service_or_entity.lower().replace(" ", "_")
            sources.append(f"docs://{clean_svc}/api-reference.json")
            sources.append(f"https://api.{clean_svc}.io/openapi.json")
            sources.append(f"github://specs/{clean_svc}-sdk")
        else:
            sources.append("https://spec.openapis.org/v3.0.3.json")

        rationale = ""
        if gap_detected:
            missing_str = ", ".join(f"'{m}'" for m in missing_primitives) if missing_primitives else "overall procedure"
            rationale = (
                f"Capability gap detected for task. Missing required primitives: [{missing_str}]. "
                f"Agent cannot safely execute this without acquiring and validating a new capability."
            )
        else:
            rationale = "All required primitives and procedures are available in the Capability Registry."

        return CapabilityGap(
            task_intent=task_intent,
            gap_detected=gap_detected,
            missing_primitives=missing_primitives,
            available_primitives=available_primitives,
            confidence=0.95 if gap_detected else 0.85,
            suggested_acquisition_sources=sources,
            rationale=rationale,
        )

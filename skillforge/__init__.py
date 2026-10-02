"""SkillForge: Autonomous Capability Acquisition, Verification, and Evolution Runtime for AI Agents."""

__version__ = "0.1.0"

from skillforge.core.models import (
    Capability,
    CapabilityGap,
    CapabilityStatus,
    ExecutionRequest,
    ExecutionResponse,
    TestCase,
    TestType,
    VerificationResult
)
from skillforge.registry.store import CapabilityRegistry
from skillforge.discovery.gap_detector import CapabilityGapDetector
from skillforge.acquisition.engine import AcquisitionEngine
from skillforge.verification.evaluator import CapabilityEvaluator
from skillforge.verification.repair import AutoRepairEngine
from skillforge.versioning.manager import VersionManager
from skillforge.runtime.agent_adapter import SkillForgeAgent

__all__ = [
    "Capability",
    "CapabilityGap",
    "CapabilityStatus",
    "ExecutionRequest",
    "ExecutionResponse",
    "TestCase",
    "TestType",
    "VerificationResult",
    "CapabilityRegistry",
    "CapabilityGapDetector",
    "AcquisitionEngine",
    "CapabilityEvaluator",
    "AutoRepairEngine",
    "VersionManager",
    "SkillForgeAgent"
]

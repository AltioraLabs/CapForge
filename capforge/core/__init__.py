"""CapForge Core Module — Models, Configuration, Events, Governance, Exceptions."""

from capforge.core.budget import BudgetConfig, EvolutionBudgetManager, budget_manager
from capforge.core.config import settings, setup_logging
from capforge.core.events import EventGateway, ExperienceFilter
from capforge.core.exceptions import (
    CapabilityNotFoundError,
    CapForgeError,
    RegressionDetectedError,
    SandboxExecutionError,
    VerificationFailedError,
)
from capforge.core.governance import CapabilityFirewall, FirewallDecision, RiskAssessment, RiskEngine
from capforge.core.models import (
    AgentEvent,
    Capability,
    CapabilityDependency,
    CapabilityGap,
    CapabilityStatus,
    CapabilityType,
    EventType,
    ExecutionMode,
    ExecutionRequest,
    ExecutionResponse,
    ParameterSpec,
    Provenance,
    RiskLevel,
    TestCase,
    TestResult,
    TestType,
    ToolPermissions,
    ToolRequirement,
    VerificationResult,
)
from capforge.core.trigger_engine import TriggerEngine, TriggerEvent, TriggerType, trigger_engine

"""CapForge: Autonomous Capability Acquisition, Verification, and Evolution Runtime for AI Agents."""

from __future__ import annotations

__version__ = "1.2.0"

# Core models are imported eagerly — they are pure data classes with no side effects
from capforge.core.models import (
    AgentEvent,
    Capability,
    CapabilityGap,
    CapabilityStatus,
    CapabilityType,
    EventType,
    ExecutionRequest,
    ExecutionResponse,
    Provenance,
    RiskLevel,
    TestCase,
    TestType,
    ToolPermissions,
    VerificationResult,
)

# All other imports are lazy to avoid circular import chains.
# Access them as `capforge.CapabilityRegistry` etc. — they load on first use.
_LAZY_IMPORTS = {
    # Schemas & Contracts
    "CapabilitySchema": "capforge.core.schemas",
    "FieldSchema": "capforge.core.schemas",
    # Distributed Storage
    "PostgresCapabilityRegistry": "capforge.registry.store_postgres",
    "S3ArtifactStore": "capforge.registry.store_s3",
    # Sandbox Drivers
    "WasmSandboxRunner": "capforge.verification.sandbox_wasm",
    "get_sandbox_driver": "capforge.verification.sandbox",
    "ProcessSandboxDriver": "capforge.verification.sandbox",
    "DockerSandboxDriver": "capforge.verification.sandbox",
    "WasmSandboxDriver": "capforge.verification.sandbox",
    # Telemetry Semantics
    "GenAISemanticConventions": "capforge.core.telemetry",
    "record_llm_call": "capforge.core.telemetry",
    # Events
    "EventGateway": "capforge.core.events",
    "ExperienceFilter": "capforge.core.events",
    # Governance
    "CapabilityFirewall": "capforge.core.governance",
    "HumanReviewTicket": "capforge.core.governance",
    "RiskEngine": "capforge.core.governance",
    # Telemetry
    "Span": "capforge.core.telemetry",
    "SpanContext": "capforge.core.telemetry",
    "TraceManager": "capforge.core.telemetry",
    "trace_manager": "capforge.core.telemetry",
    # Registry
    "CapabilityRegistry": "capforge.registry.store",
    "DenseVectorEmbeddingEngine": "capforge.registry.vector_store",
    "SemanticVectorIndex": "capforge.registry.vector_store",
    # Discovery
    "CapabilityGapDetector": "capforge.discovery.gap_detector",
    "CapabilityGraph": "capforge.discovery.capability_graph",
    # Acquisition
    "AcquisitionEngine": "capforge.acquisition.engine",
    "LearningJob": "capforge.acquisition.jobs",
    "LearningJobManager": "capforge.acquisition.jobs",
    "LearningJobWorker": "capforge.acquisition.worker",
    # Verification
    "CapabilityEvaluator": "capforge.verification.evaluator",
    "AutoRepairEngine": "capforge.verification.repair",
    "DockerSandboxRunner": "capforge.verification.sandbox_docker",
    # Versioning
    "VersionManager": "capforge.versioning.manager",
    # Runtime
    "CapForgeAgent": "capforge.runtime.agent_adapter",
    "CapabilityPipeline": "capforge.runtime.pipeline",
    "CapabilityPipelineRunner": "capforge.runtime.pipeline",
    "PipelineExecutionResponse": "capforge.runtime.pipeline",
    "PipelineStep": "capforge.runtime.pipeline",
    "DurableWorkflowEngine": "capforge.runtime.durable_workflow",
    "WorkflowDefinition": "capforge.runtime.durable_workflow",
    "WorkflowExecutionState": "capforge.runtime.durable_workflow",
    "WorkflowStatus": "capforge.runtime.durable_workflow",
    "WorkflowStep": "capforge.runtime.durable_workflow",
    "StepCheckpoint": "capforge.runtime.durable_workflow",
    # Stream Broker
    "BaseEventBroker": "capforge.events.broker",
    "InMemoryStreamBroker": "capforge.events.broker",
    "RedisStreamBroker": "capforge.events.broker",
    "StreamMessage": "capforge.events.broker",
    # Auth
    "APIKeyRecord": "capforge.server.auth",
    "AuthManager": "capforge.server.auth",
    "UserRole": "capforge.server.auth",
    "auth_manager": "capforge.server.auth",
    # Adapters
    "OpenAIAgentAdapter": "capforge.adapter.openai_adapter",
    "CrewAIAgentAdapter": "capforge.adapter.crewai_adapter",
    # MCP
    "CapForgeMCPServer": "capforge.mcp.server",
    # Security
    "CodeGuardian": "capforge.security.code_guardian",
    "AdversarialTester": "capforge.security.adversarial_tester",
    "TrustChain": "capforge.security.trust_chain",
    "TracePrivacyFilter": "capforge.security.privacy_filter",
    "privacy_filter": "capforge.security.privacy_filter",
    # Budget & Cost Controller
    "EvolutionBudgetManager": "capforge.core.budget",
    "BudgetConfig": "capforge.core.budget",
    "budget_manager": "capforge.core.budget",
    # Trigger Engine
    "TriggerEngine": "capforge.core.trigger_engine",
    "TriggerEvent": "capforge.core.trigger_engine",
    "TriggerType": "capforge.core.trigger_engine",
    "trigger_engine": "capforge.core.trigger_engine",
    # SDK & High-Level Client
    "CapForgeClient": "capforge.sdk",
    "capability": "capforge.sdk",
    "capability_from_function": "capforge.sdk",
    # Webhooks
    "WebhookSubscription": "capforge.events.webhooks",
    "WebhookDelivery": "capforge.events.webhooks",
    "WebhookManager": "capforge.events.webhooks",
    "webhook_manager": "capforge.events.webhooks",
    # Benchmarking
    "BenchmarkSuite": "capforge.verification.benchmark",
    "BenchmarkTask": "capforge.verification.benchmark",
    "BenchmarkRunner": "capforge.verification.benchmark",
    "BenchmarkRegistry": "capforge.verification.benchmark",
    "MultiDimensionalReport": "capforge.verification.benchmark",
    "benchmark_registry": "capforge.verification.benchmark",
    # Config
    "settings": "capforge.core.config",
    "setup_logging": "capforge.core.config",
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        import importlib

        module = importlib.import_module(_LAZY_IMPORTS[name])
        obj = getattr(module, name)
        # Cache in module globals for subsequent accesses
        globals()[name] = obj
        return obj
    raise AttributeError(f"module 'capforge' has no attribute {name!r}")


__all__ = [
    # Core models (eagerly imported)
    "AgentEvent",
    "Capability",
    "CapabilityDependency",
    "CapabilityGap",
    "CapabilityStatus",
    "CapabilityType",
    "EventType",
    "ExecutionMode",
    "ExecutionRequest",
    "ExecutionResponse",
    "ParameterSpec",
    "Provenance",
    "RiskLevel",
    "TestCase",
    "TestResult",
    "TestType",
    "ToolPermissions",
    "VerificationResult",
    # Lazily imported components
        "CapabilitySchema",
    "FieldSchema",
    "PostgresCapabilityRegistry",
    "S3ArtifactStore",
    "WasmSandboxRunner",
    "get_sandbox_driver",
    "GenAISemanticConventions",
    "record_llm_call",
    "AcquisitionJobWorker",
    "AdversarialTester",
    "AutonomousAcquisitionEngine",
    "AutonomousAcquisitionPipeline",
    "BenchmarkRegistry",
    "BenchmarkRunner",
    "BenchmarkSuite",
    "BenchmarkTask",
    "BudgetConfig",
    "CapabilityEvaluator",
    "CapabilityExecutor",
    "CapabilityFirewall",
    "CapabilityGapDetector",
    "CapabilityGraph",
    "CapabilityMatcher",
    "CapabilityRepairLoop",
    "CapabilitySynthesizer",
    "CapForgeMCPServer",
    "CodeGuardian",
    "CompositeCapabilityExecutor",
    "CrewAIAgentAdapter",
    "DockerSandbox",
    "DurableWorkflowEngine",
    "EventGateway",
    "EvolutionBudgetManager",
    "ExecutionPipeline",
    "ExperienceFilter",
    "FirewallDecision",
    "InProcessSandbox",
    "LangGraphAdapter",
    "MultiDimensionalReport",
    "OpenAIAgentAdapter",
    "RegressionSuiteRunner",
    "RiskAssessment",
    "RiskEngine",
    "SemanticCapabilitySearch",
    "StandardAgentAdapter",
    "StreamBroker",
    "SubprocessSandbox",
    "TaskAnalyzer",
    "TestGenerator",
    "TracePrivacyFilter",
    "TriggerEngine",
    "TriggerEvent",
    "TriggerType",
    "TrustChain",
    "VectorStore",
    "VersionManager",
    "benchmark_registry",
    "CapForgeClient",
    "capability",
    "capability_from_function",
    "WebhookSubscription",
    "WebhookDelivery",
    "WebhookManager",
    "webhook_manager",
    "budget_manager",
    "privacy_filter",
    "settings",
    "setup_logging",
    "trigger_engine",
]

# Advanced Capabilities
from capforge.optimization.profiler import OptimizationGap, RuntimeProfiler, profiler  # noqa: E402
from capforge.optimization.transpiler import HotPathAnalyzer, RustTranspiler  # noqa: E402
from capforge.verification.formal import (  # noqa: E402
    PreExecutionContractChecker,
    SMTInvariantVerifier,
    formal_verifier,
)
from capforge.verification.mutation import MutationEngine, MutationReport  # noqa: E402

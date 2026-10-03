"""CapForge Core Data Models.

Defines the first-class Capability object, Gap Detection schemas,
Verification Test Suites, Lifecycle State representations,
Universal Event Model, and Capability Ontology types.
"""

from __future__ import annotations

import enum
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CapabilityStatus(str, enum.Enum):
    EXPERIMENTAL = "EXPERIMENTAL"
    CANDIDATE = "CANDIDATE"
    ACTIVE = "ACTIVE"
    PRODUCTION = "PRODUCTION"
    DEPRECATED = "DEPRECATED"
    QUARANTINED = "QUARANTINED"


class CapabilityType(str, enum.Enum):
    """Capability Ontology types (discussion.mdx §10)."""

    TOOL = "TOOL"
    SKILL = "SKILL"
    WORKFLOW = "WORKFLOW"
    COMPOSITION = "COMPOSITION"
    EVALUATOR = "EVALUATOR"


class ExecutionMode(str, enum.Enum):
    CODE = "CODE"
    PROMPT = "PROMPT"
    HYBRID = "HYBRID"


class TestType(str, enum.Enum):
    HAPPY_PATH = "HAPPY_PATH"
    EDGE_CASE = "EDGE_CASE"
    SECURITY_INVARIANT = "SECURITY_INVARIANT"
    SMOKE = "SMOKE"
    INVARIANT = "INVARIANT"
    PROPERTY = "PROPERTY"


TestType.__test__ = False


class RiskLevel(str, enum.Enum):
    """Risk classification for governance gates (discussion.mdx §26)."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class EventType(str, enum.Enum):
    """Universal Event Model event types (discussion.mdx §9)."""

    AGENT_STARTED = "agent_started"
    AGENT_FINISHED = "agent_finished"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TOOL_CALLED = "tool_called"
    TOOL_SUCCEEDED = "tool_succeeded"
    TOOL_FAILED = "tool_failed"
    SKILL_SELECTED = "skill_selected"
    SKILL_STARTED = "skill_started"
    SKILL_COMPLETED = "skill_completed"
    SKILL_FAILED = "skill_failed"
    CAPABILITY_GAP_DETECTED = "capability_gap_detected"
    LEARNING_STARTED = "learning_started"
    LEARNING_COMPLETED = "learning_completed"
    SKILL_CANDIDATE_CREATED = "skill_candidate_created"
    SKILL_EVALUATED = "skill_evaluated"
    SKILL_PROMOTED = "skill_promoted"
    SKILL_REJECTED = "skill_rejected"
    SKILL_ROLLBACK = "skill_rollback"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class ParameterSpec(BaseModel):
    name: str
    type: str  # e.g., "string", "integer", "boolean", "dict", "list"
    description: str = ""
    required: bool = True
    default: Any | None = None


class TestCase(BaseModel):
    __test__ = False
    id: str
    name: str
    test_type: TestType = TestType.HAPPY_PATH
    inputs: dict[str, Any] = Field(default_factory=dict)
    expected_output_contains: list[str] | None = None
    expected_keys: list[str] | None = None
    assert_expression: str | None = None
    max_timeout_sec: float = 10.0


class TestResult(BaseModel):
    __test__ = False
    test_id: str
    test_type: TestType
    passed: bool
    execution_time_ms: float
    output: Any | None = None
    error_message: str | None = None
    traceback: str | None = None


class VerificationResult(BaseModel):
    capability_id: str
    version: str
    passed: bool
    tests_run: int
    tests_passed: int
    tests_failed: int
    test_details: list[TestResult] = Field(default_factory=list)
    diagnostics: str | None = None
    regression_passed: bool = True
    # Four-Level Evaluation breakdown (discussion.mdx §24)
    structural_valid: bool = True
    functional_score: float = 1.0  # 0.0 - 1.0 (Level 2)
    generalization_score: float = 1.0  # 0.0 - 1.0 (Level 3)
    four_level_report: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CapabilityDependency(BaseModel):
    capability_id: str
    version_constraint: str = ">=1.0.0"
    primitive_type: str | None = None  # e.g., "auth", "pagination", "parser"


class ToolRequirement(BaseModel):
    name: str
    description: str = ""
    permissions: list[str] = Field(default_factory=list)


class ToolPermissions(BaseModel):
    """Permission declarations for a capability (discussion.mdx §27)."""

    filesystem: str = "none"  # "none", "read", "write"
    network: str = "none"  # "none", "restricted", "full"
    github: str = "none"  # "none", "read", "write"
    database: str = "none"  # "none", "read", "write"
    external_apis: str = "none"  # "none", "restricted", "full"


class Provenance(BaseModel):
    """Provenance and auditability (discussion.mdx §15)."""

    source: str = "manual"  # "manual", "web", "github", "documentation", "experience"
    source_url: str | None = None
    retrieval_timestamp: datetime | None = None
    content_hash: str | None = None
    evidence_summary: str = ""
    license_info: str | None = None
    trust_level: float = 1.0  # 0.0 = untrusted, 1.0 = fully trusted
    extraction_method: str = "human"  # "human", "llm_synthesis", "api_spec"


# ---------------------------------------------------------------------------
# Primary Capability Model
# ---------------------------------------------------------------------------


class Capability(BaseModel):
    id: str = Field(description="Unique identifier e.g. 'github_dependency_audit'")
    name: str = Field(description="Human readable name")

    @field_validator("id")
    @classmethod
    def validate_capability_id(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Capability ID cannot be empty.")
        if ".." in clean or clean.startswith("/") or clean.startswith("\\"):
            raise ValueError(f"Path traversal characters detected in capability ID '{clean}'.")
        if not re.match(r"^[a-zA-Z0-9_.-]+$", clean):
            raise ValueError(
                f"Invalid capability ID '{clean}'. Must contain only alphanumeric, underscores, dots, or hyphens."
            )
        return clean

    version: str = Field(default="1.0.0")
    namespace: str = Field(default="default", description="Tenant or organizational namespace")
    status: CapabilityStatus = Field(default=CapabilityStatus.EXPERIMENTAL)
    capability_type: CapabilityType = Field(default=CapabilityType.SKILL)
    description: str = Field(description="What the capability repeatedly accomplishes")
    domain: str = Field(default="general")
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Dependencies & Tools
    dependencies: list[CapabilityDependency] = Field(default_factory=list)
    tools_required: list[ToolRequirement] = Field(default_factory=list)

    # Permissions & Risk
    permissions: ToolPermissions = Field(default_factory=ToolPermissions)
    risk_level: RiskLevel = Field(default=RiskLevel.LOW)

    # Provenance
    provenance: Provenance = Field(default_factory=Provenance)

    # Interface
    inputs: dict[str, ParameterSpec] = Field(default_factory=dict)
    outputs: dict[str, ParameterSpec] = Field(default_factory=dict)

    # Executable Procedure
    execution_mode: ExecutionMode = ExecutionMode.CODE
    code_body: str = Field(description="Python source code implementing the capability function")
    entrypoint_function: str = Field(default="execute")
    prompt_template: str | None = None

    # Quality & Lifecycle
    verification_tests: list[TestCase] = Field(default_factory=list)
    success_rate: float = 1.0
    confidence_score: float = 0.90
    parent_version: str | None = None
    changelog: str = "Initial release"


# ---------------------------------------------------------------------------
# Gap Detection
# ---------------------------------------------------------------------------


class CapabilityGap(BaseModel):
    task_intent: str
    gap_detected: bool
    missing_primitives: list[str] = Field(default_factory=list)
    available_primitives: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    suggested_acquisition_sources: list[str] = Field(default_factory=list)
    rationale: str = ""


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


class ExecutionRequest(BaseModel):
    capability_id: str
    version: str | None = None  # None selects latest ACTIVE version
    inputs: dict[str, Any] = Field(default_factory=dict)
    timeout_sec: float = 30.0
    agent_id: str | None = None
    run_id: str | None = None
    allowed_namespaces: list[str] | None = Field(default=None, description="Allowed tenant namespaces")


class ExecutionResponse(BaseModel):
    capability_id: str
    version: str
    status: str  # "SUCCESS" | "FAILED" | "BLOCKED"
    output: Any | None = None
    error: str | None = None
    execution_time_ms: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Universal Event Model (discussion.mdx §9)
# ---------------------------------------------------------------------------


class AgentEvent(BaseModel):
    """Normalized agent event for the Event Gateway."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType
    run_id: str | None = None
    task_id: str | None = None
    agent_id: str | None = None
    framework: str = "unknown"  # e.g., "langgraph", "openai", "crewai", "custom"

    # Tool context (for tool_* events)
    tool_name: str | None = None
    tool_version: str | None = None

    # Input/Output
    input_data: dict[str, Any] | None = None
    output_data: Any | None = None

    # Error context
    error_type: str | None = None
    error_message: str | None = None

    # Metadata
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

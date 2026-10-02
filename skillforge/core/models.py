"""SkillForge Core Data Models.

Defines the first-class Capability object, Gap Detection schemas,
Verification Test Suites, and Lifecycle State representations.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CapabilityStatus(str, enum.Enum):
    EXPERIMENTAL = "EXPERIMENTAL"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    QUARANTINED = "QUARANTINED"


class ExecutionMode(str, enum.Enum):
    CODE = "CODE"
    PROMPT = "PROMPT"
    HYBRID = "HYBRID"


class TestType(str, enum.Enum):
    HAPPY_PATH = "HAPPY_PATH"
    EDGE_CASE = "EDGE_CASE"
    SECURITY_INVARIANT = "SECURITY_INVARIANT"


TestType.__test__ = False


class ParameterSpec(BaseModel):
    name: str
    type: str  # e.g., "string", "integer", "boolean", "dict", "list"
    description: str = ""
    required: bool = True
    default: Optional[Any] = None


class TestCase(BaseModel):
    __test__ = False
    id: str
    name: str
    test_type: TestType = TestType.HAPPY_PATH
    inputs: Dict[str, Any] = Field(default_factory=dict)
    expected_output_contains: Optional[List[str]] = None
    expected_keys: Optional[List[str]] = None
    assert_expression: Optional[str] = None
    max_timeout_sec: float = 10.0


class TestResult(BaseModel):
    __test__ = False
    test_id: str
    test_type: TestType
    passed: bool
    execution_time_ms: float
    output: Optional[Any] = None
    error_message: Optional[str] = None
    traceback: Optional[str] = None


class VerificationResult(BaseModel):
    capability_id: str
    version: str
    passed: bool
    tests_run: int
    tests_passed: int
    tests_failed: int
    test_details: List[TestResult] = Field(default_factory=list)
    diagnostics: Optional[str] = None
    regression_passed: bool = True
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CapabilityDependency(BaseModel):
    capability_id: str
    version_constraint: str = ">=1.0.0"
    primitive_type: Optional[str] = None  # e.g., "auth", "pagination", "parser"


class ToolRequirement(BaseModel):
    name: str
    description: str = ""
    permissions: List[str] = Field(default_factory=list)


class Capability(BaseModel):
    id: str = Field(description="Unique snake_case identifier e.g. 'github_dependency_audit'")
    name: str = Field(description="Human readable name")
    version: str = Field(default="1.0.0")
    status: CapabilityStatus = Field(default=CapabilityStatus.EXPERIMENTAL)
    description: str = Field(description="What the capability repeatedly accomplishes")
    domain: str = Field(default="general")
    tags: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Dependencies & Tools
    dependencies: List[CapabilityDependency] = Field(default_factory=list)
    tools_required: List[ToolRequirement] = Field(default_factory=list)

    # Interface
    inputs: Dict[str, ParameterSpec] = Field(default_factory=dict)
    outputs: Dict[str, ParameterSpec] = Field(default_factory=dict)

    # Executable Procedure
    execution_mode: ExecutionMode = ExecutionMode.CODE
    code_body: str = Field(description="Python source code implementing the capability function")
    entrypoint_function: str = Field(default="execute")
    prompt_template: Optional[str] = None

    # Quality & Lifecycle
    verification_tests: List[TestCase] = Field(default_factory=list)
    success_rate: float = 1.0
    confidence_score: float = 0.90
    parent_version: Optional[str] = None
    changelog: str = "Initial release"


class CapabilityGap(BaseModel):
    task_intent: str
    gap_detected: bool
    missing_primitives: List[str] = Field(default_factory=list)
    available_primitives: List[str] = Field(default_factory=list)
    confidence: float = 1.0
    suggested_acquisition_sources: List[str] = Field(default_factory=list)
    rationale: str = ""


class ExecutionRequest(BaseModel):
    capability_id: str
    version: Optional[str] = None  # None selects latest ACTIVE version
    inputs: Dict[str, Any] = Field(default_factory=dict)
    timeout_sec: float = 30.0


class ExecutionResponse(BaseModel):
    capability_id: str
    version: str
    status: str  # "SUCCESS" | "FAILED"
    output: Optional[Any] = None
    error: Optional[str] = None
    execution_time_ms: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

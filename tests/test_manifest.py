"""Unit tests for YAML Capability Manifest Serialization and Deserialization (§12)."""

import pytest

from capforge.core.manifest import (
    capability_to_manifest_dict,
    capability_to_yaml,
    manifest_yaml_to_capability,
)
from capforge.core.models import (
    Capability,
    CapabilityStatus,
    CapabilityType,
    RiskLevel,
    TestCase,
    TestType,
    ToolPermissions,
    ToolRequirement,
)


@pytest.fixture
def sample_capability():
    return Capability(
        id="github_security_analyzer",
        name="GitHub Security Analyzer",
        version="1.2.0",
        capability_type=CapabilityType.SKILL,
        status=CapabilityStatus.ACTIVE,
        description="Audit GitHub repositories for known security vulnerabilities.",
        domain="security",
        tags=["github", "security", "cve"],
        tools_required=[ToolRequirement(name="github.get_repo"), ToolRequirement(name="cve.lookup")],
        permissions=ToolPermissions(filesystem="read", network="restricted", github="read"),
        risk_level=RiskLevel.MEDIUM,
        code_body="def execute(repo=''):\n    return {'status': 'clean', 'vulnerabilities': []}\n",
        entrypoint_function="execute",
        verification_tests=[
            TestCase(
                id="test_clean_repo",
                name="Clean Repo Smoke Test",
                test_type=TestType.SMOKE,
                inputs={"repo": "owner/repo"},
                expected_keys=["status", "vulnerabilities"],
            )
        ],
    )


def test_capability_to_manifest_dict(sample_capability):
    m = capability_to_manifest_dict(sample_capability)
    assert m["capability_id"] == "github_security_analyzer"
    assert m["version"] == "1.2.0"
    assert m["type"] == "SKILL"
    assert m["risk"]["level"] == "MEDIUM"
    assert m["permissions"]["github"] == "read"
    assert "github.get_repo" in m["tools"]
    assert len(m["verification_tests"]) == 1


def test_manifest_roundtrip_yaml(sample_capability):
    yaml_text = capability_to_yaml(sample_capability)
    assert "capability_id: github_security_analyzer" in yaml_text
    assert "version: 1.2.0" in yaml_text

    reconstructed = manifest_yaml_to_capability(yaml_text)
    assert reconstructed.id == sample_capability.id
    assert reconstructed.version == sample_capability.version
    assert reconstructed.capability_type == sample_capability.capability_type
    assert reconstructed.risk_level == sample_capability.risk_level
    assert reconstructed.permissions.github == sample_capability.permissions.github
    assert len(reconstructed.tools_required) == 2
    assert reconstructed.tools_required[0].name == "github.get_repo"
    assert len(reconstructed.verification_tests) == 1


def test_manifest_missing_id_raises():
    invalid_yaml = """
version: 1.0.0
description: Missing ID manifest
"""
    with pytest.raises(ValueError, match="capability_id"):
        manifest_yaml_to_capability(invalid_yaml)

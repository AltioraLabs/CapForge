"""Unit tests for the Capability Registry storage engine."""

import tempfile
from pathlib import Path
import pytest

from capforge.core.models import (
    Capability,
    CapabilityStatus,
    ExecutionMode,
    ParameterSpec,
    TestCase,
    TestType,
    VerificationResult
)
from capforge.registry.store import CapabilityRegistry


@pytest.fixture
def temp_registry():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    registry = CapabilityRegistry(db_path=db_path)
    yield registry
    if db_path.exists():
        try:
            db_path.unlink()
        except Exception:
            pass


def test_register_and_retrieve_capability(temp_registry):
    cap = Capability(
        id="test_http_fetcher",
        name="Test HTTP Fetcher",
        version="1.0.0",
        status=CapabilityStatus.ACTIVE,
        description="Fetches data from test endpoints",
        domain="testing",
        code_body="def execute(inputs): return {'status': 'OK'}",
        entrypoint_function="execute"
    )

    registered = temp_registry.register(cap)
    assert registered.id == "test_http_fetcher"

    retrieved = temp_registry.get("test_http_fetcher")
    assert retrieved is not None
    assert retrieved.name == "Test HTTP Fetcher"
    assert retrieved.status == CapabilityStatus.ACTIVE


def test_versioning_and_rollback(temp_registry):
    v1 = Capability(
        id="test_versioned_service",
        name="Versioned Service",
        version="1.0.0",
        status=CapabilityStatus.ACTIVE,
        description="Version 1",
        code_body="def execute(inputs): return 1"
    )
    temp_registry.register(v1)

    v2 = Capability(
        id="test_versioned_service",
        name="Versioned Service",
        version="1.1.0",
        status=CapabilityStatus.ACTIVE,
        description="Version 2",
        code_body="def execute(inputs): return 2"
    )
    temp_registry.register(v2)

    versions = temp_registry.list_versions("test_versioned_service")
    assert len(versions) == 2

    # Rollback to v1
    rolled = temp_registry.rollback("test_versioned_service", "1.0.0")
    assert rolled.version == "1.0.0"
    assert rolled.status == CapabilityStatus.ACTIVE


def test_capability_id_validation():
    """Verify that capability IDs with path traversal or invalid characters are rejected."""
    with pytest.raises(ValueError, match="Path traversal"):
        Capability(
            id="../evil_traversal",
            name="Evil Traversal",
            description="Should fail",
            code_body="def execute(): pass",
        )

    with pytest.raises(ValueError, match="Invalid capability ID"):
        Capability(
            id="bad id with spaces; rm -rf /",
            name="Bad ID",
            description="Should fail",
            code_body="def execute(): pass",
        )


def test_semantic_fuzzy_search(temp_registry):
    """Verify that character n-gram fuzzy matching finds capabilities despite slight typos."""
    from capforge.registry.search import CapabilityMatcher
    cap = Capability(
        id="kubernetes_ingress_analyzer",
        name="Kubernetes Ingress Controller Diagnostics",
        description="Inspects ingress routes and certificates",
        domain="kubernetes",
        tags=["k8s", "ingress", "tls"],
        code_body="def execute(inputs): pass",
    )
    temp_registry.register(cap)

    matcher = CapabilityMatcher(temp_registry)
    # Search with typo: 'kubernets ingrss'
    matches = matcher.find_matches("kubernets ingrss", threshold=0.15)
    assert len(matches) > 0
    assert matches[0][0].id == "kubernetes_ingress_analyzer"

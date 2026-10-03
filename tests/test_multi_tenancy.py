"""Tests for CapForge Multi-Tenant Namespace Isolation (v0.5.0)."""

import pytest

from capforge.core.governance import CapabilityFirewall
from capforge.core.models import Capability, CapabilityStatus, ExecutionRequest
from capforge.registry.store import CapabilityRegistry


@pytest.fixture
def multi_tenant_env(tmp_path):
    db_path = tmp_path / "tenant_test.db"
    reg = CapabilityRegistry(db_path=db_path)
    fw = CapabilityFirewall()

    # Cap 1: default namespace
    c1 = Capability(
        id="general_formatter",
        name="General Text Formatter",
        description="Public formatting utility",
        namespace="default",
        status=CapabilityStatus.ACTIVE,
        code_body="def execute(inputs): return {'text': 'formatted'}",
    )
    reg.register(c1)

    # Cap 2: infra namespace
    c2 = Capability(
        id="k8s_drain_node",
        name="Kubernetes Node Drainer",
        description="Drains production node",
        namespace="infra",
        status=CapabilityStatus.ACTIVE,
        code_body="def execute(inputs): return {'drained': True}",
    )
    reg.register(c2)

    return reg, fw


def test_namespace_listing_filter(multi_tenant_env):
    reg, _ = multi_tenant_env

    all_caps = reg.list_capabilities()
    assert len(all_caps) == 2

    infra_caps = reg.list_capabilities(namespace="infra")
    assert len(infra_caps) == 1
    assert infra_caps[0].id == "k8s_drain_node"

    default_caps = reg.list_capabilities(namespace="default")
    assert len(default_caps) == 1
    assert default_caps[0].id == "general_formatter"


def test_firewall_namespace_permission_enforcement(multi_tenant_env):
    reg, fw = multi_tenant_env
    infra_cap = reg.get("k8s_drain_node")

    # Request without allowed_namespaces passes (unrestricted legacy agent)
    req_unrestricted = ExecutionRequest(capability_id="k8s_drain_node", inputs={})
    dec1 = fw.check(infra_cap, req_unrestricted)
    assert dec1.allowed is True

    # Request from finance agent restricted to ['default', 'finance']
    req_restricted_blocked = ExecutionRequest(
        capability_id="k8s_drain_node",
        inputs={},
        allowed_namespaces=["default", "finance"],
    )
    dec2 = fw.check(infra_cap, req_restricted_blocked)
    assert dec2.allowed is False
    assert "namespace 'infra' is not permitted" in dec2.blocked_reason

    # Request from DevOps agent permitted for ['infra']
    req_permitted = ExecutionRequest(
        capability_id="k8s_drain_node",
        inputs={},
        allowed_namespaces=["infra"],
    )
    dec3 = fw.check(infra_cap, req_permitted)
    assert dec3.allowed is True

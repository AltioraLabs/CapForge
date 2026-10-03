"""Tests for CapForge Model Context Protocol (MCP) Server."""

import pytest
import json
from capforge.core.models import Capability, CapabilityStatus
from capforge.registry.store import CapabilityRegistry
from capforge.mcp.server import CapForgeMCPServer


@pytest.fixture
def mcp_server(tmp_path):
    db_path = str(tmp_path / "mcp_test.db")
    reg = CapabilityRegistry(db_path=db_path)

    # Register a sample capability
    sample_cap = Capability(
        id="dns_resolver",
        name="DNS Query Resolver",
        description="Performs recursive DNS record lookups",
        domain="networking",
        tags=["dns", "network", "lookup"],
        code_body="""def execute(inputs):
    domain = inputs.get('domain', 'localhost')
    return {'domain': domain, 'ip': '127.0.0.1', 'status': 'RESOLVED'}
""",
        status=CapabilityStatus.ACTIVE,
    )
    reg.register(sample_cap)

    return CapForgeMCPServer(registry=reg)


def test_mcp_initialize(mcp_server):
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"clientInfo": {"name": "test-agent"}},
    }
    resp = mcp_server.handle_message(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert "result" in resp
    assert resp["result"]["serverInfo"]["name"] == "capforge-mcp"
    assert "tools" in resp["result"]["capabilities"]


def test_mcp_list_tools(mcp_server):
    req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    resp = mcp_server.handle_message(req)
    tools = resp["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "capforge_search_capabilities" in tool_names
    assert "capforge_execute_capability" in tool_names
    assert "capforge_synthesize_capability" in tool_names
    assert "capforge_get_manifest" in tool_names
    assert "capforge_list_capabilities" in tool_names


def test_mcp_call_search(mcp_server):
    req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "capforge_search_capabilities",
            "arguments": {"query": "dns lookup", "threshold": 0.1},
        },
    }
    resp = mcp_server.handle_message(req)
    content = resp["result"]["content"][0]["text"]
    data = json.loads(content)
    assert len(data) > 0
    assert data[0]["id"] == "dns_resolver"


def test_mcp_call_execute(mcp_server):
    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "capforge_execute_capability",
            "arguments": {"capability_id": "dns_resolver", "inputs": {"domain": "capforge.ai"}},
        },
    }
    resp = mcp_server.handle_message(req)
    content = resp["result"]["content"][0]["text"]
    data = json.loads(content)
    assert data["capability_id"] == "dns_resolver"
    assert data["status"] == "SUCCESS"
    assert data["output"]["domain"] == "capforge.ai"
    assert data["output"]["ip"] == "127.0.0.1"


def test_mcp_call_manifest(mcp_server):
    req = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "capforge_get_manifest",
            "arguments": {"capability_id": "dns_resolver"},
        },
    }
    resp = mcp_server.handle_message(req)
    content = resp["result"]["content"][0]["text"]
    data = json.loads(content)
    assert data["capability_id"] == "dns_resolver"
    assert "capability_id: dns_resolver" in data["manifest_yaml"]


def test_mcp_invalid_method(mcp_server):
    req = {"jsonrpc": "2.0", "id": 6, "method": "unknown_action", "params": {}}
    resp = mcp_server.handle_message(req)
    assert "error" in resp
    assert resp["error"]["code"] == -32601

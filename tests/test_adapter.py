"""Unit tests for CapForge Framework-Agnostic Adapter SDK (§8, Interface 4)."""

import pytest
from capforge.adapter.standard import StandardAgentAdapter
from capforge.adapter.langgraph import LangGraphAdapter
from capforge.core.models import Capability, CapabilityStatus, EventType, TestCase, TestType
from capforge.registry.store import CapabilityRegistry


@pytest.fixture
def test_registry():
    reg = CapabilityRegistry()
    cap = Capability(
        id="text_summarizer",
        name="Text Summarizer",
        version="1.0.0",
        status=CapabilityStatus.ACTIVE,
        description="Summarize text content",
        code_body="def execute(text=''):\n    return {'summary': text[:10] + '...'}\n",
        entrypoint_function="execute",
        verification_tests=[
            TestCase(id="t1", name="Smoke", test_type=TestType.SMOKE, inputs={"text": "hello world test"})
        ],
    )
    reg.register(cap)
    return reg


def test_standard_adapter_tool_discovery_and_event_capture():
    adapter = StandardAgentAdapter(agent_id="test_agent_1")

    # 1. Register local tool
    def local_tool(arg: str):
        """A sample test tool."""
        return arg.upper()

    adapter.register_local_tool("local_uppercase", local_tool)
    tools = adapter.discover_tools()
    assert len(tools) == 1
    assert tools[0].name == "local_uppercase"

    # 2. Extract failure and capture event
    err_event = adapter.extract_failure(ValueError("Connection timed out"))
    assert err_event.event_type == EventType.TOOL_FAILED
    assert err_event.error_type == "ValueError"

    events = adapter.capture_events()
    assert len(events) == 1
    # Captured events should be drained
    assert len(adapter.capture_events()) == 0


def test_standard_adapter_invoke_skill(test_registry):
    adapter = StandardAgentAdapter(agent_id="test_agent_2")
    adapter.sf.registry = test_registry
    adapter.sf.executor.registry = test_registry

    res = adapter.invoke_skill("text_summarizer", {"text": "CapForge capability invocation test"})
    assert res.status == "SUCCESS"
    assert res.output["summary"] == "CapForge c..."


def test_standard_adapter_inject_capability(test_registry):
    adapter = StandardAgentAdapter(agent_id="test_agent_3")
    adapter.sf.registry = test_registry
    adapter.sf.executor.registry = test_registry

    cap = test_registry.get("text_summarizer")
    injected_callable = adapter.inject_capability(cap)

    # Calling it like a native Python function
    output = injected_callable(text="Direct injection execution")
    assert output["summary"] == "Direct inj..."


def test_langgraph_adapter_nodes(test_registry):
    adapter = LangGraphAdapter(agent_id="langgraph_agent")
    adapter.sf.registry = test_registry
    adapter.sf.executor.registry = test_registry

    # Create node
    node = adapter.create_langgraph_node("text_summarizer")
    initial_state = {"inputs": {"text": "LangGraph state payload"}}
    next_state = node(initial_state)

    assert "text_summarizer_output" in next_state
    assert next_state["text_summarizer_output"]["summary"] == "LangGraph ..."
    assert next_state["text_summarizer_status"] == "SUCCESS"

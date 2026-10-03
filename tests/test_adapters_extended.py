"""Tests for Extended Multi-Framework Adapters & Docker Sandbox (v0.6.0)."""

import json

import pytest

from capforge.adapter.crewai_adapter import CrewAIAgentAdapter
from capforge.adapter.openai_adapter import OpenAIAgentAdapter
from capforge.core.models import Capability, CapabilityStatus, ParameterSpec
from capforge.registry.store import CapabilityRegistry
from capforge.verification.sandbox_docker import DockerSandboxRunner


@pytest.fixture
def multi_adapter_env(tmp_path):
    db_path = tmp_path / "adapters_test.db"
    reg = CapabilityRegistry(db_path=db_path)

    cap = Capability(
        id="sentiment_analyzer",
        name="Sentiment Analyzer",
        description="Analyzes customer sentiment score",
        inputs={
            "text": ParameterSpec(name="text", type="string", description="Review text", required=True),
            "neutral_threshold": ParameterSpec(name="neutral_threshold", type="number", description="Threshold", required=False, default=0.5),
        },
        status=CapabilityStatus.ACTIVE,
        code_body="""def execute(inputs):
    text = inputs.get('text', '')
    score = 0.95 if 'great' in text.lower() else 0.20
    return {'sentiment': 'POSITIVE' if score > 0.5 else 'NEGATIVE', 'score': score}
""",
    )
    reg.register(cap)
    return reg


def test_openai_adapter_tool_generation_and_execution(multi_adapter_env):
    reg = multi_adapter_env
    adapter = OpenAIAgentAdapter(registry=reg)

    tools = adapter.get_openai_tools()
    assert len(tools) == 1
    tool = tools[0]

    assert tool["type"] == "function"
    assert tool["function"]["name"] == "sentiment_analyzer"
    assert "text" in tool["function"]["parameters"]["properties"]
    assert "text" in tool["function"]["parameters"]["required"]

    # Execute simulated OpenAI tool call
    simulated_call = {
        "id": "call_abc123",
        "type": "function",
        "function": {
            "name": "sentiment_analyzer",
            "arguments": json.dumps({"text": "CapForge is a great evolution platform!"}),
        },
    }

    tool_message = adapter.handle_tool_call(simulated_call)
    assert tool_message["role"] == "tool"
    assert tool_message["tool_call_id"] == "call_abc123"

    payload = json.loads(tool_message["content"])
    assert payload["status"] == "SUCCESS"
    assert payload["output"]["sentiment"] == "POSITIVE"
    assert payload["output"]["score"] == 0.95


def test_crewai_adapter_tool_generation_and_execution(multi_adapter_env):
    reg = multi_adapter_env
    adapter = CrewAIAgentAdapter(registry=reg)

    crew_tools = adapter.get_crewai_tools()
    assert len(crew_tools) == 1
    tool = crew_tools[0]

    assert tool.name == "sentiment_analyzer"
    assert "Analyzes customer sentiment" in tool.description

    # Invoke tool via CrewAI standard run interface
    output = tool.run(text="Service degraded and bad performance")
    assert isinstance(output, dict)
    assert output["sentiment"] == "NEGATIVE"
    assert output["score"] == 0.20


def test_docker_sandbox_runner_fallback_execution():
    runner = DockerSandboxRunner(force_subprocess_fallback=True)
    assert runner.is_docker_enabled() is False

    code = "def execute(inputs): return {'calculated': inputs.get('val', 0) * 10}"
    res = runner.execute_code(code, "execute", {"val": 4})
    assert res["success"] is True
    assert res["output"]["calculated"] == 40
    assert res["execution_time_ms"] > 0

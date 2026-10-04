"""Tests for CapForge High-Level SDK Client & @capability Decorator."""

import pytest

from capforge import CapForgeClient, capability
from capforge.core.models import Capability, CapabilityStatus, RiskLevel
from capforge.sdk import SecurityError


@capability(
    id="word_counter",
    domain="nlp",
    risk_level="LOW",
    tags=["text", "utility"],
    tests=[
        {
            "id": "test_count",
            "name": "Count words",
            "inputs": {"text": "one two three"},
            "expected_keys": ["count"],
            "assert_expression": "output['count'] == 3",
        }
    ],
)
def count_words(text: str = "") -> dict:
    """Count number of words in text."""
    words = text.split()
    return {"count": len(words), "text": text}


def test_decorator_metadata():
    """Verify @capability decorator extracts correct metadata from function."""
    assert count_words.capforge_id == "word_counter"
    cap = count_words.capforge_capability
    assert isinstance(cap, Capability)
    assert cap.id == "word_counter"
    assert cap.name == "Count Words"
    assert cap.domain == "nlp"
    assert cap.risk_level == RiskLevel.LOW
    assert "text" in cap.inputs
    assert cap.inputs["text"].type == "string"
    assert cap.inputs["text"].required is False
    assert cap.inputs["text"].default == ""
    assert "count" in cap.verification_tests[0].expected_keys


def test_decorator_preserves_callable():
    """Decorated function can still be called directly like normal Python code."""
    res = count_words(text="hello world")
    assert res == {"count": 2, "text": "hello world"}


def test_decorator_to_tool():
    """Decorated function provides .to_tool() producing OpenAI tool schema."""
    tool_def = count_words.to_tool()
    assert tool_def["type"] == "function"
    assert tool_def["function"]["name"] == "word_counter"
    assert "text" in tool_def["function"]["parameters"]["properties"]


def test_capability_from_function():
    """Capability.from_function creates a Capability model from a plain function."""

    def multiply(x: int, y: int = 5) -> int:
        """Multiply x and y."""
        return x * y

    cap = Capability.from_function(multiply, id="math_multiply", domain="math")
    assert cap.id == "math_multiply"
    assert cap.domain == "math"
    assert "x" in cap.inputs
    assert cap.inputs["x"].required is True
    assert cap.inputs["y"].required is False


def test_client_local_lifecycle(tmp_path):
    """Test full CapForgeClient lifecycle in local embedded mode."""
    db_file = tmp_path / "sdk_test.db"

    with CapForgeClient(db_path=db_file, enable_security_scan=False, auto_evaluate=False) as client:
        # Register decorated capability
        reg = client.register(count_words, promote=True)
        assert reg.status == CapabilityStatus.ACTIVE

        # Execute
        exec_res = client.execute("word_counter", {"text": "alpha beta gamma delta"})
        assert exec_res.status == "SUCCESS"
        assert exec_res.output["count"] == 4

        # Get and List
        fetched = client.get("word_counter")
        assert fetched is not None
        assert fetched.id == "word_counter"

        caps = client.list_capabilities(domain="nlp")
        assert any(c.id == "word_counter" for c in caps)

        # Health check & Info
        health = client.health_check()
        assert health["subsystems"]["registry"]["status"] == "ok"

        info = client.info()
        assert info["total_capabilities"] >= 1
        assert info["mode"] == "local"

        # Tool export
        tool = client.as_tool("word_counter")
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "word_counter"


def test_client_register_plain_function(tmp_path):
    """Test registering a plain Python function with register_function()."""
    db_file = tmp_path / "plain_test.db"

    def greet_user(name: str) -> str:
        """Greet a user."""
        return f"Hello, {name}!"

    with CapForgeClient(db_path=db_file, enable_security_scan=False, auto_evaluate=False) as client:
        cap = client.register_function(greet_user, id="user_greeter", domain="social", promote=True)
        assert cap.id == "user_greeter"
        assert cap.status == CapabilityStatus.ACTIVE

        res = client.execute("user_greeter", {"name": "Alice"})
        assert res.status == "SUCCESS"


def test_client_batch_operations(tmp_path):
    """Test batch register, evaluate, and execute on CapForgeClient."""
    db_file = tmp_path / "batch_test.db"

    @capability(id="func_a", domain="test")
    def func_a(val: int) -> int:
        return val * 2

    @capability(id="func_b", domain="test")
    def func_b(val: int) -> int:
        return val + 10

    with CapForgeClient(db_path=db_file, enable_security_scan=False, auto_evaluate=False) as client:
        # Batch register
        registered = client.register_batch([func_a, func_b], promote=True)
        assert len(registered) == 2

        # Batch execute
        responses = client.execute_batch(
            [
                {"capability_id": "func_a", "inputs": {"val": 5}},
                {"capability_id": "func_b", "inputs": {"val": 5}},
            ]
        )
        assert len(responses) == 2
        assert responses[0].output == 10
        assert responses[1].output == 15


def test_client_security_scan_block(tmp_path):
    """CapForgeClient blocks registration if capability code triggers critical security violations."""
    db_file = tmp_path / "sec_test.db"

    malicious_code = """
import os
def execute(cmd: str):
    os.system(cmd)
"""
    bad_cap = Capability(
        id="malicious_exec",
        name="Malicious Exec",
        description="Dangerous execution",
        code_body=malicious_code,
    )

    with CapForgeClient(db_path=db_file, enable_security_scan=True, auto_evaluate=False) as client:
        with pytest.raises(SecurityError) as exc_info:
            client.register(bad_cap)
        assert "Security scan blocked" in str(exc_info.value)


def test_sdk_tool_bridges_and_langgraph(tmp_path):
    """CapForgeClient provides convenient to_openai_tool, handle_openai_tool_call, to_crewai_tool, and LangGraphAdapter."""
    from capforge import LangGraphAdapter

    db_file = tmp_path / "bridge_test.db"

    @capability(id="adder", domain="math")
    def adder(x: int = 1, y: int = 2) -> dict:
        return {"sum": x + y}

    with CapForgeClient(db_path=db_file, enable_security_scan=False, auto_evaluate=False) as client:
        client.register(adder, promote=True)

        # 1. to_openai_tool & handle_openai_tool_call
        openai_tool = client.to_openai_tool("adder")
        assert openai_tool["type"] == "function"
        assert openai_tool["function"]["name"] == "adder"

        mock_call = {
            "id": "call_123",
            "function": {"name": "adder", "arguments": '{"x": 10, "y": 20}'}
        }
        res_msg = client.handle_openai_tool_call(mock_call)
        assert res_msg["role"] == "tool"
        assert res_msg["tool_call_id"] == "call_123"
        assert '"sum": 30' in res_msg["content"]

        # 2. to_crewai_tool
        crew_tool = client.to_crewai_tool("adder")
        assert crew_tool.name == "adder"
        out = crew_tool.run(x=5, y=7)
        assert out == {"sum": 12}

        # 3. batch_execute alias
        batch_res = client.batch_execute([{"capability_id": "adder", "inputs": {"x": 2, "y": 3}}])
        assert len(batch_res) == 1
        assert batch_res[0].output == {"sum": 5}

        # 4. LangGraphAdapter
        lg_adapter = LangGraphAdapter(client)
        node_fn = lg_adapter.create_langgraph_node("adder")
        state_out = node_fn({"tool_inputs": {"x": 40, "y": 2}})
        assert state_out["result"] == {"sum": 42}
        assert state_out["error"] is None


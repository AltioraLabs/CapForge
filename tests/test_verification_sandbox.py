"""Unit tests for Sandbox Execution and Automated Verification Gates."""

import pytest
from capforge.core.models import (
    Capability,
    CapabilityStatus,
    TestCase,
    TestType,
)
from capforge.verification.sandbox import SandboxRunner
from capforge.verification.evaluator import CapabilityEvaluator
from capforge.verification.repair import AutoRepairEngine


def test_sandbox_execution_success_in_process():
    """Test in-process sandbox mode for fast unit testing."""
    sandbox = SandboxRunner(use_subprocess=False)
    code = """
def execute(inputs):
    return {"result": inputs["a"] + inputs["b"]}
"""
    res = sandbox.execute_code(code, "execute", {"a": 10, "b": 25})
    assert res["success"] is True
    assert res["output"] == {"result": 35}
    assert res["execution_time_ms"] >= 0


def test_sandbox_execution_success_subprocess():
    """Test subprocess-isolated sandbox mode."""
    sandbox = SandboxRunner(use_subprocess=True)
    code = """
def execute(inputs):
    return {"result": inputs.get("x", 0) * 2}
"""
    res = sandbox.execute_code(code, "execute", {"x": 21})
    assert res["success"] is True
    assert res["output"] == {"result": 42}


def test_sandbox_handles_exception():
    sandbox = SandboxRunner(use_subprocess=False)
    code = """
def execute(inputs):
    raise ValueError("intentional error")
"""
    res = sandbox.execute_code(code, "execute", {})
    assert res["success"] is False
    assert "ValueError" in res["error"]


def test_sandbox_missing_entrypoint():
    sandbox = SandboxRunner(use_subprocess=False)
    code = """
def wrong_name(inputs):
    return {}
"""
    res = sandbox.execute_code(code, "execute", {})
    assert res["success"] is False
    assert "not defined" in res["error"] or "not found" in res["error"] or "not callable" in res["error"]


def test_evaluator_catches_assertion_failure():
    evaluator = CapabilityEvaluator(sandbox=SandboxRunner(use_subprocess=False))
    code = "def execute(inputs): return {'status': 'FAILED'}"
    cap = Capability(
        id="test_cap",
        name="Test Cap",
        description="Testing assertions",
        code_body=code,
        verification_tests=[
            TestCase(
                id="test_1",
                name="Expect SUCCESS",
                test_type=TestType.HAPPY_PATH,
                inputs={},
                assert_expression="output['status'] == 'SUCCESS'",
            )
        ],
    )
    result = evaluator.evaluate(cap)
    assert result.passed is False
    assert result.tests_failed == 1


def test_evaluator_passes_on_correct_output():
    evaluator = CapabilityEvaluator(sandbox=SandboxRunner(use_subprocess=False))
    code = "def execute(inputs): return {'status': 'SUCCESS', 'records': [], 'summary': {}}"
    cap = Capability(
        id="test_cap_pass",
        name="Test Cap Pass",
        description="Testing pass",
        code_body=code,
        verification_tests=[
            TestCase(
                id="test_pass_1",
                name="Happy path",
                test_type=TestType.HAPPY_PATH,
                inputs={},
                expected_keys=["status", "records", "summary"],
                assert_expression="output['status'] == 'SUCCESS'",
            )
        ],
    )
    result = evaluator.evaluate(cap)
    assert result.passed is True
    assert result.tests_passed == 1


def test_auto_repair_recovers_failing_capability():
    evaluator = CapabilityEvaluator(sandbox=SandboxRunner(use_subprocess=False))
    repair_engine = AutoRepairEngine(evaluator)

    # Buggy code that crashes with KeyError when api_key is missing
    buggy_code = """
def execute(inputs):
    key = inputs["api_key"]
    return {"status": "SUCCESS", "records": [key]}
"""
    cap = Capability(
        id="test_repair_cap",
        name="Test Repair Cap",
        description="Testing auto-repair",
        code_body=buggy_code,
        verification_tests=[
            TestCase(
                id="test_empty",
                name="Empty inputs must not crash",
                test_type=TestType.EDGE_CASE,
                inputs={},
                assert_expression="output is not None and output.get('status') in ['SUCCESS', 'FAILED']",
            )
        ],
    )

    repaired_cap, result, iters = repair_engine.repair_until_pass(cap)
    assert result.passed is True
    assert iters >= 1


def test_sandbox_env_sanitization(monkeypatch):
    """Verify that sensitive host environment variables are stripped from sandbox subprocess."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-token-12345")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "super-secret-aws-key")
    monkeypatch.setenv("DATABASE_PASSWORD", "db-pass-999")

    sandbox = SandboxRunner(use_subprocess=True)
    code = """
import os
def execute(inputs):
    return {
        "has_openai": "OPENAI_API_KEY" in os.environ,
        "has_aws": "AWS_SECRET_ACCESS_KEY" in os.environ,
        "has_db_pass": "DATABASE_PASSWORD" in os.environ,
    }
"""
    res = sandbox.execute_code(code, "execute", {})
    assert res["success"] is True
    assert res["output"]["has_openai"] is False
    assert res["output"]["has_aws"] is False
    assert res["output"]["has_db_pass"] is False

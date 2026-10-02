"""Unit tests for Sandbox Execution and Automated Verification Gates."""

import pytest
from skillforge.core.models import (
    Capability,
    CapabilityStatus,
    TestCase,
    TestType
)
from skillforge.verification.sandbox import SandboxRunner
from skillforge.verification.evaluator import CapabilityEvaluator
from skillforge.verification.repair import AutoRepairEngine


def test_sandbox_execution_success():
    sandbox = SandboxRunner()
    code = """
def execute(inputs):
    return {"result": inputs["a"] + inputs["b"]}
"""
    res = sandbox.execute_code(code, "execute", {"a": 10, "b": 25})
    assert res["success"] is True
    assert res["output"] == {"result": 35}
    assert res["execution_time_ms"] >= 0


def test_evaluator_catches_assertion_failure():
    evaluator = CapabilityEvaluator()
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
                assert_expression="output['status'] == 'SUCCESS'"
            )
        ]
    )
    result = evaluator.evaluate(cap)
    assert result.passed is False
    assert result.tests_failed == 1


def test_auto_repair_recovers_failing_capability():
    evaluator = CapabilityEvaluator()
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
                assert_expression="output is not None and output.get('status') in ['SUCCESS', 'FAILED']"
            )
        ]
    )

    repaired_cap, result, iters = repair_engine.repair_until_pass(cap)
    assert result.passed is True
    assert iters >= 1

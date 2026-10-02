"""SkillForge Capability Evaluator.

Executes test suites in the sandbox, assesses assertions and invariants,
and generates structured VerificationResult reports.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List
from skillforge.core.models import Capability, TestCase, TestResult, VerificationResult
from skillforge.verification.sandbox import SandboxRunner


class CapabilityEvaluator:
    """Evaluates candidate capabilities against verification test batteries."""

    def __init__(self, sandbox: SandboxRunner | None = None):
        self.sandbox = sandbox or SandboxRunner()

    def evaluate(self, capability: Capability) -> VerificationResult:
        """Run all verification tests against the capability code in the sandbox."""
        test_results: List[TestResult] = []
        tests_passed = 0
        tests_failed = 0
        diagnostics_notes = []

        for test in capability.verification_tests:
            run_res = self.sandbox.execute_code(
                code_body=capability.code_body,
                entrypoint=capability.entrypoint_function,
                inputs=test.inputs,
                timeout_sec=test.max_timeout_sec
            )

            passed = False
            error_msg = run_res["error"]
            tb = run_res["traceback"]
            output = run_res["output"]

            if run_res["success"]:
                # Check assertions
                passed, assert_err = self._check_assertions(output, test)
                if not passed:
                    error_msg = assert_err or "Assertion check failed"
            
            if passed:
                tests_passed += 1
            else:
                tests_failed += 1
                diagnostics_notes.append(f"Test '{test.id}' failed: {error_msg}")

            test_results.append(TestResult(
                test_id=test.id,
                test_type=test.test_type,
                passed=passed,
                execution_time_ms=run_res["execution_time_ms"],
                output=output,
                error_message=error_msg,
                traceback=tb
            ))

        all_passed = (tests_failed == 0 and len(capability.verification_tests) > 0)
        diagnostics = "\n".join(diagnostics_notes) if diagnostics_notes else "All verification tests passed successfully."

        return VerificationResult(
            capability_id=capability.id,
            version=capability.version,
            passed=all_passed,
            tests_run=len(capability.verification_tests),
            tests_passed=tests_passed,
            tests_failed=tests_failed,
            test_details=test_results,
            diagnostics=diagnostics,
            regression_passed=True
        )

    def _check_assertions(self, output: Any, test: TestCase) -> tuple[bool, str | None]:
        """Check all assertions configured on the test case."""
        # 1. Expected keys
        if test.expected_keys and isinstance(output, dict):
            for k in test.expected_keys:
                if k not in output:
                    return False, f"Expected key '{k}' missing from output dictionary"

        # 2. Output contains strings
        if test.expected_output_contains:
            out_str = str(output)
            for s in test.expected_output_contains:
                if s not in out_str:
                    return False, f"Output did not contain required substring '{s}'"

        # 3. Dynamic Python assert expression
        if test.assert_expression:
            eval_scope = {"output": output}
            try:
                result = eval(test.assert_expression, {"__builtins__": None, "isinstance": isinstance, "len": len, "dict": dict, "list": list, "str": str, "int": int, "bool": bool}, eval_scope)
                if not bool(result):
                    return False, f"Expression '{test.assert_expression}' evaluated to False (output={output})"
            except Exception as e:
                return False, f"Error evaluating assertion expression '{test.assert_expression}': {e}"

        return True, None

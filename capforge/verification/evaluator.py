"""CapForge Capability Evaluator — Five-Level Evaluation (discussion.mdx §24).

Executes the five-level verification suite:
- Level 0: Security Gate (CodeGuardian — static analysis, evasion, secrets)
- Level 1: Structural Validation (Syntax, Schema, Entrypoint, Permissions)
- Level 2: Functional Evaluation (Correctness, Task Success, Assertions)
- Level 3: Generalization Evaluation (Edge Cases, Transfer Tasks)
- Level 4: Regression Evaluation (Historical Version Regression Battery)
- Level 5: Adversarial Testing (Determinism, Environment Blindness, Chaos — optional)
"""

from __future__ import annotations

import ast
import logging
from typing import TYPE_CHECKING, Any

from capforge.core.models import (
    Capability,
    TestCase,
    TestResult,
    TestType,
    VerificationResult,
)
from capforge.core.telemetry import (
    GenAISemanticConventions,
    trace_manager,
)
from capforge.verification.formal import formal_verifier
from capforge.verification.sandbox import SandboxRunner

# TYPE_CHECKING guard prevents circular import at module load time.
# The actual classes are imported lazily inside __init__ to break the cycle:
#   adversarial_tester -> sandbox -> verification/__init__ -> evaluator -> adversarial_tester
if TYPE_CHECKING:
    from capforge.security.code_guardian import CodeGuardian

logger = logging.getLogger("capforge.evaluator")


_SAFE_ASSERT_CALLS = frozenset({
    "len", "isinstance", "str", "int", "float", "bool", "list", "dict",
    "abs", "round", "min", "max", "sum", "any", "all",
})

_SAFE_ASSERT_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.Compare,
    ast.Call,
    ast.Attribute,
    ast.Subscript,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Dict,
)


def _assert_expr_is_safe(expression: str) -> tuple[bool, str]:
    """Statically whitelist an assert expression before eval().

    Allows comparisons, boolean logic, arithmetic, subscripts, and method
    calls on `output` (e.g. output.get('status') == 'SUCCESS'). Rejects
    dunder attribute access (blocks __class__/__subclasses__ escapes),
    arbitrary names, lambdas, comprehensions, and non-whitelisted calls.
    """
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        return False, f"not valid Python: {e}"
    # NOTE: ast.boolop is NOT a subclass of ast.operator (sibling ABCs), so all
    # four operator families are listed explicitly here.
    allowed_nodes = _SAFE_ASSERT_NODES + (ast.boolop, ast.operator, ast.unaryop, ast.cmpop)
    allowed_names = frozenset({"output", "True", "False", "None"}) | _SAFE_ASSERT_CALLS
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                return False, f"dunder attribute access '{node.attr}' is forbidden"
        elif isinstance(node, ast.Name):
            if node.id not in allowed_names:
                return False, f"unknown name '{node.id}' (only 'output' and safe builtins allowed)"
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                if func.id not in _SAFE_ASSERT_CALLS:
                    return False, f"call to '{func.id}' is not whitelisted"
            elif not isinstance(func, ast.Attribute):
                return False, "only simple or output-method calls are allowed"
        elif not isinstance(node, allowed_nodes):
            return False, f"node type '{type(node).__name__}' is not allowed"
    return True, ""


class CapabilityEvaluator:
    """Evaluates candidate capabilities against five-level verification batteries.

    Args:
        sandbox: Sandbox execution engine. Defaults to SandboxRunner().
        enable_security_gate: Run L0 CodeGuardian before L1-L4 (default: True).
        enable_adversarial: Run L5 AdversarialTester after L4 (default: False — slower).
        guardian: Custom CodeGuardian instance. Defaults to strict-mode guardian.
    """

    def __init__(
        self,
        sandbox: SandboxRunner | None = None,
        enable_security_gate: bool = True,
        enable_adversarial: bool = False,
        guardian: CodeGuardian | None = None,
    ):
        self.sandbox = sandbox or SandboxRunner()
        self.enable_security_gate = enable_security_gate
        self.enable_adversarial = enable_adversarial
        # Late imports here to avoid circular import at module load time
        if enable_security_gate or guardian is not None:
            from capforge.security.code_guardian import CodeGuardian as _CG

            self._guardian = guardian or _CG(block_on_critical=True, block_on_high=False)
        else:
            self._guardian = None
        if enable_adversarial:
            from capforge.security.adversarial_tester import AdversarialTester as _AT

            self._adversarial = _AT(sandbox=self.sandbox)
        else:
            self._adversarial = None

    def evaluate(
        self,
        capability: Capability,
        prior_versions_tests: list[TestCase] | None = None,
    ) -> VerificationResult:
        """Run complete five-level verification tests against capability in the sandbox."""
        with trace_manager.start_span("capforge.verification.evaluate") as span:
            span.set_attribute(GenAISemanticConventions.CAPABILITY_ID, capability.id)
            span.set_attribute(GenAISemanticConventions.CAPABILITY_VERSION, str(capability.version))
            span.set_attribute(GenAISemanticConventions.CAPABILITY_STATUS, capability.status.value)
            res = self._evaluate_internal(capability, prior_versions_tests)
            span.set_attribute(GenAISemanticConventions.VERIFICATION_PASSED, res.passed)
            return res

    def _evaluate_internal(
        self,
        capability: Capability,
        prior_versions_tests: list[TestCase] | None = None,
    ) -> VerificationResult:
        diagnostics_notes: list[str] = []
        level_0_report: dict[str, Any] = {"skipped": True}

        # -------------------------------------------------------------------
        # Level 0: Security Gate (CodeGuardian)
        # -------------------------------------------------------------------
        if self.enable_security_gate:
            scan = self._guardian.scan(capability.id, capability.code_body)
            level_0_report = scan.to_dict()
            if scan.blocked:
                logger.warning(
                    "L0 Security Gate BLOCKED capability '%s': %s",
                    capability.id,
                    scan.summary,
                )
                return VerificationResult(
                    capability_id=capability.id,
                    version=capability.version,
                    passed=False,
                    tests_run=0,
                    tests_passed=0,
                    tests_failed=0,
                    structural_valid=False,
                    functional_score=0.0,
                    generalization_score=0.0,
                    regression_passed=False,
                    diagnostics=f"L0 Security Gate blocked: {scan.summary}",
                    four_level_report={
                        "level_0_security": level_0_report,
                        "level_1_structural": {"skipped": True},
                        "level_2_functional": {"score": 0.0, "passed": 0, "total": 0},
                        "level_3_generalization": {"score": 0.0, "passed": 0, "total": 0},
                        "level_4_regression": {"passed": False},
                    },
                )

        # -------------------------------------------------------------------
        # Level 1: Structural Validation
        # -------------------------------------------------------------------
        structural_valid, struct_err = self._validate_structure(capability)
        if not structural_valid:
            diagnostics_notes.append(f"Level 1 (Structural) failed: {struct_err}")
            return VerificationResult(
                capability_id=capability.id,
                version=capability.version,
                passed=False,
                tests_run=0,
                tests_passed=0,
                tests_failed=0,
                structural_valid=False,
                functional_score=0.0,
                generalization_score=0.0,
                regression_passed=False,
                diagnostics=f"Structural validation failure: {struct_err}",
                four_level_report={
                    "level_1_structural": {"valid": False, "error": struct_err},
                    "level_2_functional": {"score": 0.0, "passed": 0, "total": 0},
                    "level_3_generalization": {"score": 0.0, "passed": 0, "total": 0},
                    "level_4_regression": {"passed": False},
                },
            )

        # -------------------------------------------------------------------
        # Level 2 & Level 3: Functional & Generalization Evaluation
        # -------------------------------------------------------------------
        test_results: list[TestResult] = []
        tests_passed = 0
        tests_failed = 0

        functional_tests = [
            t for t in capability.verification_tests if t.test_type in (TestType.SMOKE, TestType.INVARIANT)
        ]
        generalization_tests = [
            t for t in capability.verification_tests if t.test_type in (TestType.EDGE_CASE, TestType.PROPERTY)
        ]

        # If no specific split, treat all as functional
        if not functional_tests and not generalization_tests:
            functional_tests = list(capability.verification_tests)

        func_passed = 0
        gen_passed = 0

        for test in capability.verification_tests:
            run_res = self.sandbox.execute_code(
                code_body=capability.code_body,
                entrypoint=capability.entrypoint_function,
                inputs=test.inputs,
                timeout_sec=test.max_timeout_sec,
            )

            passed = False
            error_msg = run_res.get("error")
            tb = run_res.get("traceback")
            output = run_res.get("output")

            if run_res["success"]:
                passed, assert_err = self._check_assertions(output, test)
                if not passed:
                    error_msg = assert_err or "Assertion check failed"

            if passed:
                tests_passed += 1
                if test in functional_tests:
                    func_passed += 1
                if test in generalization_tests:
                    gen_passed += 1
            else:
                tests_failed += 1
                diagnostics_notes.append(f"Test '{test.id}' ({test.test_type.value}) failed: {error_msg}")

            test_results.append(
                TestResult(
                    test_id=test.id,
                    test_type=test.test_type,
                    passed=passed,
                    execution_time_ms=run_res.get("execution_time_ms", 0.0),
                    output=output,
                    error_message=error_msg,
                    traceback=tb,
                )
            )

        func_total = len(functional_tests)
        gen_total = len(generalization_tests)

        func_score = (func_passed / func_total) if func_total > 0 else 1.0
        gen_score = (gen_passed / gen_total) if gen_total > 0 else 1.0

        # -------------------------------------------------------------------
        # Level 4: Regression Evaluation (if prior test suite provided)
        # -------------------------------------------------------------------
        regression_passed = True
        regression_failed_tests = []

        if prior_versions_tests:
            for reg_test in prior_versions_tests:
                reg_res = self.sandbox.execute_code(
                    code_body=capability.code_body,
                    entrypoint=capability.entrypoint_function,
                    inputs=reg_test.inputs,
                    timeout_sec=reg_test.max_timeout_sec,
                )
                r_passed = False
                if reg_res.get("success"):
                    r_passed, _ = self._check_assertions(reg_res.get("output"), reg_test)
                if not r_passed:
                    regression_passed = False
                    regression_failed_tests.append(reg_test.id)

            if not regression_passed:
                diagnostics_notes.append(f"Level 4 (Regression) failed on historical tests: {regression_failed_tests}")

        all_passed = tests_failed == 0 and len(capability.verification_tests) > 0 and regression_passed
        diagnostics = (
            "\n".join(diagnostics_notes)
            if diagnostics_notes
            else "All five-level verification tests passed successfully."
        )

        return VerificationResult(
            capability_id=capability.id,
            version=capability.version,
            passed=all_passed,
            tests_run=len(capability.verification_tests),
            tests_passed=tests_passed,
            tests_failed=tests_failed,
            test_details=test_results,
            structural_valid=True,
            functional_score=round(func_score, 4),
            generalization_score=round(gen_score, 4),
            regression_passed=regression_passed,
            diagnostics=diagnostics,
            four_level_report={
                "level_0_security": level_0_report,
                "level_1_structural": {"valid": True},
                "level_1_formal_proof": formal_verifier.verify_invariants(capability).__dict__,
                "level_2_functional": {"score": round(func_score, 4), "passed": func_passed, "total": func_total},
                "level_3_generalization": {"score": round(gen_score, 4), "passed": gen_passed, "total": gen_total},
                "level_4_regression": {"passed": regression_passed, "failed_tests": regression_failed_tests},
            },
        )

    def _validate_structure(self, capability: Capability) -> tuple[bool, str | None]:
        """Level 1 Structural Validation: check AST syntax, entrypoint, and schema."""
        if not capability.code_body or not capability.code_body.strip():
            return False, "Empty code body"

        try:
            tree = ast.parse(capability.code_body)
        except SyntaxError as e:
            return False, f"Python syntax error in code_body: {e}"

        # Verify entrypoint function definition exists
        found_entrypoint = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == capability.entrypoint_function
            for node in ast.walk(tree)
        )
        if not found_entrypoint:
            # Fallback: if 'run', 'main', or any function exists, adapt entrypoint
            alt_fn = next(
                (
                    node.name
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name in ("execute", "run", "main")
                ),
                None,
            )
            if alt_fn:
                capability.entrypoint_function = alt_fn
                found_entrypoint = True
            else:
                return False, f"Entrypoint function '{capability.entrypoint_function}' not found in code body"

        if not capability.id:
            return False, "Capability ID is required"

        return True, None

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

        # 3. Dynamic Python assert expression (AST-whitelisted before eval:
        # no dunder attribute access, so subclass-traversal escapes such as
        # output.__class__.__base__.__subclasses__() are rejected statically).
        if test.assert_expression:
            safe, reason = _assert_expr_is_safe(test.assert_expression)
            if not safe:
                return False, f"Rejected unsafe assert expression: {reason}"
            eval_scope = {"output": output}
            try:
                result = eval(
                    test.assert_expression,
                    {
                        "__builtins__": None,
                        "isinstance": isinstance,
                        "len": len,
                        "dict": dict,
                        "list": list,
                        "str": str,
                        "int": int,
                        "bool": bool,
                    },
                    eval_scope,
                )
                if not bool(result):
                    return False, f"Expression '{test.assert_expression}' evaluated to False (output={output})"
            except Exception as e:
                return False, f"Error evaluating assertion expression '{test.assert_expression}': {e}"

        return True, None

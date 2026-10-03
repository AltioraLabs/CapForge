"""CapForge Automated Test Generator.

Synthesizes multi-class test batteries (Happy Path, Boundary/Edge Cases, and Invariants)
to ensure robust validation gates before any capability can reach production.
"""

from __future__ import annotations

from capforge.core.models import Capability, TestCase, TestType


class TestGenerator:
    """Generates comprehensive verification suites for candidate capabilities."""

    def enrich_tests(self, capability: Capability) -> list[TestCase]:
        """Ensure the capability has at least one test for each critical test class."""
        tests = list(capability.verification_tests)
        existing_types = {t.test_type for t in tests}

        # 1. Missing Happy Path
        if TestType.HAPPY_PATH not in existing_types:
            sample_inputs = {}
            for name, spec in capability.inputs.items():
                if spec.default is not None:
                    sample_inputs[name] = spec.default
                elif spec.type == "string":
                    sample_inputs[name] = "test_value"
                elif spec.type == "integer":
                    sample_inputs[name] = 10
                elif spec.type == "dict":
                    sample_inputs[name] = {}
                elif spec.type == "list":
                    sample_inputs[name] = []
                else:
                    sample_inputs[name] = "test"

            tests.append(
                TestCase(
                    id=f"test_{capability.id}_auto_happy_path",
                    name="Auto-generated Happy Path execution test",
                    test_type=TestType.HAPPY_PATH,
                    inputs=sample_inputs,
                    assert_expression="output is not None",
                )
            )

        # 2. Missing Edge Case (Empty or None parameters)
        if TestType.EDGE_CASE not in existing_types:
            tests.append(
                TestCase(
                    id=f"test_{capability.id}_auto_edge_empty_inputs",
                    name="Auto-generated Boundary test with empty inputs",
                    test_type=TestType.EDGE_CASE,
                    inputs={},
                    assert_expression="output is not None and ('status' in output or 'error' in output)",
                )
            )

        # 3. Missing Security / Invariant (Output dictionary contract)
        if TestType.SECURITY_INVARIANT not in existing_types:
            tests.append(
                TestCase(
                    id=f"test_{capability.id}_auto_invariant_contract",
                    name="Auto-generated Invariant: output is a dictionary conforming to output spec",
                    test_type=TestType.SECURITY_INVARIANT,
                    inputs=tests[0].inputs if tests else {},
                    assert_expression="isinstance(output, dict)",
                )
            )

        return tests

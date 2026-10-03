"""CapForge Regression Testing Battery.

Guarantees backward compatibility and eliminates capability drift:
validates that new capability versions do NOT regress on historical test suites.
"""

from __future__ import annotations

from capforge.core.exceptions import RegressionDetectedError
from capforge.core.models import Capability, TestCase
from capforge.registry.store import CapabilityRegistry
from capforge.verification.evaluator import CapabilityEvaluator


class RegressionSuiteRunner:
    """Executes historical regression test batteries against updated candidate capabilities."""

    def __init__(self, registry: CapabilityRegistry, evaluator: CapabilityEvaluator | None = None):
        self.registry = registry
        self.evaluator = evaluator or CapabilityEvaluator()

    def run_regression_battery(self, candidate_capability: Capability) -> tuple[bool, list[str]]:
        """Run all test cases from prior versions of this capability against the candidate.

        Returns (all_passed, list_of_failed_test_ids).
        """
        all_versions = self.registry.list_versions(candidate_capability.id)
        if not all_versions:
            # First version ever, no regressions possible
            return True, []

        historical_tests: list[TestCase] = []
        seen_test_ids = {t.id for t in candidate_capability.verification_tests}

        for past_cap in all_versions:
            if past_cap.version == candidate_capability.version:
                continue
            for test in past_cap.verification_tests:
                if test.id not in seen_test_ids:
                    historical_tests.append(test)
                    seen_test_ids.add(test.id)

        if not historical_tests:
            return True, []

        # Construct temporary capability combining candidate code with historical test suite
        test_probe = candidate_capability.model_copy()
        test_probe.verification_tests = historical_tests

        res = self.evaluator.evaluate(test_probe)
        failed_tests = [t.test_id for t in res.test_details if not t.passed]

        return res.passed, failed_tests

    def assert_no_regression(self, candidate_capability: Capability) -> None:
        """Assert that the candidate capability does not regress on historical tests."""
        passed, failed_tests = self.run_regression_battery(candidate_capability)
        if not passed:
            first_fail = failed_tests[0] if failed_tests else "unknown"
            raise RegressionDetectedError(
                capability_id=candidate_capability.id, broken_version=candidate_capability.version, test_id=first_fail
            )

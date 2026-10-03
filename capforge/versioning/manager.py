"""CapForge Version Manager.

Manages semantic version increments, automated promotion gates,
historical lineage tracking, risk-based governance, and rollback operations.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from capforge.core.models import Capability, CapabilityStatus, RiskLevel, VerificationResult
from capforge.core.exceptions import VerificationFailedError, RegressionDetectedError
from capforge.core.governance import RiskEngine, RiskAssessment
from capforge.registry.store import CapabilityRegistry
from capforge.versioning.regression import RegressionSuiteRunner
from capforge.verification.evaluator import CapabilityEvaluator

logger = logging.getLogger("capforge.versioning")


class VersionManager:
    """Orchestrates capability promotion, versioning, and rollback governance."""

    def __init__(self, registry: CapabilityRegistry, risk_engine: Optional[RiskEngine] = None):
        self.registry = registry
        self.evaluator = CapabilityEvaluator()
        self.regression_runner = RegressionSuiteRunner(registry, self.evaluator)
        self.risk_engine = risk_engine or RiskEngine()

    def bump_semver(self, current_version: str, bump_type: str = "patch") -> str:
        """Increment a semver string (e.g. 1.0.0 -> 1.0.1 or 1.1.0 or 2.0.0)."""
        parts = current_version.split(".")
        major = int(parts[0]) if len(parts) > 0 else 1
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0

        if bump_type == "major":
            return f"{major + 1}.0.0"
        elif bump_type == "minor":
            return f"{major}.{minor + 1}.0"
        else:
            return f"{major}.{minor}.{patch + 1}"

    def assess_risk(self, candidate: Capability) -> RiskAssessment:
        """Assess the risk level of a candidate capability."""
        assessment = self.risk_engine.assess(candidate)
        candidate.risk_level = assessment.risk_level
        return assessment

    def promote_to_active(
        self,
        candidate: Capability,
        skip_regression: bool = False,
        skip_risk_check: bool = False,
    ) -> Tuple[VerificationResult, Optional[RiskAssessment]]:
        """Validate candidate against verification tests and regression battery before promoting to ACTIVE.

        Returns (verification_result, risk_assessment).
        Raises VerificationFailedError or RegressionDetectedError if gates fail.
        """
        # 0. Risk Assessment (unless skipped)
        risk_assessment = None
        if not skip_risk_check:
            risk_assessment = self.assess_risk(candidate)
            logger.info(
                "Risk assessment: %s (score=%.3f, auto_promote=%s)",
                risk_assessment.risk_level.value,
                risk_assessment.risk_score,
                risk_assessment.auto_promote_allowed,
            )

        # 1. Verification Gate
        verif = self.evaluator.evaluate(candidate)
        self.registry.record_verification(verif)

        if not verif.passed:
            raise VerificationFailedError(
                capability_id=candidate.id,
                failed_tests=verif.tests_failed,
                total_tests=verif.tests_run,
                details=verif.diagnostics or ""
            )

        # 2. Regression Gate
        if not skip_regression:
            regression_passed, failed_test_ids = self.regression_runner.run_regression_battery(candidate)
            verif.regression_passed = regression_passed
            if not regression_passed:
                first_fail = failed_test_ids[0] if failed_test_ids else "unknown"
                raise RegressionDetectedError(
                    capability_id=candidate.id,
                    broken_version=candidate.version,
                    test_id=first_fail
                )

        # 3. Demote any previously ACTIVE version to DEPRECATED
        active_caps = self.registry.list_versions(candidate.id)
        for prev in active_caps:
            if prev.version != candidate.version and prev.status == CapabilityStatus.ACTIVE:
                self.registry.set_status(candidate.id, prev.version, CapabilityStatus.DEPRECATED)

        # 4. Promote candidate to ACTIVE and persist
        candidate.status = CapabilityStatus.ACTIVE
        self.registry.register(candidate)

        logger.info(
            "Promoted %s v%s to ACTIVE (risk=%s)",
            candidate.id,
            candidate.version,
            candidate.risk_level.value,
        )

        return verif, risk_assessment

    def rollback(self, capability_id: str, target_version: str) -> Capability:
        """Rollback capability to an earlier verified version."""
        rolled = self.registry.rollback(capability_id, target_version)
        logger.info("Rolled back %s to v%s", capability_id, target_version)
        return rolled

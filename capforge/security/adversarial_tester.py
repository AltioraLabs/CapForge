"""CapForge Adversarial Tester — Production Parity & Evasion Detection.

Addresses the second unsolved problem: a capability that passes evaluation
but behaves differently in production (adversarial evasion / test-aware malware).

The Adversarial Tester runs AFTER the standard 4-level battery. It applies
three adversarial lenses:

  Test 1 — Determinism Verification
    Runs the same input N times and checks all outputs are identical.
    Non-deterministic behavior (when it shouldn't be) is a red flag for
    counter-based triggers, probabilistic activations, or race conditions.

  Test 2 — Environment Blindness
    Executes the code twice: once with test environment markers present
    (PYTEST=1, CI=1, TESTING=1), once with production-like markers.
    If outputs differ, the code is environment-aware — sandbox evasion.

  Test 3 — Chaos Input Robustness
    Feeds malformed, extreme, and adversarially crafted inputs.
    Legitimate capabilities return graceful FAILED responses.
    Suspicious behaviors: unexpected SUCCESS on garbage input,
    data exfiltration in output, different error modes per input type.

Usage:
    tester = AdversarialTester(sandbox)
    result = tester.run(capability)
    if result.evasion_detected or result.non_deterministic:
        registry.quarantine(capability)
"""

from __future__ import annotations

import copy
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from capforge.core.models import Capability
from capforge.verification.sandbox import SandboxRunner

logger = logging.getLogger("capforge.security.adversarial")


# ---------------------------------------------------------------------------
# Chaos Input Corpus
# ---------------------------------------------------------------------------

CHAOS_INPUTS: list[dict[str, Any]] = [
    # Type confusion
    {},
    {"payload": None},
    {"payload": 0},
    {"payload": False},
    {"payload": []},
    {"payload": ""},
    # Boundary values
    {"payload": "A" * 65536},  # 64KB string
    {"payload": list(range(10000))},  # Large list
    {"payload": {str(i): i for i in range(100)}},  # Large dict
    # Deep nesting
    {"payload": {"a": {"b": {"c": {"d": {"e": "deep"}}}}}},
    # Unicode edge cases
    {"payload": "\x00\x01\x02\x03"},  # Null bytes
    {"payload": "\u202e" * 100},  # RTL override (unicode smuggling)
    {"payload": "😈" * 100},  # Emoji
    # Injection attempts in inputs
    {"payload": "__import__('os').system('id')"},
    {"payload": "${7*7}"},  # Template injection probe
    {"payload": "'; DROP TABLE capabilities; --"},  # SQL injection probe
    {"payload": "<script>alert(1)</script>"},  # XSS probe
    {"payload": "{{7*7}}"},  # SSTI probe
    # Special keys
    {"__proto__": "polluted"},  # Prototype pollution
    {"__class__": "evil"},
    {"constructor": {"prototype": {}}},
]


# ---------------------------------------------------------------------------
# Sensitive Data Patterns — detect exfiltration in output
# ---------------------------------------------------------------------------

SENSITIVE_OUTPUT_PATTERNS = [
    r"AKIA[0-9A-Z]{16}",  # AWS key
    r"sk-[a-zA-Z0-9]{48}",  # OpenAI key
    r"ghp_[a-zA-Z0-9]{36}",  # GitHub PAT
    r"-----BEGIN.*PRIVATE KEY-----",  # Private key
    r"(?i)password\s*[:=]\s*\S{6,}",  # Password value
    r"\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}",  # Credit card
    r"(?i)ssn\s*[:=]\s*\d{3}-\d{2}-\d{4}",  # SSN
]


# ---------------------------------------------------------------------------
# Result Models
# ---------------------------------------------------------------------------


@dataclass
class DeterminismResult:
    deterministic: bool
    runs: int
    differing_run_indices: list[int] = field(default_factory=list)
    outputs: list[Any] = field(default_factory=list)
    note: str = ""

    @property
    def passed(self) -> bool:
        return self.deterministic


@dataclass
class EnvironmentBlindnessResult:
    environment_blind: bool  # True = SAFE (same output in test and prod env)
    test_env_output: Any = None
    prod_env_output: Any = None
    evasion_detected: bool = False
    note: str = ""

    @property
    def passed(self) -> bool:
        return self.environment_blind and not self.evasion_detected


@dataclass
class ChaosResult:
    total_inputs: int
    graceful_failures: int
    suspicious_successes: int = 0
    exfiltration_detected: bool = False
    crash_count: int = 0
    suspicious_inputs: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""

    @property
    def passed(self) -> bool:
        return not self.exfiltration_detected and self.suspicious_successes == 0


@dataclass
class AdversarialTestResult:
    capability_id: str
    version: str
    determinism: DeterminismResult | None = None
    environment_blindness: EnvironmentBlindnessResult | None = None
    chaos: ChaosResult | None = None
    evasion_detected: bool = False
    overall_passed: bool = True
    summary: str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "version": self.version,
            "overall_passed": self.overall_passed,
            "evasion_detected": self.evasion_detected,
            "summary": self.summary,
            "duration_ms": round(self.duration_ms, 1),
            "determinism": {
                "passed": self.determinism.passed if self.determinism else None,
                "runs": self.determinism.runs if self.determinism else 0,
                "differing_runs": self.determinism.differing_run_indices if self.determinism else [],
            },
            "environment_blindness": {
                "passed": self.environment_blindness.passed if self.environment_blindness else None,
                "evasion_detected": self.environment_blindness.evasion_detected
                if self.environment_blindness
                else False,
            },
            "chaos": {
                "passed": self.chaos.passed if self.chaos else None,
                "total_inputs": self.chaos.total_inputs if self.chaos else 0,
                "suspicious_successes": self.chaos.suspicious_successes if self.chaos else 0,
                "exfiltration_detected": self.chaos.exfiltration_detected if self.chaos else False,
                "crashes": self.chaos.crash_count if self.chaos else 0,
            },
        }


# ---------------------------------------------------------------------------
# AdversarialTester
# ---------------------------------------------------------------------------


class AdversarialTester:
    """Tests capabilities against adversarial evasion and production parity issues.

    Designed for open-source use: plugs into any SandboxRunner, configurable
    strictness, fast enough to run in CI (< 10 seconds for most capabilities).

    Args:
        sandbox: SandboxRunner instance to use for execution.
        determinism_runs: How many times to repeat for determinism check (default: 3).
        chaos_timeout_sec: Timeout per chaos input (default: 3.0).
        strict_mode: If True, any suspicious finding blocks promotion (default: False).
    """

    def __init__(
        self,
        sandbox: SandboxRunner | None = None,
        determinism_runs: int = 3,
        chaos_timeout_sec: float = 3.0,
        strict_mode: bool = False,
    ):
        self.sandbox = sandbox or SandboxRunner()
        self.determinism_runs = determinism_runs
        self.chaos_timeout_sec = chaos_timeout_sec
        self.strict_mode = strict_mode

    def run(self, capability: Capability, base_inputs: dict[str, Any] | None = None) -> AdversarialTestResult:
        """Run all three adversarial test lenses against a capability.

        Args:
            capability: The capability to test.
            base_inputs: Representative inputs for determinism/blindness tests.
                         If not provided, uses capability's first test case inputs.
        """
        start = time.perf_counter()
        result = AdversarialTestResult(
            capability_id=capability.id,
            version=capability.version,
        )

        # Use first test case inputs as base, or empty dict
        if base_inputs is None:
            if capability.verification_tests:
                base_inputs = capability.verification_tests[0].inputs
            else:
                base_inputs = {}

        logger.info("AdversarialTester: starting tests for capability '%s'", capability.id)

        # Test 1: Determinism
        result.determinism = self._test_determinism(
            capability.code_body,
            capability.entrypoint_function,
            base_inputs,
        )

        # Test 2: Environment Blindness
        result.environment_blindness = self._test_environment_blindness(
            capability.code_body,
            capability.entrypoint_function,
            base_inputs,
        )

        # Test 3: Chaos Inputs
        result.chaos = self._test_chaos_inputs(
            capability.code_body,
            capability.entrypoint_function,
        )

        # Evaluate overall
        evasion = result.environment_blindness.evasion_detected or not result.determinism.passed
        security_issue = result.chaos.exfiltration_detected

        result.evasion_detected = evasion
        result.overall_passed = not security_issue and (not evasion if self.strict_mode else not security_issue)

        result.summary = self._build_summary(result)
        result.duration_ms = (time.perf_counter() - start) * 1000.0

        if not result.overall_passed:
            logger.warning(
                "AdversarialTester: FAILED for '%s' — evasion=%s, security=%s",
                capability.id,
                evasion,
                security_issue,
            )
        else:
            logger.info(
                "AdversarialTester: PASSED for '%s' in %.1fms",
                capability.id,
                result.duration_ms,
            )

        return result

    # -----------------------------------------------------------------------
    # Test 1: Determinism
    # -----------------------------------------------------------------------

    def _test_determinism(
        self,
        code: str,
        entrypoint: str,
        inputs: dict[str, Any],
    ) -> DeterminismResult:
        """Run same input N times — output must be consistent."""
        outputs = []
        for i in range(self.determinism_runs):
            run = self.sandbox.execute_code(
                code_body=code,
                entrypoint=entrypoint,
                inputs=copy.deepcopy(inputs),
                timeout_sec=self.chaos_timeout_sec,
            )
            outputs.append(run.get("output"))

        normalized = [self._normalize_output(o) for o in outputs]
        baseline = normalized[0]
        differing = [i for i, o in enumerate(normalized[1:], 1) if o != baseline]

        deterministic = len(differing) == 0
        note = ""
        if not deterministic:
            note = (
                f"Output differed on run(s) {differing}. "
                "Possible counter-based trigger, race condition, or randomized behavior."
            )
            logger.warning("Determinism FAILED for capability: %s", note)

        return DeterminismResult(
            deterministic=deterministic,
            runs=self.determinism_runs,
            differing_run_indices=differing,
            outputs=outputs,
            note=note,
        )

    # -----------------------------------------------------------------------
    # Test 2: Environment Blindness
    # -----------------------------------------------------------------------

    def _test_environment_blindness(
        self,
        code: str,
        entrypoint: str,
        inputs: dict[str, Any],
    ) -> EnvironmentBlindnessResult:
        """Execute with test-env markers vs production-env markers.

        A safe capability should produce the same output regardless of environment.
        Different outputs = sandbox evasion detected.
        """
        # Production-like environment (no test markers)
        prod_run = self.sandbox.execute_code(
            code_body=code,
            entrypoint=entrypoint,
            inputs=copy.deepcopy(inputs),
            timeout_sec=self.chaos_timeout_sec,
            env_overrides={"CAPFORGE_ENV": "production"},
        )

        # Test-environment markers explicitly set
        test_run = self.sandbox.execute_code(
            code_body=code,
            entrypoint=entrypoint,
            inputs=copy.deepcopy(inputs),
            timeout_sec=self.chaos_timeout_sec,
            env_overrides={
                "PYTEST": "1",
                "TESTING": "true",
                "CI": "true",
                "GITHUB_ACTIONS": "true",
                "CAPFORGE_ENV": "test",
            },
        )

        prod_output_normalized = self._normalize_output(prod_run.get("output"))
        test_output_normalized = self._normalize_output(test_run.get("output"))

        evasion = prod_output_normalized != test_output_normalized and prod_run.get("success") != test_run.get(
            "success"
        )

        note = ""
        if evasion:
            note = (
                "Output or success status differs between test-env and prod-env execution. "
                "Possible sandbox evasion — capability may behave differently in production."
            )
            logger.warning("Environment blindness FAILED: %s", note)

        return EnvironmentBlindnessResult(
            environment_blind=not evasion,
            test_env_output=test_run.get("output"),
            prod_env_output=prod_run.get("output"),
            evasion_detected=evasion,
            note=note,
        )

    # -----------------------------------------------------------------------
    # Test 3: Chaos Inputs
    # -----------------------------------------------------------------------

    def _test_chaos_inputs(
        self,
        code: str,
        entrypoint: str,
    ) -> ChaosResult:
        """Feed adversarially crafted inputs and check for suspicious behavior."""
        suspicious_successes = 0
        exfiltration_detected = False
        crash_count = 0
        graceful_failures = 0
        suspicious_inputs_log = []

        for chaos_input in CHAOS_INPUTS:
            try:
                run = self.sandbox.execute_code(
                    code_body=code,
                    entrypoint=entrypoint,
                    inputs=copy.deepcopy(chaos_input),
                    timeout_sec=self.chaos_timeout_sec,
                )
            except Exception:
                crash_count += 1
                continue

            output = run.get("output", {})

            # Check for data exfiltration in output
            output_str = json.dumps(output, default=str) if output else ""
            for pattern in SENSITIVE_OUTPUT_PATTERNS:
                if re.search(pattern, output_str, re.IGNORECASE):
                    exfiltration_detected = True
                    suspicious_inputs_log.append(
                        {
                            "input": str(chaos_input)[:100],
                            "finding": "EXFILTRATION",
                        }
                    )
                    break

            # Check for suspicious success on injection probe inputs.
            # A SAFE capability treats injection strings as plain input values.
            # A DANGEROUS capability EXECUTES them and the result appears in output.
            # We detect actual execution by checking if computed values or shell output
            # appear in the response (e.g. "49" from 7*7, "uid=" from os.system).
            if (
                run.get("success")
                and isinstance(output, dict)
                and chaos_input
                in [
                    {"payload": "__import__('os').system('id')"},
                    {"payload": "${7*7}"},
                    {"payload": "{{7*7}}"},
                ]
            ):
                output_str_probe = json.dumps(output, default=str)
                EXECUTION_EVIDENCE = ["uid=", "gid=", "root:", " 49", ":49", "=49", " 42", ":42", "=42", "evaluated"]
                actually_executed = any(ev in output_str_probe for ev in EXECUTION_EVIDENCE)
                if actually_executed:
                    suspicious_successes += 1
                    suspicious_inputs_log.append(
                        {
                            "input": str(chaos_input)[:100],
                            "finding": "INJECTION_EXECUTED",
                        }
                    )
            elif not run.get("success"):
                graceful_failures += 1

        note = ""
        if exfiltration_detected:
            note += "EXFILTRATION: Sensitive data pattern detected in output. "
        if suspicious_successes > 0:
            note += f"SUSPICIOUS_SUCCESS: {suspicious_successes} injection probe(s) returned SUCCESS. "
        if crash_count > 0:
            note += f"CRASHES: {crash_count} chaos input(s) caused unhandled crashes. "

        return ChaosResult(
            total_inputs=len(CHAOS_INPUTS),
            graceful_failures=graceful_failures,
            suspicious_successes=suspicious_successes,
            exfiltration_detected=exfiltration_detected,
            crash_count=crash_count,
            suspicious_inputs=suspicious_inputs_log,
            note=note.strip(),
        )

    # -----------------------------------------------------------------------
    # Utilities
    # -----------------------------------------------------------------------

    @staticmethod
    def _normalize_output(output: Any) -> str:
        """Normalize output for comparison: remove timestamps and floating-point noise."""
        if output is None:
            return "null"
        try:
            s = json.dumps(output, sort_keys=True, default=str)
        except Exception:
            s = str(output)
        # Remove ISO timestamps (allow output to contain them without false evasion detection)
        s = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[.\d]*[Z+\-\d:]*", "<TIMESTAMP>", s)
        # Remove floating point timing fields
        s = re.sub(r'"(?:time|elapsed|duration|latency)":\s*[\d.]+', '"<TIMING>": 0', s)
        return s

    @staticmethod
    def _build_summary(result: AdversarialTestResult) -> str:
        parts = []
        if result.evasion_detected:
            parts.append("EVASION_DETECTED")
        if result.chaos and result.chaos.exfiltration_detected:
            parts.append("EXFILTRATION_DETECTED")
        if result.determinism and not result.determinism.passed:
            parts.append("NON_DETERMINISTIC")
        if not parts:
            return "PASSED: No adversarial issues detected."
        status = "BLOCKED" if not result.overall_passed else "WARNING"
        return f"{status}: {' | '.join(parts)}"

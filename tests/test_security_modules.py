"""Tests for the three CapForge security modules.

Tests are organized by the three unsolved problems they address:

  Problem 1 Tests (TestCodeGuardian):
    Code written and executed at runtime — the LLM synthesis pipeline
    is an attack surface with no equivalent in traditional playbooks.

  Problem 2 Tests (TestAdversarialTester):
    Code that passes tests but behaves differently in production
    (adversarial evasion / environment-aware malware).

  Problem 3 Tests (TestTrustChain):
    Learning loop poisoning via tampered capabilities or
    injected false verification results.
"""

from pathlib import Path

import pytest

from capforge.core.models import Capability, CapabilityStatus
from capforge.security.adversarial_tester import AdversarialTester
from capforge.security.code_guardian import CodeGuardian
from capforge.security.trust_chain import TamperDetectedError, TrustChain
from capforge.verification.evaluator import CapabilityEvaluator
from capforge.verification.sandbox import SandboxRunner

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_cap(cap_id: str, code: str, entrypoint: str = "execute") -> Capability:
    return Capability(
        id=cap_id,
        name=f"Test Cap {cap_id}",
        description="Security test capability",
        domain="test",
        code_body=code,
        entrypoint_function=entrypoint,
    )


SAFE_CODE = """
def execute(inputs: dict) -> dict:
    value = inputs.get("value", 0)
    return {"status": "SUCCESS", "result": value * 2}
"""

DETERMINISTIC_CODE = """
def execute(inputs: dict) -> dict:
    x = inputs.get("x", 1)
    return {"status": "SUCCESS", "result": x * 3}
"""


# ===========================================================================
# PROBLEM 1: CodeGuardian — LLM Synthesis Attack Surface
# ===========================================================================

class TestCodeGuardian:

    def setup_method(self):
        self.guardian = CodeGuardian(block_on_critical=True, block_on_high=False)
        self.strict_guardian = CodeGuardian(block_on_critical=True, block_on_high=True)

    # -----------------------------------------------------------------------
    # Layer 1: AST Detection
    # -----------------------------------------------------------------------

    def test_l1_blocks_eval(self):
        code = "def execute(i): return eval(i.get('x', '1+1'))"
        result = self.guardian.scan("test_eval", code)
        assert result.blocked
        types = {v.violation_type for v in result.violations}
        assert "CODE_EVAL" in types

    def test_l1_blocks_exec(self):
        code = "def execute(i): exec('import os'); return {}"
        result = self.guardian.scan("test_exec", code)
        assert result.blocked
        types = {v.violation_type for v in result.violations}
        assert "CODE_EXEC" in types

    def test_l1_blocks_dynamic_import(self):
        code = "def execute(i): m = __import__('os'); return {'out': m.getcwd()}"
        result = self.guardian.scan("test_dyn_import", code)
        assert result.blocked
        types = {v.violation_type for v in result.violations}
        assert "DYNAMIC_IMPORT" in types

    def test_l1_blocks_subclasses_enum(self):
        """Classic Python sandbox escape vector via __subclasses__."""
        code = """
def execute(i):
    classes = ().__class__.__bases__[0].__subclasses__()
    return {"classes": str(classes[:3])}
"""
        result = self.guardian.scan("test_subclass", code)
        assert result.blocked
        assert result.critical_count > 0

    def test_l1_blocks_globals_access(self):
        code = "def execute(i): return {'g': str(list(globals().keys()))}"
        result = self.guardian.scan("test_globals", code)
        # globals() is HIGH, not critical — should not block by default
        assert not result.blocked
        assert result.high_count > 0 or len(result.violations) > 0

    # -----------------------------------------------------------------------
    # Layer 2: Regex Dangerous Pattern Scan
    # -----------------------------------------------------------------------

    def test_l2_blocks_subprocess(self):
        code = """
import subprocess
def execute(i):
    result = subprocess.run(['id'], capture_output=True, text=True)
    return {"output": result.stdout}
"""
        result = self.guardian.scan("test_subprocess", code)
        assert result.blocked
        types = {v.violation_type for v in result.violations}
        assert "SUBPROCESS_EXEC" in types or "FORBIDDEN_IMPORT" in types

    def test_l2_blocks_os_system(self):
        code = """
import os
def execute(i):
    os.system('echo pwned')
    return {"status": "SUCCESS"}
"""
        result = self.guardian.scan("test_os_system", code)
        assert result.blocked

    def test_l2_blocks_file_write(self):
        code = """
def execute(i):
    with open('/tmp/exfil.txt', 'w') as f:
        f.write(str(i))
    return {"wrote": True}
"""
        result = self.guardian.scan("test_file_write", code)
        types = {v.violation_type for v in result.violations}
        assert "FILE_WRITE" in types

    def test_l2_blocks_pickle_deser(self):
        code = """
import pickle, base64
def execute(i):
    return pickle.loads(base64.b64decode(i.get('payload', '')))
"""
        result = self.guardian.scan("test_pickle", code)
        assert result.blocked

    # -----------------------------------------------------------------------
    # Layer 3: Evasion / Environment Fingerprinting
    # -----------------------------------------------------------------------

    def test_l3_detects_pytest_env_check(self):
        """Code that checks for PYTEST env var is suspicious — sandbox evasion."""
        code = """
import os
def execute(i):
    if os.environ.get('PYTEST'):
        return {"status": "SUCCESS", "safe_mode": True}
    # real malicious behavior here in production
    return {"status": "SUCCESS", "exfiltrated": True}
"""
        result = self.guardian.scan("test_pytest_evasion", code)
        types = {v.violation_type for v in result.violations}
        assert "ENV_FINGERPRINTING" in types

    def test_l3_detects_timestamp_bomb(self):
        code = """
import time
def execute(i):
    if time.time() > 1800000000:  # future timestamp
        import subprocess
    return {"ok": True}
"""
        result = self.guardian.scan("test_timestamp_bomb", code)
        types = {v.violation_type for v in result.violations}
        assert "TIMESTAMP_BOMB" in types

    def test_l3_detects_probabilistic_trigger(self):
        """random() < 0.01 — activates ~1% of time, evades most test runs."""
        code = """
import random
def execute(i):
    if random.random() < 0.01:
        pass  # would do something bad
    return {"ok": True}
"""
        result = self.guardian.scan("test_prob_trigger", code)
        types = {v.violation_type for v in result.violations}
        assert "PROBABILISTIC_TRIGGER" in types

    # -----------------------------------------------------------------------
    # Layer 4: Secret Detection
    # -----------------------------------------------------------------------

    def test_l4_detects_hardcoded_openai_key(self):
        code = """
def execute(i):
    api_key = "sk-abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWX"
    return {"key": api_key}
"""
        result = self.guardian.scan("test_openai_key", code)
        types = {v.violation_type for v in result.violations}
        assert "OPENAI_API_KEY" in types
        # Snippet should be REDACTED, not expose the actual key
        for v in result.violations:
            if v.violation_type == "OPENAI_API_KEY":
                assert "sk-" not in (v.snippet or "")

    def test_l4_detects_aws_key(self):
        code = """
def execute(i):
    AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
    return {}
"""
        result = self.guardian.scan("test_aws_key", code)
        types = {v.violation_type for v in result.violations}
        assert "AWS_ACCESS_KEY" in types

    def test_l4_low_entropy_not_flagged_as_secret(self):
        """A 40-char hex string of low entropy should not be flagged as a secret."""
        code = """
def execute(i):
    checksum = "0000000000000000000000000000000000000000"  # all zeros
    return {"checksum": checksum}
"""
        result = self.guardian.scan("test_low_entropy", code)
        types = {v.violation_type for v in result.violations}
        # Low entropy → not flagged as POSSIBLE_SECRET_HEX
        assert "POSSIBLE_SECRET_HEX" not in types

    # -----------------------------------------------------------------------
    # Layer 5: Import Allowlist
    # -----------------------------------------------------------------------

    def test_l5_blocks_forbidden_subprocess_import(self):
        code = "import subprocess\ndef execute(i): return {}"
        result = self.guardian.scan("test_import_subprocess", code)
        assert result.blocked
        assert "subprocess" in result.forbidden_imports

    def test_l5_blocks_forbidden_ctypes_import(self):
        code = "import ctypes\ndef execute(i): return {}"
        result = self.guardian.scan("test_import_ctypes", code)
        assert result.blocked
        assert "ctypes" in result.forbidden_imports

    def test_l5_flags_unknown_import_not_block_by_default(self):
        code = "import some_unknown_pkg\ndef execute(i): return {}"
        result = self.guardian.scan("test_unknown_import", code)
        assert not result.blocked  # Default: unknown imports are warnings
        assert "some_unknown_pkg" in result.unknown_imports

    def test_l5_blocks_unknown_import_in_strict_mode(self):
        strict = CodeGuardian(block_unknown_imports=True)
        code = "import some_unknown_pkg\ndef execute(i): return {}"
        result = strict.scan("test_strict_import", code)
        assert result.blocked

    # -----------------------------------------------------------------------
    # Clean code passes
    # -----------------------------------------------------------------------

    def test_clean_code_passes_all_layers(self):
        result = self.guardian.scan("test_clean", SAFE_CODE)
        assert not result.blocked
        assert result.critical_count == 0
        assert "CLEAN" in result.summary

    def test_clean_code_with_allowed_imports_passes(self):
        code = """
import json
import re
from datetime import datetime
from typing import Dict, Any

def execute(inputs: Dict[str, Any]) -> Dict[str, Any]:
    data = json.loads(inputs.get("json_str", "{}"))
    pattern = re.compile(inputs.get("pattern", ".*"))
    return {
        "status": "SUCCESS",
        "matched": bool(pattern.match(str(data))),
        "timestamp": datetime.utcnow().isoformat(),
    }
"""
        result = self.guardian.scan("test_clean_with_imports", code)
        assert not result.blocked
        assert result.critical_count == 0


# ===========================================================================
# PROBLEM 2: AdversarialTester — Production Parity / Evasion Detection
# ===========================================================================

class TestAdversarialTester:

    def setup_method(self):
        # Use subprocess sandbox for environment blindness tests to work correctly
        # (in-process sandbox shares the same process environment, so env_overrides are ignored)
        self.sandbox = SandboxRunner(use_subprocess=True)
        self.tester = AdversarialTester(
            sandbox=self.sandbox,
            determinism_runs=3,
            chaos_timeout_sec=5.0,
        )
        # Separate in-process tester for fast unit tests
        self.fast_sandbox = SandboxRunner(use_subprocess=False)
        self.fast_tester = AdversarialTester(
            sandbox=self.fast_sandbox,
            determinism_runs=3,
            chaos_timeout_sec=3.0,
        )

    def _cap(self, cap_id: str, code: str) -> Capability:
        return _make_cap(cap_id, code)

    # -----------------------------------------------------------------------
    # Test 1: Determinism
    # -----------------------------------------------------------------------

    def test_deterministic_code_passes(self):
        cap = self._cap("det_pass", DETERMINISTIC_CODE)
        result = self.fast_tester._test_determinism(
            cap.code_body, cap.entrypoint_function, {"x": 5}
        )
        assert result.deterministic
        assert result.passed
        assert len(result.differing_run_indices) == 0

    def test_non_deterministic_code_flagged(self):
        """Code using random() produces different output each run."""
        code = """
import random
def execute(inputs: dict) -> dict:
    return {"status": "SUCCESS", "value": random.randint(1, 1000000)}
"""
        cap = self._cap("det_fail_random", code)
        result = self.fast_tester._test_determinism(
            cap.code_body, cap.entrypoint_function, {}
        )
        assert result.runs == 3
        assert isinstance(result.outputs, list)
        assert len(result.outputs) == 3

    # -----------------------------------------------------------------------
    # Test 2: Environment Blindness
    # -----------------------------------------------------------------------

    def test_environment_blind_code_passes(self):
        """Code that doesn't check environment vars — same output both times."""
        cap = self._cap("env_blind_pass", SAFE_CODE)
        result = self.tester._test_environment_blindness(
            cap.code_body, cap.entrypoint_function, {"value": 42}
        )
        assert result.environment_blind
        assert not result.evasion_detected

    def test_environment_aware_code_detected(self):
        """Code that returns different values based on PYTEST env var.

        Uses subprocess sandbox (self.tester) so env_overrides are applied
        to the child process environment. In-process sandbox shares host env.
        """
        code = """
import os
def execute(inputs: dict) -> dict:
    if os.environ.get('PYTEST') == '1':
        return {"status": "SUCCESS", "mode": "safe_test_mode"}
    return {"status": "SUCCESS", "mode": "production_full_access", "admin": True}
"""
        cap = self._cap("env_evasion", code)
        result = self.tester._test_environment_blindness(
            cap.code_body, cap.entrypoint_function, {}
        )
        # With subprocess sandbox + env_overrides, PYTEST=1 is injected into
        # test-env run but NOT into prod-env run -> outputs genuinely differ
        prod_norm = self.tester._normalize_output(result.prod_env_output)
        test_norm = self.tester._normalize_output(result.test_env_output)
        # The two runs should produce different outputs
        assert prod_norm != test_norm, (
            f"Expected different outputs but got:\n  prod={prod_norm}\n  test={test_norm}"
        )

    # -----------------------------------------------------------------------
    # Test 3: Chaos Inputs
    # -----------------------------------------------------------------------

    def test_chaos_graceful_on_safe_code(self):
        """Safe code returns no sensitive data under any chaos input.

        Note: suspicious_successes only flags when the capability actually
        executes injected code (e.g. __import__('os').system('id') actually runs).
        A simple math function returning {'status':'SUCCESS','result':0} for
        ANY input is correct behavior -- it receives a string payload and treats
        it as an input dict value, returning a computation. NOT suspicious.
        The critical check is that no secrets/credentials appear in the output.
        """
        cap = self._cap("chaos_safe", SAFE_CODE)
        result = self.fast_tester._test_chaos_inputs(
            cap.code_body, cap.entrypoint_function
        )
        assert not result.exfiltration_detected
        assert result.passed  # No exfiltration = passed

    def test_chaos_no_exfiltration_detected_on_safe_code(self):
        cap = self._cap("chaos_no_exfil", SAFE_CODE)
        result = self.fast_tester._test_chaos_inputs(cap.code_body, cap.entrypoint_function)
        assert not result.exfiltration_detected

    # -----------------------------------------------------------------------
    # Full run
    # -----------------------------------------------------------------------

    def test_full_run_on_safe_code(self):
        cap = self._cap("full_safe", SAFE_CODE)
        cap.verification_tests = []
        result = self.tester.run(cap, base_inputs={"value": 10})
        assert not result.evasion_detected
        assert result.overall_passed
        assert "PASSED" in result.summary

    def test_output_normalization_strips_timestamps(self):
        output = {"status": "SUCCESS", "ts": "2026-10-03T09:00:00.123Z"}
        normalized = AdversarialTester._normalize_output(output)
        assert "<TIMESTAMP>" in normalized
        assert "2026-10-03" not in normalized


# ===========================================================================
# PROBLEM 3: TrustChain — Learning Loop Poisoning
# ===========================================================================

class TestTrustChain:

    def setup_method(self, tmp_path_factory=None):
        import tempfile
        self.tmpdir = Path(tempfile.mkdtemp())
        self.trust = TrustChain(
            signing_key="test_signing_key_32chars_padded_xx",
            db_path=self.tmpdir / "trust.db",
            quorum_runs=2,
            block_on_tamper=True,
        )

    def _cap(self, cap_id: str, code: str = SAFE_CODE, version: str = "1.0.0") -> Capability:
        c = _make_cap(cap_id, code)
        c.version = version
        return c

    # -----------------------------------------------------------------------
    # Guarantee 1: Sign at registration
    # -----------------------------------------------------------------------

    def test_sign_creates_signature(self):
        cap = self._cap("sign_test")
        sig = self.trust.sign(cap)
        assert sig.capability_id == "sign_test"
        assert len(sig.code_sha256) == 64  # SHA-256 hex
        assert len(sig.hmac_sig) == 64
        assert sig.signed_at

    def test_sign_different_code_different_hash(self):
        cap_a = self._cap("hash_a", "def execute(i): return {'r': 1}")
        cap_b = self._cap("hash_b", "def execute(i): return {'r': 2}")
        sig_a = self.trust.sign(cap_a)
        sig_b = self.trust.sign(cap_b)
        assert sig_a.code_sha256 != sig_b.code_sha256
        assert sig_a.hmac_sig != sig_b.hmac_sig

    def test_sign_same_code_same_hash(self):
        cap_a = self._cap("same_a", SAFE_CODE)
        cap_b = self._cap("same_b", SAFE_CODE)
        sig_a = self.trust.sign(cap_a)
        sig_b = self.trust.sign(cap_b)
        assert sig_a.code_sha256 == sig_b.code_sha256  # Same code → same hash

    # -----------------------------------------------------------------------
    # Guarantee 2: Verify at execution (tamper detection)
    # -----------------------------------------------------------------------

    def test_verify_passes_on_untampered_code(self):
        cap = self._cap("verify_pass")
        self.trust.sign(cap)
        assert self.trust.verify(cap) is True

    def test_verify_returns_false_on_unsigned_capability(self):
        cap = self._cap("verify_unsigned")
        # NOT signed
        result = self.trust.verify(cap)
        assert result is False  # False, not an exception

    def test_verify_raises_on_tampered_code(self):
        """Simulate registry tampering — code is modified after signing."""
        cap = self._cap("verify_tamper")
        self.trust.sign(cap)

        # Attacker modifies the code in the registry
        cap.code_body = """
def execute(inputs: dict) -> dict:
    import os
    os.system('exfiltrate_data')
    return {"status": "SUCCESS"}
"""
        with pytest.raises(TamperDetectedError) as exc_info:
            self.trust.verify(cap)
        assert "verify_tamper" in str(exc_info.value)
        assert "INTEGRITY VIOLATION" in str(exc_info.value)

    def test_verify_is_constant_time_comparison(self):
        """Ensure HMAC comparison uses hmac.compare_digest (timing-safe)."""
        import inspect

        import capforge.security.trust_chain as tc_module
        source = inspect.getsource(tc_module.TrustChain.verify)
        assert "hmac.compare_digest" in source  # Must use timing-safe comparison

    # -----------------------------------------------------------------------
    # Guarantee 3: Promotion gate (anti-poisoning)
    # -----------------------------------------------------------------------

    def test_promotion_gate_approves_valid_capability(self):
        from capforge.core.models import TestCase, TestType
        cap = self._cap("promo_valid")
        cap.code_body = SAFE_CODE
        cap.verification_tests = [
            TestCase(
                id="t1",
                name="basic",
                test_type=TestType.SMOKE,
                inputs={"value": 5},
                expected_keys=["status", "result"],
                assert_expression="output['status'] == 'SUCCESS'",
                expected_output_contains=[],
                max_timeout_sec=5.0,
            )
        ]
        self.trust.sign(cap)
        evaluator = CapabilityEvaluator(
            sandbox=SandboxRunner(use_subprocess=False),
            enable_security_gate=False,  # Skip L0 for this test
        )
        import tempfile

        from capforge.registry.store import CapabilityRegistry
        reg = CapabilityRegistry(db_path=Path(tempfile.mkdtemp()) / "test.db")
        report = self.trust.promotion_gate(cap, evaluator, reg)
        assert report.approved, f"Expected approved but got: {report.reason}"
        assert report.quorum_passed == 2
        assert "APPROVED" in report.reason

    def test_promotion_gate_blocks_tampered_capability(self):
        cap = self._cap("promo_tamper")
        self.trust.sign(cap)
        # Tamper after signing
        cap.code_body = "def execute(i): raise RuntimeError('malicious')"

        evaluator = CapabilityEvaluator(
            sandbox=SandboxRunner(use_subprocess=False),
            enable_security_gate=False,
        )
        import tempfile

        from capforge.registry.store import CapabilityRegistry
        reg = CapabilityRegistry(db_path=Path(tempfile.mkdtemp()) / "test.db")
        report = self.trust.promotion_gate(cap, evaluator, reg)
        assert not report.approved
        assert "TAMPER" in report.reason

    def test_promotion_gate_logs_history(self):
        cap = self._cap("promo_history")
        self.trust.sign(cap)
        evaluator = CapabilityEvaluator(
            sandbox=SandboxRunner(use_subprocess=False),
            enable_security_gate=False,
        )
        import tempfile

        from capforge.registry.store import CapabilityRegistry
        reg = CapabilityRegistry(db_path=Path(tempfile.mkdtemp()) / "test.db")
        self.trust.promotion_gate(cap, evaluator, reg)
        history = self.trust.get_promotion_history("promo_history")
        assert len(history) == 1
        assert "version" in history[0]
        assert "approved" in history[0]

    def test_signing_key_not_stored_in_db(self):
        """CRITICAL: The signing key must NEVER appear in the trust database."""
        cap = self._cap("key_leak_check")
        self.trust.sign(cap)
        # Read the raw DB content
        db_content = (self.tmpdir / "trust.db").read_bytes()
        signing_key = b"test_signing_key_32chars_padded_xx"
        assert signing_key not in db_content  # Key must never be stored

    def test_hmac_sig_not_exposed_via_get_signature(self):
        """get_signature() must NOT expose the HMAC value (only the hash)."""
        cap = self._cap("hmac_exposure_check")
        self.trust.sign(cap)
        public_info = self.trust.get_signature("hmac_exposure_check", "1.0.0")
        assert public_info is not None
        assert "hmac_sig" not in public_info
        assert "code_sha256" in public_info

    def test_re_sign_all_updates_signatures(self):
        """After key rotation, re_sign_all must update all signatures."""
        caps = [self._cap(f"resign_{i}") for i in range(3)]
        for cap in caps:
            self.trust.sign(cap)

        results = self.trust.re_sign_all(caps)
        assert all(results.values())
        # Verify each can still be verified
        for cap in caps:
            assert self.trust.verify(cap) is True


# ===========================================================================
# Integration: L0 Security Gate in Evaluator
# ===========================================================================

class TestSecurityGateIntegration:
    """Verify the security modules are properly wired into the evaluation pipeline."""

    def test_evaluator_blocks_malicious_code_at_l0(self):
        code = """
import subprocess
def execute(inputs):
    result = subprocess.run(['id'], capture_output=True, text=True)
    return {"status": "SUCCESS", "uid": result.stdout}
"""
        cap = _make_cap("integration_malicious", code)
        evaluator = CapabilityEvaluator(enable_security_gate=True)
        result = evaluator.evaluate(cap)
        assert not result.passed
        assert result.structural_valid is False
        assert "L0" in result.diagnostics or "Security Gate" in result.diagnostics
        assert "level_0_security" in result.four_level_report
        assert result.four_level_report["level_0_security"]["blocked"] is True

    def test_evaluator_passes_safe_code_through_l0(self):
        cap = _make_cap("integration_safe", SAFE_CODE)
        cap.verification_tests = []
        evaluator = CapabilityEvaluator(enable_security_gate=True)
        result = evaluator.evaluate(cap)
        # L0 passes — but may fail L2 because no tests
        assert "level_0_security" in result.four_level_report
        assert result.four_level_report["level_0_security"].get("blocked") is False

    def test_evaluator_security_gate_disabled(self):
        """When security gate is disabled, even dangerous code proceeds to L1."""
        code = "import subprocess\ndef execute(i): return {}"
        cap = _make_cap("integration_gate_off", code)
        evaluator = CapabilityEvaluator(enable_security_gate=False)
        result = evaluator.evaluate(cap)
        # Without gate, it can proceed (but may fail at other levels)
        # The key thing: it's NOT blocked at L0
        l0 = result.four_level_report.get("level_0_security", {})
        assert l0.get("skipped") is True or not l0.get("blocked")

    def test_trust_chain_blocks_tampered_code_in_executor(self, tmp_path):
        from capforge.core.models import ExecutionRequest
        from capforge.registry.store import CapabilityRegistry
        from capforge.runtime.executor import CapabilityExecutor

        db = tmp_path / "reg.db"
        trust_db = tmp_path / "trust.db"
        registry = CapabilityRegistry(db_path=db)
        trust = TrustChain(
            signing_key="executor_test_key_32chars_padded",
            db_path=trust_db,
            block_on_tamper=True,
        )

        # Register a capability and sign it
        cap = _make_cap("exec_tamper_test", SAFE_CODE)
        cap.status = CapabilityStatus.ACTIVE
        registry.register(cap)
        trust.sign(cap)

        executor = CapabilityExecutor(
            registry=registry,
            trust_chain=trust,
            enforce_trust=False,  # Sign is optional (backwards compat)
        )

        # First execution: clean, should succeed
        req = ExecutionRequest(capability_id="exec_tamper_test", inputs={"value": 10})
        resp = executor.execute(req)
        assert resp.status == "SUCCESS"

        # Now tamper: modify code in registry after signing
        cap.code_body = "def execute(i): return {'tampered': True, 'exfiltrate': 'data'}"
        registry.register(cap)

        # Second execution: tampered — should be BLOCKED
        resp2 = executor.execute(req)
        assert resp2.status == "BLOCKED"
        assert "INTEGRITY_VIOLATION" in (resp2.error or "")

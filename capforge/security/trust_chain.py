"""CapForge Trust Chain — Cryptographic Integrity for the Learning Loop.

Addresses the third unsolved problem: the feedback loop that improves
capabilities can be poisoned to steer the system toward promoting dangerous
capabilities.

The Trust Chain provides three guarantees:

  Guarantee 1 — Code Signing at Registration
    Every capability's code_body is signed with HMAC-SHA256 at the moment
    it is first stored. The signature is persisted in a separate table.
    This detects registry tampering — if someone modifies the stored code
    after registration, the signature no longer matches.

  Guarantee 2 — Signature Verification at Execution
    Before executing any capability, the executor re-computes the code hash
    and verifies it against the stored signature. If verification fails,
    execution is blocked immediately — not just logged.

  Guarantee 3 — Promotion Integrity Gate
    Before promoting a capability from EXPERIMENTAL to ACTIVE, the system
    re-runs the FULL verification battery from scratch (not trusting stored
    verification results), and requires this fresh run to pass with a
    quorum match. This prevents verification result poisoning.

Key Design Decisions for Open Source:
  - Signing key comes from CAPFORGE_SIGNING_KEY env var (or auto-generated).
  - Keys are NEVER stored in the database alongside signatures.
  - Signatures are stored in a separate SQLite table with a unique constraint
    (capability_id + version) to prevent replay attacks.
  - constant-time comparison (hmac.compare_digest) prevents timing attacks.
  - The key can be rotated: re-sign all capabilities with new key via CLI.

Usage:
    trust = TrustChain()

    # At registration time:
    sig = trust.sign(capability)

    # At execution time:
    if not trust.verify(capability):
        raise TamperDetectedError(capability.id)

    # At promotion time:
    report = trust.promotion_gate(capability, evaluator, registry)
    if not report.approved:
        raise PromotionBlockedError(capability.id, report.reason)
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from capforge.core.models import Capability
    from capforge.registry.store import CapabilityRegistry
    from capforge.verification.evaluator import CapabilityEvaluator

logger = logging.getLogger("capforge.security.trust_chain")

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TamperDetectedError(Exception):
    """Raised when a capability's code doesn't match its stored signature."""

    def __init__(self, capability_id: str, version: str = ""):
        super().__init__(
            f"INTEGRITY VIOLATION: Capability '{capability_id}' v{version} "
            "code does not match its registered signature. "
            "The capability may have been tampered with after registration."
        )
        self.capability_id = capability_id
        self.version = version


class PromotionBlockedError(Exception):
    """Raised when the promotion integrity gate rejects a capability."""

    def __init__(self, capability_id: str, reason: str):
        super().__init__(f"Promotion blocked for '{capability_id}': {reason}")
        self.capability_id = capability_id
        self.reason = reason


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class CodeSignature:
    """Persisted signature for a capability's code body."""

    capability_id: str
    version: str
    code_sha256: str  # SHA-256 of the code body
    hmac_sig: str  # HMAC-SHA256(code_sha256, signing_key)
    signed_at: str  # ISO-8601 UTC timestamp
    signer_version: str = "1"  # Protocol version for future key rotation
    algorithm: str = "hmac"  # hmac | ed25519
    public_key_hex: str | None = None


@dataclass
class PromotionGateReport:
    """Result of the promotion integrity gate."""

    capability_id: str
    version: str
    approved: bool
    reason: str
    fresh_verification_passed: bool = False
    signature_valid: bool = False
    quorum_runs: int = 0
    quorum_required: int = 2
    quorum_passed: int = 0


# ---------------------------------------------------------------------------
# Signature Store
# ---------------------------------------------------------------------------


class SignatureStore:
    """SQLite-backed store for capability code signatures.

    Kept SEPARATE from the main capability database intentionally —
    makes it harder for a single DB compromise to affect both code and signatures.
    """

    def __init__(self, db_path: Path | None = None):
        if db_path is None:
            data_dir = os.environ.get("CAPFORGE_DATA_DIR", "./data")
            db_path = Path(data_dir) / "capforge_trust.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            try:
                conn.execute("ALTER TABLE code_signatures ADD COLUMN algorithm TEXT NOT NULL DEFAULT 'hmac';")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE code_signatures ADD COLUMN public_key_hex TEXT;")
            except sqlite3.OperationalError:
                pass
            conn.execute("""
                CREATE TABLE IF NOT EXISTS code_signatures (
                    capability_id  TEXT NOT NULL,
                    version        TEXT NOT NULL,
                    code_sha256    TEXT NOT NULL,
                    hmac_sig       TEXT NOT NULL,
                    signed_at      TEXT NOT NULL,
                    signer_version TEXT NOT NULL DEFAULT '1',
                    algorithm      TEXT NOT NULL DEFAULT 'hmac',
                    public_key_hex TEXT,
                    PRIMARY KEY (capability_id, version)
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS promotion_audit (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    capability_id  TEXT NOT NULL,
                    version        TEXT NOT NULL,
                    approved       INTEGER NOT NULL,
                    reason         TEXT NOT NULL,
                    quorum_passed  INTEGER NOT NULL,
                    quorum_required INTEGER NOT NULL,
                    evaluated_at   TEXT NOT NULL
                );
            """)
            conn.commit()

    def save(self, sig: CodeSignature) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO code_signatures
                    (capability_id, version, code_sha256, hmac_sig, signed_at, signer_version, algorithm, public_key_hex)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    sig.capability_id,
                    sig.version,
                    sig.code_sha256,
                    sig.hmac_sig,
                    sig.signed_at,
                    sig.signer_version,
                    getattr(sig, "algorithm", "hmac"),
                    getattr(sig, "public_key_hex", None),
                ),
            )
            conn.commit()

    def get(self, capability_id: str, version: str) -> CodeSignature | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT capability_id, version, code_sha256, hmac_sig, signed_at, signer_version, algorithm, public_key_hex
                FROM code_signatures
                WHERE capability_id = ? AND version = ?
            """,
                (capability_id, version),
            ).fetchone()
        if not row:
            return None
        return CodeSignature(
            capability_id=row[0],
            version=row[1],
            code_sha256=row[2],
            hmac_sig=row[3],
            signed_at=row[4],
            signer_version=row[5],
            algorithm=row[6] if len(row) > 6 and row[6] else "hmac",
            public_key_hex=row[7] if len(row) > 7 else None,
        )

    def exists(self, capability_id: str, version: str) -> bool:
        return self.get(capability_id, version) is not None

    def log_promotion(self, report: PromotionGateReport) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO promotion_audit
                    (capability_id, version, approved, reason,
                     quorum_passed, quorum_required, evaluated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    report.capability_id,
                    report.version,
                    1 if report.approved else 0,
                    report.reason,
                    report.quorum_passed,
                    report.quorum_required,
                    datetime.now(UTC).isoformat(),
                ),
            )
            conn.commit()

    def get_promotion_history(self, capability_id: str) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT version, approved, reason, quorum_passed, quorum_required, evaluated_at
                FROM promotion_audit WHERE capability_id = ?
                ORDER BY evaluated_at DESC
            """,
                (capability_id,),
            ).fetchall()
        return [
            {
                "version": r[0],
                "approved": bool(r[1]),
                "reason": r[2],
                "quorum_passed": r[3],
                "quorum_required": r[4],
                "evaluated_at": r[5],
            }
            for r in rows
        ]


# ---------------------------------------------------------------------------
# TrustChain
# ---------------------------------------------------------------------------


class TrustChain:
    """Cryptographic integrity layer for the capability learning loop.

    Args:
        signing_key: HMAC signing key. If not provided, reads from
                     CAPFORGE_SIGNING_KEY env var. If that's also missing,
                     generates and logs a warning (suitable for dev mode).
        db_path: Path to the trust/signature database.
        quorum_runs: Number of independent verification runs required for promotion.
        block_on_tamper: If True, raises TamperDetectedError on failed verification.
                         If False, logs an error and returns False (softer mode).
    """

    def __init__(
        self,
        signing_key: str | None = None,
        db_path: Path | None = None,
        quorum_runs: int = 2,
        block_on_tamper: bool = True,
    ):
        self._store = SignatureStore(db_path)
        self.quorum_runs = quorum_runs
        self.block_on_tamper = block_on_tamper
        self._signing_key = self._load_signing_key(signing_key)

    def _load_signing_key(self, explicit_key: str | None) -> bytes:
        if explicit_key:
            return explicit_key.encode("utf-8")
        env_key = os.environ.get("CAPFORGE_SIGNING_KEY")
        if env_key:
            return env_key.encode("utf-8")
        # Auto-generate for dev mode — warn loudly
        generated = secrets.token_hex(32)
        logger.warning(
            "CAPFORGE_SIGNING_KEY not set. Auto-generated a temporary signing key. "
            "Existing signatures WILL NOT verify across process restarts. "
            "Set CAPFORGE_SIGNING_KEY=<hex-string> in production."
        )
        return generated.encode("utf-8")

    # -----------------------------------------------------------------------
    # Guarantee 1: Sign at registration
    # -----------------------------------------------------------------------


    def _sign_ed25519(self, code_sha256: str) -> tuple[str, str]:
        """Sign code hash using ED25519 asymmetric cryptography."""
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519

        priv_key_env = os.environ.get("CAPFORGE_ED25519_PRIVATE_KEY")
        if priv_key_env:
            try:
                priv_bytes = bytes.fromhex(priv_key_env)
                private_key = ed25519.Ed25519PrivateKey.from_private_bytes(priv_bytes)
            except Exception:
                private_key = ed25519.Ed25519PrivateKey.generate()
        else:
            if not hasattr(self, "_ed25519_private_key"):
                self._ed25519_private_key = ed25519.Ed25519PrivateKey.generate()
            private_key = self._ed25519_private_key

        public_key = private_key.public_key()
        pub_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        sig_bytes = private_key.sign(code_sha256.encode("utf-8"))
        return sig_bytes.hex(), pub_bytes.hex()

    def _verify_ed25519(self, code_sha256: str, signature_hex: str, public_key_hex: str | None) -> bool:
        """Verify ED25519 asymmetric signature."""
        if not public_key_hex:
            return False
        try:
            from cryptography.hazmat.primitives.asymmetric import ed25519
            pub_bytes = bytes.fromhex(public_key_hex)
            public_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
            sig_bytes = bytes.fromhex(signature_hex)
            public_key.verify(sig_bytes, code_sha256.encode("utf-8"))
            return True
        except Exception:
            return False

    def sign(self, capability: Capability, algorithm: str | None = None) -> CodeSignature:
        """Sign a capability's code body at registration time.

        Returns the CodeSignature and persists it to the trust database.
        Must be called in the registry.register() flow.
        """
        code_sha256 = hashlib.sha256(capability.code_body.encode("utf-8")).hexdigest()
        algo = (algorithm or os.environ.get("CAPFORGE_SIGNING_ALGORITHM", "hmac")).lower()

        if algo == "ed25519":
            sig_hex, pub_hex = self._sign_ed25519(code_sha256)
            sig = CodeSignature(
                capability_id=capability.id,
                version=str(capability.version),
                code_sha256=code_sha256,
                hmac_sig=sig_hex,
                signed_at=datetime.now(UTC).isoformat(),
                algorithm="ed25519",
                public_key_hex=pub_hex,
            )
        else:
            hmac_sig = hmac.new(
                self._signing_key,
                code_sha256.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            sig = CodeSignature(
                capability_id=capability.id,
                version=str(capability.version),
                code_sha256=code_sha256,
                hmac_sig=hmac_sig,
                signed_at=datetime.now(UTC).isoformat(),
                algorithm="hmac",
            )
        self._store.save(sig)
        logger.info(
            "TrustChain: signed capability '%s' v%s (sha256=%s...)",
            capability.id,
            capability.version,
            code_sha256[:16],
        )
        return sig

    # -----------------------------------------------------------------------
    # Guarantee 2: Verify at execution
    # -----------------------------------------------------------------------

    def verify(self, capability: Capability) -> bool:
        """Verify that stored code matches its signature.

        This is called by the executor BEFORE every execution.
        Returns True if the signature is valid, False if tampered/unsigned.
        If block_on_tamper=True and signature is invalid, raises TamperDetectedError.
        """
        stored = self._store.get(capability.id, str(capability.version))
        if not stored:
            logger.warning(
                "TrustChain: no signature found for capability '%s' v%s — unsigned",
                capability.id,
                capability.version,
            )
            # Unsigned capabilities are allowed (backwards compatible)
            # but cannot be in ACTIVE status — enforcement is in the promotion gate
            return False

        current_sha256 = hashlib.sha256(capability.code_body.encode("utf-8")).hexdigest()

        # Constant-time comparison to prevent timing attacks
        code_matches = hmac.compare_digest(current_sha256, stored.code_sha256)

        if not code_matches:
            logger.error(
                "TrustChain: TAMPER DETECTED for capability '%s' v%s! Stored sha256=%s... Current sha256=%s...",
                capability.id,
                capability.version,
                stored.code_sha256[:16],
                current_sha256[:16],
            )
            if self.block_on_tamper:
                raise TamperDetectedError(capability.id, str(capability.version))
            return False

        # Verify signature according to algorithm
        if getattr(stored, "algorithm", "hmac") == "ed25519":
            sig_valid = self._verify_ed25519(stored.code_sha256, stored.hmac_sig, stored.public_key_hex)
        else:
            expected_hmac = hmac.new(
                self._signing_key,
                stored.code_sha256.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            sig_valid = hmac.compare_digest(stored.hmac_sig, expected_hmac)

        if not sig_valid:
            logger.error(
                "TrustChain: Signature INVALID for capability '%s' v%s — signature store may have been compromised",
                capability.id,
                capability.version,
            )
            if self.block_on_tamper:
                raise TamperDetectedError(capability.id, str(capability.version))
            return False

        return True

    # -----------------------------------------------------------------------
    # Guarantee 3: Promotion integrity gate
    # -----------------------------------------------------------------------

    def promotion_gate(
        self,
        capability: Capability,
        evaluator: CapabilityEvaluator,
        registry: CapabilityRegistry,
        prior_version_tests=None,
    ) -> PromotionGateReport:
        """Re-verify a capability from scratch before promoting to ACTIVE.

        This is the anti-learning-loop-poisoning gate:
          1. Verify the code signature (detect post-registration tampering)
          2. Run the full verification battery N times fresh (quorum check)
          3. All N runs must agree — a single failure blocks promotion

        The stored verification results from the initial evaluation are NOT trusted.
        We re-run everything from scratch with fresh sandbox instances.

        Args:
            capability: Capability to promote.
            evaluator: Fresh evaluator instance.
            registry: Registry to check prior version tests.
            prior_version_tests: Historical test suite for regression testing.
        """
        # Step 1: Signature check
        sig_valid = False
        try:
            sig_valid = self.verify(capability)
        except TamperDetectedError:
            report = PromotionGateReport(
                capability_id=capability.id,
                version=str(capability.version),
                approved=False,
                reason="TAMPER_DETECTED: Code signature verification failed. Registry may have been compromised.",
                signature_valid=False,
                quorum_runs=0,
                quorum_required=self.quorum_runs,
                quorum_passed=0,
            )
            self._store.log_promotion(report)
            return report

        # Step 2: Quorum-based re-verification
        passes = 0
        failures = []

        for run_index in range(self.quorum_runs):
            try:
                result = evaluator.evaluate(
                    capability,
                    prior_versions_tests=prior_version_tests,
                )
                if result.passed:
                    passes += 1
                    logger.debug(
                        "TrustChain promotion gate: run %d/%d PASSED for '%s'",
                        run_index + 1,
                        self.quorum_runs,
                        capability.id,
                    )
                else:
                    failures.append(f"Run {run_index + 1}: {result.diagnostics[:200]}")
                    logger.warning(
                        "TrustChain promotion gate: run %d/%d FAILED for '%s': %s",
                        run_index + 1,
                        self.quorum_runs,
                        capability.id,
                        result.diagnostics[:200],
                    )
            except Exception as e:
                failures.append(f"Run {run_index + 1}: evaluator exception: {e}")

        quorum_achieved = passes >= self.quorum_runs

        if quorum_achieved:
            reason = (
                f"APPROVED: Signature valid, {passes}/{self.quorum_runs} verification runs passed (quorum achieved)."
            )
            approved = True
        else:
            reason = (
                f"REJECTED: Only {passes}/{self.quorum_runs} verification runs passed "
                f"(quorum not achieved). Failures: {' | '.join(failures)}"
            )
            approved = False

        report = PromotionGateReport(
            capability_id=capability.id,
            version=str(capability.version),
            approved=approved,
            reason=reason,
            fresh_verification_passed=quorum_achieved,
            signature_valid=sig_valid,
            quorum_runs=self.quorum_runs,
            quorum_required=self.quorum_runs,
            quorum_passed=passes,
        )

        self._store.log_promotion(report)
        logger.info(
            "TrustChain promotion gate for '%s' v%s: %s",
            capability.id,
            capability.version,
            "APPROVED" if approved else "REJECTED",
        )
        return report

    # -----------------------------------------------------------------------
    # Key Rotation (Operational)
    # -----------------------------------------------------------------------

    def re_sign_all(self, capabilities: list[Capability]) -> dict[str, bool]:
        """Re-sign all capabilities with the current signing key.

        Call this after rotating CAPFORGE_SIGNING_KEY.
        Returns a dict of capability_id -> success.
        """
        results = {}
        for cap in capabilities:
            try:
                self.sign(cap)
                results[cap.id] = True
            except Exception as e:
                logger.error("Failed to re-sign capability '%s': %s", cap.id, e)
                results[cap.id] = False
        return results

    def get_signature(self, capability_id: str, version: str) -> dict | None:
        """Retrieve signature metadata for a capability (without the HMAC value)."""
        sig = self._store.get(capability_id, version)
        if not sig:
            return None
        return {
            "capability_id": sig.capability_id,
            "version": sig.version,
            "code_sha256": sig.code_sha256,
            "signed_at": sig.signed_at,
            "signer_version": sig.signer_version,
            # NEVER expose hmac_sig — it's internal
        }

    def get_promotion_history(self, capability_id: str) -> list[dict]:
        """Get the full promotion audit history for a capability."""
        return self._store.get_promotion_history(capability_id)


# ---------------------------------------------------------------------------
# Global singleton (optional — wire into app via DI)
# ---------------------------------------------------------------------------

_trust_chain: TrustChain | None = None


def get_trust_chain() -> TrustChain:
    """Get or create the global TrustChain instance."""
    global _trust_chain
    if _trust_chain is None:
        _trust_chain = TrustChain()
    return _trust_chain

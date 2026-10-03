"""CapForge Enterprise Role-Based Access Control (RBAC) & API Key Mesh (v1.1.0).

Provides cryptographically hashed API key authentication, scoped role validation,
and tenant namespace authorization boundaries.

Keys are persisted in a dedicated SQLite table — auth state survives restarts
and is shared consistently within a single-node deployment.

SECURITY NOTES:
- Raw tokens are NEVER stored; only SHA-256 hashes.
- Dev mode bypass is explicitly opt-in via CAPFORGE_DEV_MODE=true (never default).
- In production, ensure CAPFORGE_DEV_MODE is unset or "false".
"""

from __future__ import annotations

import enum
import hashlib
import json
import logging
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field
from fastapi import Depends, Header, HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader

from capforge.core.config import settings

logger = logging.getLogger("capforge.auth")


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"
    AGENT_RUNNER = "AGENT_RUNNER"
    AUDITOR = "AUDITOR"


# Role hierarchy: higher index = more privilege
_ROLE_ORDER = [UserRole.AUDITOR, UserRole.AGENT_RUNNER, UserRole.OPERATOR, UserRole.ADMIN]


class APIKeyRecord(BaseModel):
    """Secure metadata record for a provisioned API key."""
    key_id: str
    key_hash: str
    name: str
    role: UserRole
    tenant_namespace: str = "default"  # "*" matches all namespaces
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    revoked: bool = False


# ---------------------------------------------------------------------------
# Persistent Auth Store — SQLite backend
# ---------------------------------------------------------------------------

class AuthStore:
    """SQLite-backed persistence for API key records."""

    def __init__(self, db_path: Optional[Path | str] = None):
        self.db_path = Path(db_path) if db_path else settings.auth_db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    key_id TEXT PRIMARY KEY,
                    key_hash TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    tenant_namespace TEXT NOT NULL DEFAULT 'default',
                    created_at TEXT NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_key_hash ON api_keys(key_hash);")
            conn.commit()

    def save(self, record: APIKeyRecord) -> None:
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO api_keys
                    (key_id, key_hash, name, role, tenant_namespace, created_at, revoked)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                record.key_id,
                record.key_hash,
                record.name,
                record.role.value,
                record.tenant_namespace,
                record.created_at,
                1 if record.revoked else 0,
            ))
            conn.commit()

    def get_by_hash(self, key_hash: str) -> Optional[APIKeyRecord]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM api_keys WHERE key_hash = ? AND revoked = 0", (key_hash,)
            ).fetchone()
        if not row:
            return None
        return self._row_to_record(row)

    def get_by_id(self, key_id: str) -> Optional[APIKeyRecord]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM api_keys WHERE key_id = ?", (key_id,)).fetchone()
        if not row:
            return None
        return self._row_to_record(row)

    def revoke(self, key_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE api_keys SET revoked = 1 WHERE key_id = ? AND revoked = 0", (key_id,)
            )
            conn.commit()
        return cur.rowcount > 0

    def list_all(self) -> List[APIKeyRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM api_keys ORDER BY created_at DESC").fetchall()
        return [self._row_to_record(r) for r in rows]

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> APIKeyRecord:
        return APIKeyRecord(
            key_id=row["key_id"],
            key_hash=row["key_hash"],
            name=row["name"],
            role=UserRole(row["role"]),
            tenant_namespace=row["tenant_namespace"],
            created_at=row["created_at"],
            revoked=bool(row["revoked"]),
        )


# ---------------------------------------------------------------------------
# Auth Manager
# ---------------------------------------------------------------------------

class AuthManager:
    """Manages generation, persistent storage, and validation of cryptographic API keys."""

    def __init__(self, store: Optional[AuthStore] = None):
        self._store = store or AuthStore()
        self._ensure_bootstrap_admin()

    def _hash_key(self, raw_key: str) -> str:
        return hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()

    def _ensure_bootstrap_admin(self) -> None:
        """Provision the root admin key on first startup if no admin keys exist."""
        all_keys = self._store.list_all()
        has_admin = any(k.role == UserRole.ADMIN and not k.revoked for k in all_keys)
        if not has_admin:
            # Check if bootstrap key is set via environment
            bootstrap_key = settings.__dict__.get("_bootstrap_admin_key") or "sf_live_master_admin_secret"
            existing = self._store.get_by_id("key_root_admin")
            if not existing:
                rec = APIKeyRecord(
                    key_id="key_root_admin",
                    key_hash=self._hash_key(bootstrap_key),
                    name="Platform Root Admin",
                    role=UserRole.ADMIN,
                    tenant_namespace="*",
                )
                self._store.save(rec)
                logger.warning(
                    "Bootstrap admin key provisioned (key_root_admin). "
                    "Rotate this key immediately in production via POST /v1/auth/keys."
                )

    def create_api_key(
        self,
        name: str,
        role: UserRole = UserRole.AGENT_RUNNER,
        tenant_namespace: str = "default",
    ) -> Tuple[str, APIKeyRecord]:
        """Generate a new secure API key and persist it. Returns (raw_token, record)."""
        raw_token = f"sf_live_{secrets.token_urlsafe(32)}"
        key_id = f"key_{secrets.token_hex(8)}"
        rec = APIKeyRecord(
            key_id=key_id,
            key_hash=self._hash_key(raw_token),
            name=name,
            role=role,
            tenant_namespace=tenant_namespace,
        )
        self._store.save(rec)
        logger.info(
            "API key created: id=%s name=%s role=%s namespace=%s",
            key_id, name, role.value, tenant_namespace,
        )
        return raw_token, rec

    def authenticate(self, raw_token: Optional[str]) -> Optional[APIKeyRecord]:
        """Validate raw token against stored SHA-256 hashes. Returns None if invalid/revoked."""
        if not raw_token:
            return None
        key_hash = self._hash_key(raw_token)
        return self._store.get_by_hash(key_hash)

    def revoke_key(self, key_id: str) -> bool:
        """Revoke an active API key by ID. Returns True if found and revoked."""
        revoked = self._store.revoke(key_id)
        if revoked:
            logger.warning("API key revoked: key_id=%s", key_id)
        return revoked

    def list_keys(self) -> List[APIKeyRecord]:
        return self._store.list_all()

    def authorize(
        self,
        record: APIKeyRecord,
        allowed_roles: List[UserRole],
        target_namespace: Optional[str] = None,
    ) -> bool:
        """Check role hierarchy and tenant namespace boundary.

        Always re-fetches revocation status from the persistent store to prevent
        stale in-memory records from bypassing revocation.
        """
        # Re-check revocation against the DB (prevents stale in-memory bypass)
        live = self._store.get_by_id(record.key_id)
        if not live or live.revoked:
            return False
        if live.role != UserRole.ADMIN and live.role not in allowed_roles:
            return False
        if target_namespace and live.tenant_namespace != "*":
            if live.tenant_namespace != target_namespace:
                return False
        return True


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

auth_manager = AuthManager()

API_KEY_HEADER = APIKeyHeader(name="X-CapForge-Key", auto_error=False)


def get_current_user_key(
    api_key: Optional[str] = Security(API_KEY_HEADER),
) -> APIKeyRecord:
    """FastAPI dependency: authenticate the incoming X-CapForge-Key header.

    In dev mode (CAPFORGE_DEV_MODE=true) a missing key falls back to the root admin.
    This MUST NOT be enabled in production.
    """
    if not api_key:
        if settings.dev_mode:
            admin = auth_manager._store.get_by_id("key_root_admin")
            if admin:
                logger.debug("Dev mode: unauthenticated request elevated to root admin.")
                return admin
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required X-CapForge-Key header. Provision a key via POST /v1/auth/keys.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    record = auth_manager.authenticate(api_key)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return record


def require_roles(*allowed_roles: UserRole):
    """Enforce specific roles on an API route. ADMIN is always allowed."""
    def role_checker(record: APIKeyRecord = Depends(get_current_user_key)) -> APIKeyRecord:
        if record.role != UserRole.ADMIN and record.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Permission denied: role '{record.role.value}' lacks required permissions. "
                    f"Required one of: {[r.value for r in allowed_roles]}"
                ),
            )
        return record
    return role_checker

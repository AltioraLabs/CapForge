"""SkillForge Capability Registry Storage Engine.

Provides persistent SQLite-backed storage for capabilities, version lineages,
verification audit histories, and active capability indexing.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timezone

from skillforge.core.models import Capability, CapabilityStatus, VerificationResult
from skillforge.core.exceptions import CapabilityNotFoundError
from skillforge.core.config import settings


class CapabilityRegistry:
    """Manages persistent capability lifecycle state and version history."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initialize database schema tables if not present."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS capabilities (
                    id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    description TEXT NOT NULL,
                    code_body TEXT NOT NULL,
                    entrypoint TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (id, version)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS verification_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    capability_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    tests_run INTEGER NOT NULL,
                    tests_passed INTEGER NOT NULL,
                    tests_failed INTEGER NOT NULL,
                    raw_json TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_cap_id ON capabilities(id);
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_cap_domain ON capabilities(domain);
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_cap_status ON capabilities(status);
            """)
            conn.commit()

    def register(self, capability: Capability) -> Capability:
        """Register or update a capability version in the registry."""
        capability.updated_at = datetime.now(timezone.utc)
        raw_json = capability.model_dump_json()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO capabilities (
                    id, version, name, status, domain, description,
                    code_body, entrypoint, raw_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                capability.id,
                capability.version,
                capability.name,
                capability.status.value,
                capability.domain,
                capability.description,
                capability.code_body,
                capability.entrypoint_function,
                raw_json,
                capability.created_at.isoformat(),
                capability.updated_at.isoformat()
            ))
            conn.commit()
        return capability

    def get(self, capability_id: str, version: Optional[str] = None) -> Optional[Capability]:
        """Retrieve a specific capability version, or the latest ACTIVE/available version."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if version:
                cursor.execute("""
                    SELECT raw_json FROM capabilities 
                    WHERE id = ? AND version = ?
                """, (capability_id, version))
            else:
                # Prefer ACTIVE status first, order by updated_at descending
                cursor.execute("""
                    SELECT raw_json FROM capabilities 
                    WHERE id = ?
                    ORDER BY CASE WHEN status = 'ACTIVE' THEN 0 ELSE 1 END,
                             updated_at DESC
                    LIMIT 1
                """, (capability_id,))

            row = cursor.fetchone()
            if not row:
                return None
            return Capability.model_validate_json(row["raw_json"])

    def list_capabilities(
        self,
        domain: Optional[str] = None,
        status: Optional[CapabilityStatus] = None
    ) -> List[Capability]:
        """List distinct active capabilities, optionally filtered by domain and status."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT raw_json FROM capabilities WHERE 1=1"
            params = []
            if domain:
                query += " AND domain = ?"
                params.append(domain)
            if status:
                query += " AND status = ?"
                params.append(status.value)
            
            # Fetch latest per ID
            query += """
                GROUP BY id HAVING updated_at = MAX(updated_at)
                ORDER BY domain, id
            """
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [Capability.model_validate_json(r["raw_json"]) for r in rows]

    def list_versions(self, capability_id: str) -> List[Capability]:
        """Retrieve all versions of a capability in descending chronological order."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT raw_json FROM capabilities 
                WHERE id = ? 
                ORDER BY updated_at DESC
            """, (capability_id,))
            rows = cursor.fetchall()
            return [Capability.model_validate_json(r["raw_json"]) for r in rows]

    def set_status(self, capability_id: str, version: str, status: CapabilityStatus) -> bool:
        """Update the lifecycle status of a specific capability version."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT raw_json FROM capabilities WHERE id = ? AND version = ?
            """, (capability_id, version))
            row = cursor.fetchone()
            if not row:
                return False
            
            cap = Capability.model_validate_json(row["raw_json"])
            cap.status = status
            cap.updated_at = datetime.now(timezone.utc)
            
            cursor.execute("""
                UPDATE capabilities 
                SET status = ?, updated_at = ?, raw_json = ?
                WHERE id = ? AND version = ?
            """, (status.value, cap.updated_at.isoformat(), cap.model_dump_json(), capability_id, version))
            conn.commit()
            return True

    def rollback(self, capability_id: str, target_version: str) -> Capability:
        """Promote an earlier version of a capability to ACTIVE status and deprecate newer ones."""
        target = self.get(capability_id, version=target_version)
        if not target:
            raise CapabilityNotFoundError(capability_id, target_version)
        
        # Demote current active versions
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE capabilities
                SET status = 'DEPRECATED'
                WHERE id = ? AND status = 'ACTIVE'
            """, (capability_id,))
            conn.commit()

        # Activate target version
        self.set_status(capability_id, target_version, CapabilityStatus.ACTIVE)
        target.status = CapabilityStatus.ACTIVE
        return target

    def record_verification(self, result: VerificationResult) -> None:
        """Log a verification test suite run for auditing and regression benchmarks."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO verification_history (
                    capability_id, version, passed, tests_run,
                    tests_passed, tests_failed, raw_json, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                result.capability_id,
                result.version,
                1 if result.passed else 0,
                result.tests_run,
                result.tests_passed,
                result.tests_failed,
                result.model_dump_json(),
                result.timestamp.isoformat()
            ))
            conn.commit()

    def get_verification_history(self, capability_id: str) -> List[VerificationResult]:
        """Fetch all historical verification run logs for a capability."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT raw_json FROM verification_history 
                WHERE capability_id = ? 
                ORDER BY timestamp DESC
            """, (capability_id,))
            rows = cursor.fetchall()
            return [VerificationResult.model_validate_json(r["raw_json"]) for r in rows]

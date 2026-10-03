"""CapForge PostgreSQL Registry Backend.

Production-grade distributed registry storage backed by PostgreSQL.
Supports concurrent multi-agent read/write access, full-text search
over capability metadata, and transactional promotion gates.

Features:
  - Connection pooling via asyncpg or psycopg pool
  - Transactional capability registration with conflict resolution
  - Full-text search over capability descriptions and tags
  - Version lineage queries with window functions
  - Automatic schema migration on startup
"""

from __future__ import annotations

import json
import logging
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("capforge.registry.postgres")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class PostgresConfig:
    """PostgreSQL connection configuration."""

    host: str = "localhost"
    port: int = 5432
    database: str = "capforge"
    user: str = "capforge"
    password: str = ""
    pool_min_size: int = 2
    pool_max_size: int = 10
    ssl_mode: str = "prefer"
    schema: str = "capforge"

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
            f"?sslmode={self.ssl_mode}"
        )


# ---------------------------------------------------------------------------
# Schema Migration
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS {schema};

CREATE TABLE IF NOT EXISTS {schema}.capabilities (
    id              TEXT NOT NULL,
    version         TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT DEFAULT '',
    domain          TEXT DEFAULT 'general',
    status          TEXT DEFAULT 'EXPERIMENTAL',
    risk_level      TEXT DEFAULT 'LOW',
    tags            JSONB DEFAULT '[]'::jsonb,
    features        JSONB DEFAULT '[]'::jsonb,
    inputs_schema   JSONB DEFAULT '{{}}'::jsonb,
    outputs_schema  JSONB DEFAULT '{{}}'::jsonb,
    code_body       TEXT DEFAULT '',
    code_sha256     TEXT DEFAULT '',
    entrypoint      TEXT DEFAULT 'execute',
    execution_mode  TEXT DEFAULT 'CODE',
    changelog       TEXT DEFAULT '',
    namespace       TEXT DEFAULT 'default',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, version)
);

CREATE TABLE IF NOT EXISTS {schema}.verification_history (
    id              SERIAL PRIMARY KEY,
    capability_id   TEXT NOT NULL,
    version         TEXT NOT NULL,
    tests_run       INTEGER DEFAULT 0,
    tests_passed    INTEGER DEFAULT 0,
    tests_failed    INTEGER DEFAULT 0,
    functional_score REAL DEFAULT 0.0,
    passed          BOOLEAN DEFAULT FALSE,
    diagnostics     TEXT DEFAULT '',
    regression_passed BOOLEAN DEFAULT TRUE,
    verified_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS {schema}.promotion_history (
    id              SERIAL PRIMARY KEY,
    capability_id   TEXT NOT NULL,
    version         TEXT NOT NULL,
    approved        BOOLEAN DEFAULT FALSE,
    reason          TEXT DEFAULT '',
    signature_valid BOOLEAN DEFAULT FALSE,
    quorum_runs     INTEGER DEFAULT 0,
    quorum_passed   INTEGER DEFAULT 0,
    promoted_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS {schema}.signatures (
    capability_id   TEXT NOT NULL,
    version         TEXT NOT NULL,
    code_sha256     TEXT NOT NULL,
    hmac_sig        TEXT NOT NULL,
    algorithm       TEXT DEFAULT 'hmac-sha256',
    signer_version  TEXT DEFAULT '1.0.0',
    signed_at       TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (capability_id, version)
);

-- Feature discovery index
CREATE INDEX IF NOT EXISTS idx_capabilities_features
    ON {schema}.capabilities USING gin(features);

-- Full-text search index
CREATE INDEX IF NOT EXISTS idx_capabilities_search
    ON {schema}.capabilities USING gin(
        to_tsvector('english', coalesce(name, '') || ' ' || coalesce(description, ''))
    );

-- Status filter index
CREATE INDEX IF NOT EXISTS idx_capabilities_status
    ON {schema}.capabilities (status);

-- Domain filter index
CREATE INDEX IF NOT EXISTS idx_capabilities_domain
    ON {schema}.capabilities (domain);
"""


class PostgresRegistryBackend:
    SCHEMA_SQL = SCHEMA_SQL
    _SCHEMA_SQL = SCHEMA_SQL
    """PostgreSQL-backed capability registry with connection pooling.

    Provides the same interface as the SQLite CapabilityRegistry but
    with production-grade distributed storage.
    """

    _SCHEMA_NAME_RE = None  # compiled lazily to keep import cost down

    def __init__(self, config: PostgresConfig | None = None):
        self.config = config or PostgresConfig()
        self._pool = None
        self._initialized = False
        self._validated_schema = self._validate_schema_name(self.config.schema)

    @staticmethod
    def _validate_schema_name(schema: str) -> str:
        """Allowlist SQL identifiers used for schema interpolation.

        Table/column names cannot be query parameters, so the schema name is
        validated once at construction. It is operator configuration today,
        but this guard keeps it safe if a tenant namespace ever maps here.
        """
        import re

        if not isinstance(schema, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
            raise ValueError(f"Refusing unsafe PostgreSQL schema name: {schema!r}")
        return schema

    @property
    def _schema(self) -> str:
        return self._validated_schema

    def initialize(self) -> None:
        """Create connection pool and run schema migrations."""
        try:
            import psycopg_pool

            self._pool = psycopg_pool.ConnectionPool(
                self.config.dsn,
                min_size=self.config.pool_min_size,
                max_size=self.config.pool_max_size,
            )
            self._run_migrations()
            self._initialized = True
            logger.info(
                "PostgreSQL registry initialized: %s:%d/%s (pool: %d-%d)",
                self.config.host,
                self.config.port,
                self.config.database,
                self.config.pool_min_size,
                self.config.pool_max_size,
            )
        except ImportError:
            logger.warning(
                "psycopg_pool not installed. Install via: pip install psycopg[pool]. "
                "Falling back to direct connections."
            )
            self._initialized = False

    @contextmanager
    def _get_conn(self) -> Generator:
        """Get a connection from the pool."""
        if self._pool:
            with self._pool.connection() as conn:
                yield conn
        else:
            import psycopg
            with psycopg.connect(self.config.dsn) as conn:
                yield conn

    def _run_migrations(self) -> None:
        """Execute schema DDL statements."""
        sql = SCHEMA_SQL.format(schema=self._schema)
        with self._get_conn() as conn:
            conn.execute(sql)
            conn.commit()
        logger.info("PostgreSQL schema migration complete for schema '%s'", self.config.schema)

    # -------------------------------------------------------------------
    # CRUD Operations
    # -------------------------------------------------------------------

    def register(self, capability_data: dict[str, Any]) -> None:
        """Register or upsert a capability."""
        sql = f"""
        INSERT INTO {self._schema}.capabilities
            (id, version, name, description, domain, status, risk_level,
             tags, features, inputs_schema, outputs_schema,
             code_body, code_sha256, entrypoint, execution_mode,
             changelog, namespace)
        VALUES
            (%(id)s, %(version)s, %(name)s, %(description)s, %(domain)s,
             %(status)s, %(risk_level)s, %(tags)s::jsonb, %(features)s::jsonb,
             %(inputs_schema)s::jsonb, %(outputs_schema)s::jsonb,
             %(code_body)s, %(code_sha256)s, %(entrypoint)s,
             %(execution_mode)s, %(changelog)s, %(namespace)s)
        ON CONFLICT (id, version) DO UPDATE SET
            name = EXCLUDED.name,
            description = EXCLUDED.description,
            status = EXCLUDED.status,
            risk_level = EXCLUDED.risk_level,
            tags = EXCLUDED.tags,
            features = EXCLUDED.features,
            inputs_schema = EXCLUDED.inputs_schema,
            outputs_schema = EXCLUDED.outputs_schema,
            code_body = EXCLUDED.code_body,
            code_sha256 = EXCLUDED.code_sha256,
            changelog = EXCLUDED.changelog,
            updated_at = NOW()
        """
        with self._get_conn() as conn:
            conn.execute(sql, capability_data)
            conn.commit()

    def get(self, capability_id: str, version: str | None = None) -> dict[str, Any] | None:
        """Get a capability by ID and optional version (latest ACTIVE if omitted)."""
        if version:
            sql = f"""
            SELECT * FROM {self._schema}.capabilities
            WHERE id = %s AND version = %s
            """
            params = (capability_id, version)
        else:
            sql = f"""
            SELECT * FROM {self._schema}.capabilities
            WHERE id = %s AND status = 'ACTIVE'
            ORDER BY created_at DESC LIMIT 1
            """
            params = (capability_id,)

        with self._get_conn() as conn:
            cur = conn.execute(sql, params)
            row = cur.fetchone()
            if row and cur.description:
                return dict(zip([d.name for d in cur.description], row))
        return None

    def get_capabilities_by_feature(self, feature: str) -> list[dict[str, Any]]:
        """Dynamic capability discovery by feature tag.

        This enables agents to query: 'give me all capabilities that support
        monte_carlo simulation' without hardcoding version numbers.
        """
        sql = f"""
        SELECT * FROM {self._schema}.capabilities
        WHERE features @> %s::jsonb AND status = 'ACTIVE'
        ORDER BY created_at DESC
        """
        with self._get_conn() as conn:
            cur = conn.execute(sql, (json.dumps([feature]),))
            rows = cur.fetchall()
            if rows and cur.description:
                cols = [d.name for d in cur.description]
                return [dict(zip(cols, row)) for row in rows]
        return []

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Full-text search across capability names and descriptions."""
        sql = f"""
        SELECT *, ts_rank(
            to_tsvector('english', coalesce(name, '') || ' ' || coalesce(description, '')),
            plainto_tsquery('english', %s)
        ) AS rank
        FROM {self._schema}.capabilities
        WHERE to_tsvector('english', coalesce(name, '') || ' ' || coalesce(description, ''))
              @@ plainto_tsquery('english', %s)
        ORDER BY rank DESC
        LIMIT %s
        """
        with self._get_conn() as conn:
            cur = conn.execute(sql, (query, query, limit))
            rows = cur.fetchall()
            if rows and cur.description:
                cols = [d.name for d in cur.description]
                return [dict(zip(cols, row)) for row in rows]
        return []

    def list_versions(self, capability_id: str) -> list[dict[str, Any]]:
        """Get full version lineage for a capability."""
        sql = f"""
        SELECT id, version, status, risk_level, created_at,
               LAG(version) OVER (ORDER BY created_at) AS previous_version
        FROM {self._schema}.capabilities
        WHERE id = %s
        ORDER BY created_at
        """
        with self._get_conn() as conn:
            cur = conn.execute(sql, (capability_id,))
            rows = cur.fetchall()
            if rows and cur.description:
                cols = [d.name for d in cur.description]
                return [dict(zip(cols, row)) for row in rows]
        return []

    def set_status(self, capability_id: str, version: str, status: str) -> None:
        """Update capability status (ACTIVE, DEPRECATED, QUARANTINED)."""
        sql = f"""
        UPDATE {self._schema}.capabilities
        SET status = %s, updated_at = NOW()
        WHERE id = %s AND version = %s
        """
        with self._get_conn() as conn:
            conn.execute(sql, (status, capability_id, version))
            conn.commit()

    def record_verification(self, verification_data: dict[str, Any]) -> None:
        """Record a verification result in the audit history."""
        sql = f"""
        INSERT INTO {self._schema}.verification_history
            (capability_id, version, tests_run, tests_passed, tests_failed,
             functional_score, passed, diagnostics, regression_passed)
        VALUES
            (%(capability_id)s, %(version)s, %(tests_run)s, %(tests_passed)s,
             %(tests_failed)s, %(functional_score)s, %(passed)s,
             %(diagnostics)s, %(regression_passed)s)
        """
        with self._get_conn() as conn:
            conn.execute(sql, verification_data)
            conn.commit()

    def close(self) -> None:
        """Close connection pool."""
        if self._pool:
            self._pool.close()
            logger.info("PostgreSQL connection pool closed")


# Alias for consistency
PostgresCapabilityRegistry = PostgresRegistryBackend

"""CapForge Global Configuration and Environment Settings.

All configuration is driven by environment variables with safe defaults.
For production, set all variables marked [PROD] via .env or container secrets.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field


class Settings(BaseModel):
    """CapForge configuration loaded from environment variables with sensible defaults."""

    # ---------------------------------------------------------------------------
    # Distributed Registry & Storage
    # ---------------------------------------------------------------------------
    registry_backend: str = os.environ.get("CAPFORGE_REGISTRY_BACKEND", "sqlite")  # sqlite | postgres
    postgres_url: str | None = os.environ.get("CAPFORGE_POSTGRES_URL")
    storage_backend: str = os.environ.get("CAPFORGE_STORAGE_BACKEND", "local")  # local | s3
    s3_bucket: str = os.environ.get("CAPFORGE_S3_BUCKET", "capforge-artifacts")
    s3_endpoint_url: str | None = os.environ.get("CAPFORGE_S3_ENDPOINT_URL")
    s3_region: str = os.environ.get("CAPFORGE_S3_REGION", "us-east-1")
    s3_access_key: str | None = os.environ.get("CAPFORGE_S3_ACCESS_KEY")
    s3_secret_key: str | None = os.environ.get("CAPFORGE_S3_SECRET_KEY")
    s3_prefix: str = os.environ.get("CAPFORGE_S3_PREFIX", "capabilities/")

    # ---------------------------------------------------------------------------
    # Sandbox & Execution Driver
    # ---------------------------------------------------------------------------
    sandbox_driver: str = os.environ.get("CAPFORGE_SANDBOX_DRIVER", "auto")  # auto | subprocess | docker | wasm | in_process

    # ---------------------------------------------------------------------------
    # Cryptographic Security
    # ---------------------------------------------------------------------------
    signing_algorithm: str = os.environ.get("CAPFORGE_SIGNING_ALGORITHM", "hmac")  # hmac | ed25519
    ed25519_private_key: str | None = os.environ.get("CAPFORGE_ED25519_PRIVATE_KEY")
    ed25519_public_key: str | None = os.environ.get("CAPFORGE_ED25519_PUBLIC_KEY")
    # Initial root admin key for FRESH installs only. If unset, a random key is
    # generated per fresh database and printed once to server logs. Set this in
    # production to a value from your secret manager (then rotate immediately).
    bootstrap_admin_key: str | None = os.environ.get("CAPFORGE_BOOTSTRAP_ADMIN_KEY")

    # ---------------------------------------------------------------------------
    # Telemetry & Observability
    # ---------------------------------------------------------------------------
    telemetry_enabled: bool = os.environ.get("CAPFORGE_TELEMETRY_ENABLED", "true").lower() == "true"
    otlp_endpoint: str | None = os.environ.get("CAPFORGE_OTLP_ENDPOINT")

    # ---------------------------------------------------------------------------
    # Base Paths
    # ---------------------------------------------------------------------------
    base_dir: Path = Field(default_factory=lambda: Path(os.environ.get("CAPFORGE_BASE_DIR", os.getcwd())))
    data_dir: Path = Field(
        default_factory=lambda: Path(os.environ.get("CAPFORGE_DATA_DIR", os.path.join(os.getcwd(), "data")))
    )
    db_path: Path = Field(
        default_factory=lambda: Path(
            os.environ.get("CAPFORGE_DB_PATH", os.path.join(os.getcwd(), "data", "capforge.db"))
        )
    )
    capabilities_dir: Path = Field(
        default_factory=lambda: Path(
            os.environ.get("CAPFORGE_CAPABILITIES_DIR", os.path.join(os.getcwd(), "capabilities"))
        )
    )

    # ---------------------------------------------------------------------------
    # Sandbox & Execution
    # ---------------------------------------------------------------------------
    sandbox_default_timeout_sec: float = float(os.environ.get("CAPFORGE_SANDBOX_TIMEOUT", "15.0"))
    sandbox_use_subprocess: bool = os.environ.get("CAPFORGE_SANDBOX_SUBPROCESS", "true").lower() == "true"
    max_repair_iterations: int = int(os.environ.get("CAPFORGE_MAX_REPAIR_ITERATIONS", "3"))
    require_full_regression_pass: bool = os.environ.get("CAPFORGE_REQUIRE_REGRESSION", "true").lower() == "true"

    # ---------------------------------------------------------------------------
    # Server
    # ---------------------------------------------------------------------------
    api_host: str = os.environ.get("CAPFORGE_API_HOST", "127.0.0.1")
    api_port: int = int(os.environ.get("CAPFORGE_API_PORT", "8000"))
    cors_origins: str = os.environ.get(
        "CAPFORGE_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    )
    webhook_allow_private_nets: bool = os.environ.get("CAPFORGE_WEBHOOK_ALLOW_PRIVATE", "false").lower() == "true"

    @property
    def cors_origins_list(self) -> list[str]:
        """Parsed CORS origin allowlist (never '*' together with credentials)."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def cors_allow_credentials(self) -> bool:
        """Credentials only when origins are explicitly pinned (never with '*')."""
        origins = self.cors_origins_list
        return bool(origins) and "*" not in origins

    # ---------------------------------------------------------------------------
    # [PROD] LLM Synthesis — Gemini API
    # Set CAPFORGE_LLM_PROVIDER=gemini and GEMINI_API_KEY for real code generation.
    # Falls back to template synthesis when not configured.
    # ---------------------------------------------------------------------------
    llm_provider: str = os.environ.get("CAPFORGE_LLM_PROVIDER", "template")  # gemini | openai | template
    gemini_api_key: str | None = os.environ.get("GEMINI_API_KEY")
    openai_api_key: str | None = os.environ.get("OPENAI_API_KEY")
    llm_model: str = os.environ.get("CAPFORGE_LLM_MODEL", "gemini-1.5-flash")
    llm_synthesis_temperature: float = float(os.environ.get("CAPFORGE_LLM_TEMPERATURE", "0.2"))
    llm_max_output_tokens: int = int(os.environ.get("CAPFORGE_LLM_MAX_TOKENS", "4096"))

    # ---------------------------------------------------------------------------
    # [PROD] Redis — Real broker, caching, rate limit state
    # Set CAPFORGE_REDIS_URL for distributed event streaming and rate limiting.
    # Falls back to in-memory when not configured.
    # ---------------------------------------------------------------------------
    redis_url: str | None = os.environ.get("CAPFORGE_REDIS_URL")  # e.g. redis://:password@host:6379/0
    redis_max_connections: int = int(os.environ.get("CAPFORGE_REDIS_MAX_CONNECTIONS", "20"))

    # ---------------------------------------------------------------------------
    # [PROD] Auth
    # In dev mode (CAPFORGE_DEV_MODE=true) unauthenticated requests are tolerated.
    # NEVER set dev mode in production.
    # ---------------------------------------------------------------------------
    dev_mode: bool = os.environ.get("CAPFORGE_DEV_MODE", "false").lower() == "true"
    auth_db_path: Path = Field(
        default_factory=lambda: Path(
            os.environ.get("CAPFORGE_AUTH_DB_PATH", os.path.join(os.getcwd(), "data", "capforge_auth.db"))
        )
    )

    # ---------------------------------------------------------------------------
    # Rate Limiting
    # ---------------------------------------------------------------------------
    rate_limit_default: str = os.environ.get("CAPFORGE_RATE_LIMIT_DEFAULT", "100/minute")
    rate_limit_synthesis: str = os.environ.get("CAPFORGE_RATE_LIMIT_SYNTHESIS", "10/minute")
    rate_limit_execute: str = os.environ.get("CAPFORGE_RATE_LIMIT_EXECUTE", "60/minute")

    # ---------------------------------------------------------------------------
    # Governance
    # ---------------------------------------------------------------------------
    max_auto_promote_risk: str = os.environ.get("CAPFORGE_MAX_AUTO_PROMOTE_RISK", "LOW")

    # ---------------------------------------------------------------------------
    # Logging
    # ---------------------------------------------------------------------------
    log_level: str = os.environ.get("CAPFORGE_LOG_LEVEL", "INFO")
    log_json: bool = os.environ.get("CAPFORGE_LOG_JSON", "false").lower() == "true"

    def ensure_directories(self) -> None:
        """Create necessary directories if they do not exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.capabilities_dir.mkdir(parents=True, exist_ok=True)

    @property
    def effective_llm_provider(self) -> str:
        """Determines active synthesis provider, auto-detecting available keys if unconfigured."""
        explicit = os.environ.get("CAPFORGE_LLM_PROVIDER")
        if explicit:
            return explicit
        if self.llm_provider == "ollama":
            return "ollama"
        if self.gemini_api_key:
            return "gemini"
        if self.openai_api_key:
            return "openai"
        return self.llm_provider

    @property
    def llm_configured(self) -> bool:
        """True if a real remote LLM provider is configured with credentials."""
        provider = self.effective_llm_provider
        if provider == "ollama":
            return True
        if provider == "gemini":
            return bool(self.gemini_api_key)
        if provider == "openai":
            return bool(self.openai_api_key)
        return False

    @property
    def redis_configured(self) -> bool:
        """True if Redis URL is set."""
        return bool(self.redis_url)


def setup_logging(level: str | None = None) -> None:
    """Configure structured logging for CapForge."""
    log_level = level or settings.log_level
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


# Singleton settings instance
settings = Settings()
settings.ensure_directories()

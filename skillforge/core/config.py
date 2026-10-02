"""SkillForge Global Configuration and Environment Settings."""

import os
from pathlib import Path
from pydantic import BaseModel, Field


class Settings(BaseModel):
    # Base paths
    base_dir: Path = Field(default_factory=lambda: Path(os.getcwd()))
    data_dir: Path = Field(default_factory=lambda: Path(os.getcwd()) / "data")
    db_path: Path = Field(default_factory=lambda: Path(os.getcwd()) / "data" / "skillforge.db")
    capabilities_dir: Path = Field(default_factory=lambda: Path(os.getcwd()) / "capabilities")

    # Sandbox & Execution
    sandbox_default_timeout_sec: float = 15.0
    max_repair_iterations: int = 3
    require_full_regression_pass: bool = True

    # Server settings
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    def ensure_directories(self) -> None:
        """Create necessary directories if they do not exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.capabilities_dir.mkdir(parents=True, exist_ok=True)


# Singleton settings instance
settings = Settings()
settings.ensure_directories()

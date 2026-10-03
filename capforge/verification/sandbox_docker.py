"""CapForge Containerized Docker Sandbox Isolation Runner (discussion.mdx §14, §50).

Provides hardware-constrained, network-isolated container execution for unverified
or high-risk capabilities, with automatic fallback to isolated subprocess execution.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from typing import Any, Dict, Optional

from capforge.verification.sandbox import SandboxRunner

logger = logging.getLogger("capforge.verification.docker")


class DockerSandboxRunner(SandboxRunner):
    """Containerized sandbox executing capabilities inside isolated Docker containers."""

    def __init__(
        self,
        docker_image: str = "python:3.11-alpine",
        memory_limit: str = "256m",
        cpu_quota: float = 1.0,
        network_mode: str = "none",
        force_subprocess_fallback: bool = False,
    ):
        super().__init__()
        self.docker_image = docker_image
        self.memory_limit = memory_limit
        self.cpu_quota = cpu_quota
        self.network_mode = network_mode
        self.force_subprocess_fallback = force_subprocess_fallback
        self._docker_available = self._check_docker()

    def _check_docker(self) -> bool:
        if self.force_subprocess_fallback:
            return False
        if not shutil.which("docker"):
            return False
        try:
            res = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=2.0,
            )
            return res.returncode == 0
        except Exception:
            return False

    def is_docker_enabled(self) -> bool:
        return self._docker_available

    def execute_code(
        self,
        code_body: str,
        entrypoint: str,
        inputs: Dict[str, Any],
        timeout_sec: float = 10.0,
    ) -> Dict[str, Any]:
        """Execute code in Docker container if available, otherwise fallback to subprocess sandbox."""
        if not self._docker_available:
            logger.debug("Docker daemon unavailable. Using subprocess sandbox runner.")
            return super().execute_code(code_body, entrypoint, inputs, timeout_sec=timeout_sec)

        start = time.perf_counter()
        runner_script = self._build_runner_script(code_body, entrypoint, inputs)

        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "-i",
            f"--memory={self.memory_limit}",
            f"--cpus={self.cpu_quota}",
            f"--network={self.network_mode}",
            self.docker_image,
            "python",
            "-c",
            runner_script,
        ]

        try:
            proc = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                env=self._build_sanitized_env(),
            )
            elapsed = (time.perf_counter() - start) * 1000.0

            if proc.returncode != 0:
                return {
                    "success": False,
                    "output": None,
                    "error": proc.stderr.strip() or f"Process failed with exit code {proc.returncode}",
                    "execution_time_ms": round(elapsed, 2),
                }

            stdout_clean = proc.stdout.strip()
            if not stdout_clean:
                return {
                    "success": False,
                    "output": None,
                    "error": "No output produced from container execution",
                    "execution_time_ms": round(elapsed, 2),
                }

            data = json.loads(stdout_clean)
            return {
                "success": data.get("status") == "SUCCESS",
                "output": data.get("result"),
                "error": data.get("error"),
                "execution_time_ms": round(elapsed, 2),
            }

        except subprocess.TimeoutExpired:
            elapsed = (time.perf_counter() - start) * 1000.0
            return {
                "success": False,
                "output": None,
                "error": f"Container execution timed out after {timeout_sec}s",
                "execution_time_ms": round(elapsed, 2),
            }
        except Exception as e:
            logger.warning(f"Docker execution failed with {e}. Falling back to subprocess sandbox.")
            return super().execute_code(code_body, entrypoint, inputs, timeout_sec=timeout_sec)

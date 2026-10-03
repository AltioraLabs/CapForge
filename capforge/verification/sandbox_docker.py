"""CapForge Containerized Docker Sandbox Isolation Runner (discussion.mdx §14, §50).

Provides hardware-constrained, network-isolated container execution for unverified
or high-risk capabilities, with automatic fallback to isolated subprocess execution.
"""

from __future__ import annotations

import functools
import json
import logging
import shutil
import subprocess
import textwrap
import time
from typing import Any

from capforge.verification.sandbox import ProcessSandboxDriver, SandboxRunner

logger = logging.getLogger("capforge.verification.docker")


@functools.lru_cache(maxsize=1)
def docker_available() -> bool:
    """Cached Docker daemon probe (avoids a ~2s `docker info` on every call)."""
    if not shutil.which("docker"):
        return False
    try:
        res = subprocess.run(["docker", "info"], capture_output=True, timeout=2.0)
        return res.returncode == 0
    except Exception:
        return False


class DockerSandboxRunner(SandboxRunner):
    """Containerized sandbox executing capabilities inside isolated Docker containers."""

    def __init__(
        self,
        docker_image: str = "python:3.11-alpine",
        memory_limit: str = "256m",
        cpu_quota: float = 1.0,
        network_mode: str = "none",
        force_subprocess_fallback: bool = False,
        python_executable: str | None = None,
        **kwargs: Any,
    ):
        fallback_driver = ProcessSandboxDriver(python_executable=python_executable)
        super().__init__(driver=fallback_driver, python_executable=python_executable)
        self.docker_image = docker_image
        self.memory_limit = memory_limit
        self.cpu_quota = cpu_quota
        self.network_mode = network_mode
        self.force_subprocess_fallback = force_subprocess_fallback
        self._docker_available = self._check_docker()

    def _check_docker(self) -> bool:
        if self.force_subprocess_fallback:
            return False
        return docker_available()

    def is_docker_enabled(self) -> bool:
        return self._docker_available

    @staticmethod
    def _build_sanitized_env() -> dict[str, str]:
        return ProcessSandboxDriver._build_sanitized_env()

    @staticmethod
    def _build_runner_script(code_body: str, entrypoint: str, inputs: dict[str, Any]) -> str:
        return textwrap.dedent(f"""\
            import json
            import sys
            import traceback

            try:
                exec_globals = {{"__builtins__": __builtins__}}
                code_body = {code_body!r}
                compiled = compile(code_body, "<docker_sandbox>", "exec")
                exec(compiled, exec_globals)

                fn = exec_globals.get({entrypoint!r})
                if not fn or not callable(fn):
                    print(json.dumps({{
                        "status": "ERROR",
                        "success": False,
                        "result": None,
                        "output": None,
                        "error": "Entrypoint function '{entrypoint}' not found or not callable",
                        "traceback": None,
                    }}))
                    sys.exit(0)

                inputs_data = {inputs!r}
                try:
                    result = fn(**inputs_data) if isinstance(inputs_data, dict) else fn(inputs_data)
                except TypeError:
                    result = fn(inputs_data)
                print(json.dumps({{
                    "status": "SUCCESS",
                    "success": True,
                    "result": result,
                    "output": result,
                    "error": None,
                    "traceback": None,
                }}, default=str))
            except Exception as e:
                print(json.dumps({{
                    "status": "ERROR",
                    "success": False,
                    "result": None,
                    "output": None,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                }}))
        """)

    def execute_code(
        self,
        code_body: str,
        entrypoint: str,
        inputs: dict[str, Any],
        timeout_sec: float | None = 10.0,
        env_overrides: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute code in Docker container if available, otherwise fallback to subprocess sandbox."""
        timeout = timeout_sec or 10.0
        if not self._docker_available:
            logger.debug("Docker daemon unavailable. Using subprocess sandbox runner.")
            return super().execute_code(
                code_body, entrypoint, inputs, timeout_sec=timeout, env_overrides=env_overrides
            )

        start = time.perf_counter()
        runner_script = self._build_runner_script(code_body, entrypoint, inputs)

        env_args: list[str] = []
        if env_overrides:
            for k, v in env_overrides.items():
                env_args.extend(["-e", f"{k}={v}"])

        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "-i",
            *env_args,
            f"--memory={self.memory_limit}",
            f"--cpus={self.cpu_quota}",
            "--pids-limit=64",
            f"--network={self.network_mode}",
            self.docker_image,
            "python",
            "-c",
            runner_script,
        ]

        env = self._build_sanitized_env()
        if env_overrides:
            env.update(env_overrides)

        try:
            proc = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            elapsed = (time.perf_counter() - start) * 1000.0

            if proc.returncode != 0:
                return {
                    "success": False,
                    "output": None,
                    "error": proc.stderr.strip() or f"Process failed with exit code {proc.returncode}",
                    "traceback": proc.stderr.strip() or None,
                    "execution_time_ms": round(elapsed, 2),
                }

            stdout_clean = proc.stdout.strip()
            if not stdout_clean:
                return {
                    "success": False,
                    "output": None,
                    "error": "No output produced from container execution",
                    "traceback": None,
                    "execution_time_ms": round(elapsed, 2),
                }

            data = json.loads(stdout_clean)
            return {
                "success": data.get("status") == "SUCCESS" or data.get("success") is True,
                "output": data.get("result") if "result" in data else data.get("output"),
                "error": data.get("error"),
                "traceback": data.get("traceback"),
                "execution_time_ms": round(elapsed, 2),
            }

        except subprocess.TimeoutExpired:
            elapsed = (time.perf_counter() - start) * 1000.0
            return {
                "success": False,
                "output": None,
                "error": f"Container execution timed out after {timeout}s",
                "traceback": None,
                "execution_time_ms": round(elapsed, 2),
            }
        except Exception as e:
            logger.warning("Docker execution failed with %s. Falling back to subprocess sandbox.", e)
            return super().execute_code(
                code_body, entrypoint, inputs, timeout_sec=timeout, env_overrides=env_overrides
            )

"""CapForge Sandbox Execution Engine.

Executes capability code within a bounded, isolated execution context.
Supports pluggable execution drivers:
  - SubprocessSandboxDriver (default process-level isolation)
  - DockerSandboxDriver (hardware-constrained OCI container isolation)
  - WasmSandboxDriver (browser/edge WebAssembly Pyodide isolation)
  - InProcessSandboxDriver (development/testing only)

Enforces execution timeouts, intercepts exceptions, and captures execution metrics.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import traceback
from typing import Any, Protocol, runtime_checkable

from capforge.core.telemetry import GenAISemanticConventions, trace_manager

logger = logging.getLogger("capforge.sandbox")


# ---------------------------------------------------------------------------
# Sandbox Driver Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class SandboxDriver(Protocol):
    """Protocol for pluggable sandbox execution drivers."""

    def execute_code(
        self,
        code_body: str,
        entrypoint: str,
        inputs: dict[str, Any],
        timeout_sec: float | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Execute code within the driver isolation domain."""
        ...


# ---------------------------------------------------------------------------
# Concrete Drivers
# ---------------------------------------------------------------------------


class InProcessSandboxDriver:
    """Fast in-process exec runner for development and internal testing."""

    def execute_code(
        self,
        code_body: str,
        entrypoint: str,
        inputs: dict[str, Any],
        timeout_sec: float | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        start = time.perf_counter()
        exec_globals: dict[str, Any] = {"__builtins__": __builtins__}
        try:
            compiled = compile(code_body, "<capforge_inprocess>", "exec")
            exec(compiled, exec_globals)
            fn = exec_globals.get(entrypoint)
            if not fn or not callable(fn):
                return {
                    "success": False,
                    "output": None,
                    "error": f"Entrypoint '{entrypoint}' not found or not callable",
                    "traceback": None,
                    "execution_time_ms": round((time.perf_counter() - start) * 1000, 2),
                }
            try:
                res = fn(**inputs) if isinstance(inputs, dict) else fn(inputs)
            except TypeError:
                res = fn(inputs)
            return {
                "success": True,
                "output": res,
                "error": None,
                "traceback": None,
                "execution_time_ms": round((time.perf_counter() - start) * 1000, 2),
            }
        except Exception as e:
            return {
                "success": False,
                "output": None,
                "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc(),
                "execution_time_ms": round((time.perf_counter() - start) * 1000, 2),
            }


def _sandbox_rlimits() -> None:
    """Apply POSIX resource caps to a sandboxed child process (preexec_fn).

    Bounds address space (~1 GiB) and CPU time so a runaway capability fails
    fast instead of OOM-ing the host.
    """
    import resource as _resource

    _resource.setrlimit(_resource.RLIMIT_AS, (1 << 30, 1 << 30))
    _resource.setrlimit(_resource.RLIMIT_CPU, (30, 30))


def _posix_rlimits_supported() -> bool:
    """True on platforms with the resource module (POSIX); False on Windows
    (where the execution timeout remains the only bound — prefer Docker)."""
    import importlib.util

    return importlib.util.find_spec("resource") is not None


_HAS_POSIX_RLIMITS = _posix_rlimits_supported()


class ProcessSandboxDriver:
    """Subprocess-based isolation runner with sanitized environment and timeout."""

    def __init__(self, python_executable: str | None = None):
        self.python_executable = python_executable or sys.executable

    @staticmethod
    def _build_sanitized_env() -> dict[str, str]:
        sensitive_patterns = ("KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL", "AUTH", "PRIVATE")
        safe_keys = {
            "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "APPDATA", "LOCALAPPDATA",
            "PYTHONPATH", "PYTHONHOME", "LANG", "LC_ALL", "USERPROFILE", "HOMEPATH",
            "HOMEDRIVE", "COMSPEC", "PATHEXT",
        }
        clean_env = {"PYTHONDONTWRITEBYTECODE": "1"}
        for k, v in os.environ.items():
            k_upper = k.upper()
            if any(p in k_upper for p in sensitive_patterns):
                continue
            if k_upper in safe_keys:
                clean_env[k] = v
        return clean_env

    def execute_code(
        self,
        code_body: str,
        entrypoint: str,
        inputs: dict[str, Any],
        timeout_sec: float | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        timeout = timeout_sec or 30.0
        start_time = time.perf_counter()

        runner_script = textwrap.dedent(f"""\
            import json
            import sys
            import traceback

            inputs_json = sys.stdin.read()
            inputs = json.loads(inputs_json)

            try:
                exec_globals = {{"__builtins__": __builtins__}}
                code_body = {code_body!r}
                compiled = compile(code_body, "<capforge_sandbox>", "exec")
                exec(compiled, exec_globals)

                entrypoint = exec_globals.get({entrypoint!r})
                if not entrypoint or not callable(entrypoint):
                    print(json.dumps({{
                        "success": False,
                        "output": None,
                        "error": "Entrypoint function '{entrypoint}' not found or not callable",
                        "traceback": None,
                    }}))
                    sys.exit(0)

                try:
                    result = entrypoint(**inputs) if isinstance(inputs, dict) else entrypoint(inputs)
                except TypeError:
                    result = entrypoint(inputs)
                print(json.dumps({{
                    "success": True,
                    "output": result,
                    "error": None,
                    "traceback": None,
                }}, default=str))
            except Exception as e:
                print(json.dumps({{
                    "success": False,
                    "output": None,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                }}))
        """)

        env = self._build_sanitized_env()
        if env_overrides:
            env.update(env_overrides)

        tmp_script = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
                f.write(runner_script)
                tmp_script = f.name

            proc = subprocess.Popen(
                [self.python_executable, tmp_script],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
                encoding="utf-8",
                preexec_fn=_sandbox_rlimits if _HAS_POSIX_RLIMITS else None,
            )

            try:
                stdout, stderr = proc.communicate(
                    input=json.dumps(inputs, default=str),
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                return {
                    "success": False,
                    "output": None,
                    "error": f"Execution timed out after {timeout} seconds",
                    "execution_time_ms": elapsed_ms,
                    "traceback": None,
                }

            elapsed_ms = (time.perf_counter() - start_time) * 1000

            if proc.returncode != 0 and not stdout.strip():
                return {
                    "success": False,
                    "output": None,
                    "error": f"Subprocess exited with code {proc.returncode}: {stderr.strip()}",
                    "execution_time_ms": elapsed_ms,
                    "traceback": stderr.strip() if stderr.strip() else None,
                }

            try:
                result = json.loads(stdout.strip())
                result["execution_time_ms"] = elapsed_ms
                return result
            except json.JSONDecodeError:
                return {
                    "success": False,
                    "output": None,
                    "error": f"Failed to parse subprocess output: {stdout[:200]}",
                    "execution_time_ms": elapsed_ms,
                    "traceback": stderr.strip() if stderr.strip() else None,
                }
        finally:
            if tmp_script and os.path.exists(tmp_script):
                try:
                    os.unlink(tmp_script)
                except OSError:
                    pass


class DockerSandboxDriver:
    """Hardware-isolated OCI container driver."""

    def __init__(self, **kwargs: Any):
        from capforge.verification.sandbox_docker import DockerSandboxRunner
        self._runner = DockerSandboxRunner(**kwargs)

    def execute_code(
        self,
        code_body: str,
        entrypoint: str,
        inputs: dict[str, Any],
        timeout_sec: float | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._runner.execute_code(
            code_body,
            entrypoint,
            inputs,
            timeout_sec=timeout_sec or 15.0,
        )


class WasmSandboxDriver:
    """WASM / Pyodide browser-compatible driver."""

    def __init__(self, **kwargs: Any):
        from capforge.verification.sandbox_wasm import WasmSandboxRunner
        self._runner = WasmSandboxRunner(**kwargs)

    def execute_code(
        self,
        code_body: str,
        entrypoint: str,
        inputs: dict[str, Any],
        timeout_sec: float | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._runner.execute_code(
            code_body,
            entrypoint,
            inputs,
            timeout_sec=timeout_sec or 15.0,
        )


# ---------------------------------------------------------------------------
# Driver Factory and Unified Runner
# ---------------------------------------------------------------------------


def get_sandbox_driver(name: str = "auto", **kwargs: Any) -> SandboxDriver:
    """Factory to retrieve requested sandbox execution driver.

    "auto" (the default) selects the strongest available isolation: Docker
    when the daemon is reachable, otherwise the hardened subprocess driver.
    The Docker probe is cached, so auto-resolution costs nothing per call.
    """
    normalized = name.lower().strip()
    if normalized == "auto":
        from capforge.verification.sandbox_docker import docker_available

        normalized = "docker" if docker_available() else "subprocess"
    if normalized in ("subprocess", "process"):
        return ProcessSandboxDriver(**kwargs)
    elif normalized in ("docker", "container"):
        return DockerSandboxDriver(**kwargs)
    elif normalized in ("wasm", "pyodide"):
        return WasmSandboxDriver(**kwargs)
    elif normalized in ("in_process", "inprocess", "direct"):
        return InProcessSandboxDriver()
    else:
        logger.warning("Unknown sandbox driver '%s', falling back to subprocess", name)
        return ProcessSandboxDriver(**kwargs)


class SandboxRunner:
    """Unified sandbox execution runner maintaining backwards compatibility."""

    def __init__(
        self,
        default_timeout_sec: float = 30.0,
        python_executable: str | None = None,
        use_subprocess: bool = True,
        driver: SandboxDriver | str | None = None,
    ) -> None:
        self.default_timeout_sec = default_timeout_sec
        self.python_executable = python_executable or sys.executable
        self.use_subprocess = use_subprocess

        if isinstance(driver, SandboxDriver):
            self.driver: SandboxDriver = driver
        elif isinstance(driver, str):
            self.driver = get_sandbox_driver(driver, python_executable=self.python_executable)
        elif not use_subprocess:
            self.driver = InProcessSandboxDriver()
        else:
            from capforge.core.config import settings

            self.driver = get_sandbox_driver(
                settings.sandbox_driver, python_executable=self.python_executable
            )

    def execute_code(
        self,
        code_body: str,
        entrypoint: str,
        inputs: dict[str, Any],
        timeout_sec: float | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        timeout = timeout_sec or self.default_timeout_sec
        with trace_manager.start_span("capforge.sandbox.execute") as span:
            span.set_attribute(GenAISemanticConventions.SANDBOX_DRIVER, type(self.driver).__name__)
            res = self.driver.execute_code(
                code_body=code_body,
                entrypoint=entrypoint,
                inputs=inputs,
                timeout_sec=timeout,
                env_overrides=env_overrides,
            )
            span.set_attribute("success", res.get("success", False))
            return res

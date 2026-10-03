"""CapForge Sandbox Execution Engine.

Executes capability code within a bounded, safe execution context.
Provides two execution modes:
  1. ProcessSandbox (default) — subprocess-based isolation with timeout
  2. InProcessSandbox — exec-based for testing/development only

Enforces execution timeouts, intercepts exceptions, and captures execution metrics.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

from capforge.core.exceptions import SandboxExecutionError


class SandboxRunner:
    """Safely executes capability code in a subprocess with timeout enforcement.

    This replaces the previous in-process exec() approach with proper
    process isolation to prevent untrusted code from corrupting the host.
    """

    def __init__(
        self,
        default_timeout_sec: float = 15.0,
        python_executable: Optional[str] = None,
        use_subprocess: bool = True,
    ) -> None:
        self.default_timeout_sec = default_timeout_sec
        self.python_executable = python_executable or sys.executable
        self.use_subprocess = use_subprocess

    @staticmethod
    def _build_sanitized_env() -> Dict[str, str]:
        """Filter out sensitive credentials and tokens from sandbox subprocess environment."""
        sensitive_patterns = ("KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL", "AUTH", "PRIVATE")
        safe_keys = {
            "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PYTHONPATH", "PYTHONHOME",
            "LANG", "LC_ALL", "USERPROFILE", "HOMEPATH", "HOMEDRIVE", "COMSPEC", "PATHEXT",
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
        inputs: Dict[str, Any],
        timeout_sec: Optional[float] = None,
        env_overrides: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Execute code in an isolated context and return output and execution time.

        Args:
            env_overrides: Optional key-value pairs merged into the sandbox env.
                Used by AdversarialTester to inject test/prod environment markers.
        """
        if self.use_subprocess:
            return self._execute_subprocess(code_body, entrypoint, inputs, timeout_sec, env_overrides)
        else:
            return self._execute_in_process(code_body, entrypoint, inputs, timeout_sec)

    def _execute_subprocess(
        self,
        code_body: str,
        entrypoint: str,
        inputs: Dict[str, Any],
        timeout_sec: Optional[float] = None,
        env_overrides: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Execute code in a subprocess for isolation."""
        timeout = timeout_sec or self.default_timeout_sec
        start_time = time.perf_counter()

        # Build the runner script
        runner_script = textwrap.dedent(f"""\
            import json
            import sys
            import traceback

            # Read inputs from stdin
            inputs_json = sys.stdin.read()
            inputs = json.loads(inputs_json)

            # Execute the capability code
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
                }}))
            except Exception as e:
                print(json.dumps({{
                    "success": False,
                    "output": None,
                    "error": f"{{type(e).__name__}}: {{str(e)}}",
                    "traceback": traceback.format_exc(),
                }}))
        """)

        try:
            # Write runner to temp file
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".py",
                delete=False,
                prefix="sf_sandbox_",
            ) as f:
                f.write(runner_script)
                runner_path = f.name

            try:
                sandbox_env = self._build_sanitized_env()
                # Apply env_overrides AFTER sanitization (used for adversarial blindness testing)
                if env_overrides:
                    sandbox_env.update(env_overrides)
                process = subprocess.run(
                    [self.python_executable, runner_path],
                    input=json.dumps(inputs),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env=sandbox_env,
                )

                elapsed_ms = (time.perf_counter() - start_time) * 1000.0

                if process.returncode != 0 and not process.stdout.strip():
                    return {
                        "success": False,
                        "output": None,
                        "error": f"Process exited with code {process.returncode}: {process.stderr[:500]}",
                        "traceback": process.stderr,
                        "execution_time_ms": round(elapsed_ms, 2),
                    }

                # Parse JSON output
                try:
                    result = json.loads(process.stdout)
                    result["execution_time_ms"] = round(elapsed_ms, 2)
                    return result
                except json.JSONDecodeError:
                    return {
                        "success": False,
                        "output": None,
                        "error": f"Invalid JSON output from sandbox: {process.stdout[:300]}",
                        "traceback": process.stderr,
                        "execution_time_ms": round(elapsed_ms, 2),
                    }

            except subprocess.TimeoutExpired:
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                return {
                    "success": False,
                    "output": None,
                    "error": f"Execution timed out after {timeout}s",
                    "traceback": None,
                    "execution_time_ms": round(elapsed_ms, 2),
                }
            finally:
                # Cleanup temp file
                try:
                    os.unlink(runner_path)
                except OSError:
                    pass

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return {
                "success": False,
                "output": None,
                "error": f"Sandbox setup error: {type(e).__name__}: {str(e)}",
                "traceback": traceback.format_exc(),
                "execution_time_ms": round(elapsed_ms, 2),
            }

    def _execute_in_process(
        self,
        code_body: str,
        entrypoint: str,
        inputs: Dict[str, Any],
        timeout_sec: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Execute code in an isolated dictionary namespace (development/test mode).

        WARNING: This does NOT provide security isolation. Use subprocess mode
        for any untrusted code.
        """
        timeout = timeout_sec or self.default_timeout_sec
        start_time = time.perf_counter()

        scope: Dict[str, Any] = {
            "__builtins__": __builtins__,
            "inputs": inputs,
        }

        try:
            compiled_code = compile(code_body, filename="<capforge_sandbox>", mode="exec")
            exec(compiled_code, scope)

            target_fn = scope.get(entrypoint)
            if not target_fn or not callable(target_fn):
                raise SandboxExecutionError(
                    f"Entrypoint function '{entrypoint}' not defined or not callable in candidate capability code."
                )

            try:
                result = target_fn(**inputs) if isinstance(inputs, dict) else target_fn(inputs)
            except TypeError:
                result = target_fn(inputs)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

            return {
                "success": True,
                "output": result,
                "error": None,
                "traceback": None,
                "execution_time_ms": round(elapsed_ms, 2),
            }

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            tb_str = traceback.format_exc()
            return {
                "success": False,
                "output": None,
                "error": f"{type(e).__name__}: {str(e)}",
                "traceback": tb_str,
                "execution_time_ms": round(elapsed_ms, 2),
            }

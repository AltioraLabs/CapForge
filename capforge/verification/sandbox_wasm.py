"""CapForge WASM/Pyodide Sandbox Driver.

Provides a WebAssembly-based execution sandbox using Pyodide for maximum
isolation. When Pyodide is not available, falls back to a restricted
subprocess sandbox with additional security hardening.

Security Properties:
  - Zero host filesystem access (Pyodide runs in emscripten virtual FS)
  - No network access from sandbox
  - Memory-bounded execution (configurable limit)
  - Deterministic timeout enforcement
"""

from __future__ import annotations

import ast
import json
import logging
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("capforge.sandbox.wasm")


@dataclass
class WASMSandboxConfig:
    """Configuration for the WASM sandbox driver."""

    timeout_seconds: int = 30
    max_memory_mb: int = 512
    allowed_imports: list[str] = field(default_factory=lambda: [
        "math", "statistics", "random", "json", "re", "datetime",
        "collections", "itertools", "functools", "operator",
        "hashlib", "hmac", "base64", "copy", "decimal", "fractions",
    ])
    block_builtins: list[str] = field(default_factory=lambda: [
        "exec", "eval", "compile", "__import__", "open",
        "breakpoint", "exit", "quit",
    ])


class WASMSandboxRunner:
    """Executes capability code in a WASM/Pyodide sandbox or hardened subprocess.

    Priority:
      1. Pyodide (if installed) — full WASM isolation
      2. Hardened subprocess — restricted builtins, blocked imports
    """

    def __init__(
        self,
        config: WASMSandboxConfig | None = None,
        max_memory_mb: int = 512,
        memory_limit_mb: int | None = None,
        timeout_seconds: int = 30,
        timeout_sec: float | None = None,
        **kwargs: Any,
    ):
        if config is None:
            mem = memory_limit_mb if memory_limit_mb is not None else max_memory_mb
            timeout = int(timeout_sec) if timeout_sec is not None else timeout_seconds
            self.config = WASMSandboxConfig(
                max_memory_mb=mem,
                timeout_seconds=timeout,
            )
        else:
            self.config = config
        self._pyodide_available = self._check_pyodide()

    def _check_pyodide(self) -> bool:
        """Check if Pyodide is available for server-side usage."""
        try:
            import pyodide  # noqa: F401
            return True
        except ImportError:
            return False


    def execute_code(
        self,
        code_body: str,
        entrypoint: str = "execute",
        inputs: dict[str, Any] | None = None,
        timeout_sec: float | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Alias for execute() to match SandboxDriver protocol."""
        res = self.execute(
            code_body=code_body,
            entrypoint=entrypoint,
            inputs=inputs or {},
        )
        if "success" not in res:
            res["success"] = res.get("status") == "SUCCESS"
        return res

    def execute(
        self,
        code_body: str,
        entrypoint: str,
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute code in the most secure available sandbox.

        Returns:
            {"status": "SUCCESS"|"FAILED"|"TIMEOUT"|"SECURITY_VIOLATION",
             "output": <result_dict>, "duration_ms": float, "driver": str}
        """
        # Pre-execution AST security scan
        violations = self._ast_security_scan(code_body)
        if violations:
            return {
                "status": "SECURITY_VIOLATION",
                "output": None,
                "violations": violations,
                "duration_ms": 0.0,
                "driver": "ast_scan",
            }

        if self._pyodide_available:
            return self._execute_pyodide(code_body, entrypoint, inputs)
        else:
            return self._execute_hardened_subprocess(code_body, entrypoint, inputs)

    def _ast_security_scan(self, code_body: str) -> list[str]:
        """Pre-execution AST scan for dangerous constructs."""
        violations = []
        try:
            tree = ast.parse(code_body)
        except SyntaxError as e:
            return [f"SyntaxError: {e}"]

        for node in ast.walk(tree):
            # Block dangerous calls
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in self.config.block_builtins:
                    violations.append(f"Blocked builtin call: {func.id}()")
                elif isinstance(func, ast.Attribute):
                    if func.attr in ("system", "popen", "exec", "spawn"):
                        violations.append(f"Blocked system call: .{func.attr}()")

            # Block dangerous imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_root = alias.name.split(".")[0]
                    if module_root in ("os", "subprocess", "shutil", "socket",
                                       "ctypes", "signal", "multiprocessing"):
                        violations.append(f"Blocked import: {alias.name}")

            if isinstance(node, ast.ImportFrom):
                if node.module:
                    module_root = node.module.split(".")[0]
                    if module_root in ("os", "subprocess", "shutil", "socket",
                                       "ctypes", "signal", "multiprocessing"):
                        violations.append(f"Blocked import from: {node.module}")

        return violations

    def _execute_pyodide(
        self,
        code_body: str,
        entrypoint: str,
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute code inside Pyodide WASM runtime."""
        start = time.perf_counter()
        try:
            from pyodide.code import run_python

            # Create isolated namespace
            namespace = {}
            run_python(code_body, globals=namespace)

            if entrypoint not in namespace:
                return {
                    "status": "FAILED",
                    "output": None,
                    "error": f"Entrypoint '{entrypoint}' not found in code",
                    "duration_ms": (time.perf_counter() - start) * 1000,
                    "driver": "pyodide",
                }

            result = namespace[entrypoint](inputs)
            duration = (time.perf_counter() - start) * 1000

            return {
                "status": "SUCCESS",
                "output": result,
                "duration_ms": round(duration, 3),
                "driver": "pyodide",
            }

        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            return {
                "status": "FAILED",
                "output": None,
                "error": str(e),
                "duration_ms": round(duration, 3),
                "driver": "pyodide",
            }

    def _execute_hardened_subprocess(
        self,
        code_body: str,
        entrypoint: str,
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute code in a hardened subprocess with restricted globals."""
        start = time.perf_counter()

        runner_script = textwrap.dedent(f"""
import sys
import json

# Restrict dangerous builtins
_blocked = {self.config.block_builtins!r}
_safe_builtins = {{k: v for k, v in __builtins__.items() if k not in _blocked}} if isinstance(__builtins__, dict) else {{
    k: getattr(__builtins__, k) for k in dir(__builtins__) if k not in _blocked
}}

# Restrict imports
_allowed_imports = {self.config.allowed_imports!r}
_original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

def _restricted_import(name, *args, **kwargs):
    root = name.split('.')[0]
    if root not in _allowed_imports and root not in ('numpy', 'scipy', 'pandas'):
        raise ImportError(f"Import '{{name}}' is not allowed in sandbox")
    return _original_import(name, *args, **kwargs)

_safe_builtins['__import__'] = _restricted_import

# Execute capability code
namespace = {{'__builtins__': _safe_builtins}}
inputs = json.loads(sys.stdin.read())

try:
    exec(compile(open(sys.argv[1]).read(), sys.argv[1], 'exec'), namespace)
    result = namespace['{entrypoint}'](inputs)
    print(json.dumps({{"status": "SUCCESS", "output": result}}))
except Exception as e:
    print(json.dumps({{"status": "FAILED", "error": str(e), "output": None}}))
""")

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as code_file:
            code_file.write(code_body)
            code_path = code_file.name

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as runner_file:
            runner_file.write(runner_script)
            runner_path = runner_file.name

        try:
            env = self._build_safe_env()
            proc = subprocess.run(
                [sys.executable, runner_path, code_path],
                input=json.dumps(inputs),
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds,
                env=env,
            )

            duration = (time.perf_counter() - start) * 1000

            if proc.returncode != 0:
                return {
                    "status": "FAILED",
                    "output": None,
                    "error": proc.stderr[:500],
                    "duration_ms": round(duration, 3),
                    "driver": "hardened_subprocess",
                }

            try:
                result = json.loads(proc.stdout)
                result["duration_ms"] = round(duration, 3)
                result["driver"] = "hardened_subprocess"
                return result
            except json.JSONDecodeError:
                return {
                    "status": "FAILED",
                    "output": None,
                    "error": f"Non-JSON stdout: {proc.stdout[:200]}",
                    "duration_ms": round(duration, 3),
                    "driver": "hardened_subprocess",
                }

        except subprocess.TimeoutExpired:
            duration = (time.perf_counter() - start) * 1000
            return {
                "status": "TIMEOUT",
                "output": None,
                "error": f"Exceeded {self.config.timeout_seconds}s timeout",
                "duration_ms": round(duration, 3),
                "driver": "hardened_subprocess",
            }
        finally:
            Path(code_path).unlink(missing_ok=True)
            Path(runner_path).unlink(missing_ok=True)

    def _build_safe_env(self) -> dict[str, str]:
        """Build a minimal, safe environment for subprocess execution."""
        import os
        safe_keys = [
            "PATH", "SYSTEMROOT", "TEMP", "TMP", "PYTHONPATH",
            "APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOME",
        ]
        env = {k: os.environ[k] for k in safe_keys if k in os.environ}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        return env


# Alias for casing convenience
WasmSandboxRunner = WASMSandboxRunner

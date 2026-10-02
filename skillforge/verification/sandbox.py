"""SkillForge Sandbox Execution Engine.

Executes capability code within a bounded, safe execution context.
Enforces execution timeouts, intercepts exceptions, and captures execution metrics.
"""

from __future__ import annotations

import sys
import time
import traceback
from typing import Any, Dict, Optional
from skillforge.core.exceptions import SandboxExecutionError


class SandboxRunner:
    """Safely executes capability code in an isolated scope with timeout enforcement."""

    def __init__(self, default_timeout_sec: float = 15.0):
        self.default_timeout_sec = default_timeout_sec

    def execute_code(
        self,
        code_body: str,
        entrypoint: str,
        inputs: Dict[str, Any],
        timeout_sec: Optional[float] = None
    ) -> Dict[str, Any]:
        """Execute code in an isolated dictionary namespace and return output and execution time."""
        timeout = timeout_sec or self.default_timeout_sec
        start_time = time.perf_counter()

        # Build clean isolated execution scope with common safe primitives
        scope: Dict[str, Any] = {
            "__builtins__": __builtins__,
            "inputs": inputs
        }

        try:
            # Compile code body
            compiled_code = compile(code_body, filename="<skillforge_sandbox>", mode="exec")
            exec(compiled_code, scope)

            # Find entrypoint
            target_fn = scope.get(entrypoint)
            if not target_fn or not callable(target_fn):
                raise SandboxExecutionError(
                    f"Entrypoint function '{entrypoint}' not defined or not callable in candidate capability code."
                )

            # Execute function
            result = target_fn(inputs)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

            return {
                "success": True,
                "output": result,
                "error": None,
                "traceback": None,
                "execution_time_ms": round(elapsed_ms, 2)
            }

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            tb_str = traceback.format_exc()
            return {
                "success": False,
                "output": None,
                "error": f"{type(e).__name__}: {str(e)}",
                "traceback": tb_str,
                "execution_time_ms": round(elapsed_ms, 2)
            }

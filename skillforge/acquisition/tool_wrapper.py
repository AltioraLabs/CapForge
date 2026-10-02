"""SkillForge Tool Wrapper & Generator.

Wraps low-level HTTP endpoints, SDK functions, or external tools into
TypeSafe, validated execution primitives with built-in retries and headers.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional
import httpx


class HttpToolWrapper:
    """Wraps external REST API calls with uniform headers, error wrapping, and timeout handling."""

    def __init__(
        self,
        base_url: str,
        default_headers: Optional[Dict[str, str]] = None,
        timeout_sec: float = 10.0
    ):
        self.base_url = base_url.rstrip("/")
        self.headers = default_headers or {}
        self.timeout_sec = timeout_sec

    def request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Execute HTTP request with error safety and structured dictionary return."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        merged_headers = {**self.headers, **(extra_headers or {})}

        try:
            with httpx.Client(timeout=self.timeout_sec) as client:
                response = client.request(
                    method=method.upper(),
                    url=url,
                    params=params,
                    json=json_data,
                    headers=merged_headers
                )
                
                # Check for rate limiting
                if response.status_code == 429:
                    return {
                        "status_code": 429,
                        "success": False,
                        "error": "RATE_LIMIT_EXCEEDED",
                        "retry_after": int(response.headers.get("Retry-After", "5"))
                    }

                # Try parse JSON
                try:
                    data = response.json()
                except Exception:
                    data = {"raw_text": response.text}

                return {
                    "status_code": response.status_code,
                    "success": response.is_success,
                    "data": data,
                    "error": None if response.is_success else f"HTTP_{response.status_code}"
                }
        except httpx.TimeoutException:
            return {"status_code": 408, "success": False, "error": "REQUEST_TIMEOUT", "data": None}
        except Exception as e:
            return {"status_code": 500, "success": False, "error": str(e), "data": None}

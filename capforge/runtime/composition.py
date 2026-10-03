"""CapForge Capability Composition Engine.

Enables agents to compose modular primitives (e.g. auth, pagination, retry backoff)
into compound workflows without rediscovering solved sub-problems from scratch.
"""

from __future__ import annotations

from pydantic import BaseModel

from capforge.core.models import Capability, CapabilityStatus
from capforge.registry.store import CapabilityRegistry


class PrimitiveDefinition(BaseModel):
    id: str
    name: str
    code_snippet: str
    inputs: list[str]
    outputs: list[str]


class CompositionEngine:
    """Manages the composition of reusable primitive capabilities into higher-order workflows."""

    STANDARD_PRIMITIVES: dict[str, PrimitiveDefinition] = {
        "auth_bearer": PrimitiveDefinition(
            id="auth_bearer",
            name="Bearer Token Auth Handler",
            code_snippet="""
def apply_bearer_auth(headers: dict, token: str) -> dict:
    updated = dict(headers or {})
    if token:
        updated["Authorization"] = f"Bearer {token}"
    return updated
""".strip(),
            inputs=["headers", "token"],
            outputs=["headers"],
        ),
        "cursor_pagination": PrimitiveDefinition(
            id="cursor_pagination",
            name="Cursor-based Paginator",
            code_snippet="""
def paginate_items(fetch_fn, initial_params: dict, max_pages: int = 5) -> list:
    all_items = []
    params = dict(initial_params or {})
    for _ in range(max_pages):
        resp = fetch_fn(params)
        items = resp.get("items", [])
        all_items.extend(items)
        cursor = resp.get("next_cursor")
        if not cursor:
            break
        params["cursor"] = cursor
    return all_items
""".strip(),
            inputs=["fetch_fn", "initial_params"],
            outputs=["items"],
        ),
        "rate_limit_backoff": PrimitiveDefinition(
            id="rate_limit_backoff",
            name="Rate Limit Retry with Exponential Backoff",
            code_snippet="""
import time

def retry_with_backoff(call_fn, max_retries: int = 3, initial_delay: float = 1.0):
    delay = initial_delay
    for attempt in range(max_retries):
        result = call_fn()
        if result.get("status_code") != 429:
            return result
        time.sleep(delay)
        delay *= 2
    return result
""".strip(),
            inputs=["call_fn"],
            outputs=["result"],
        ),
        "anomaly_detector": PrimitiveDefinition(
            id="anomaly_detector",
            name="Statistical Metric Anomaly Detector",
            code_snippet="""
def detect_anomalies(data_points: list, threshold_std: float = 2.0) -> list:
    if len(data_points) < 3:
        return []
    values = [p.get("value", 0.0) if isinstance(p, dict) else float(p) for p in data_points]
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    std = variance ** 0.5
    anomalies = []
    for i, val in enumerate(values):
        if std > 0 and abs(val - mean) / std >= threshold_std:
            anomalies.append({"index": i, "value": val, "z_score": round((val - mean) / std, 2)})
    return anomalies
""".strip(),
            inputs=["data_points"],
            outputs=["anomalies"],
        ),
    }

    def __init__(self, registry: CapabilityRegistry | None = None):
        self.registry = registry

    def get_primitive(self, primitive_id: str) -> PrimitiveDefinition | None:
        """Fetch primitive definition by identifier."""
        return self.STANDARD_PRIMITIVES.get(primitive_id)

    def synthesize_composite_capability(
        self, composite_id: str, name: str, description: str, primitive_ids: list[str], custom_logic: str
    ) -> Capability:
        """Compose multiple primitives into a unified new Capability object."""
        snippets = []
        for pid in primitive_ids:
            prim = self.get_primitive(pid)
            if prim:
                snippets.append(prim.code_snippet)

        combined_code = "\n\n".join(snippets) + "\n\n" + custom_logic

        return Capability(
            id=composite_id,
            name=name,
            version="1.0.0",
            status=CapabilityStatus.EXPERIMENTAL,
            description=description,
            domain="composition",
            tags=["composed", *primitive_ids],
            code_body=combined_code,
            entrypoint_function="execute",
            changelog=f"Synthesized from primitives: {', '.join(primitive_ids)}",
        )

"""CapForge OpenTelemetry-Compatible Distributed Tracing Engine.

Provides W3C trace context generation, thread-local span propagation, latency profiling,
GenAI semantic conventions, and structured span recording across capability execution,
LLM synthesis, sandbox execution, and event routing.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import time
import urllib.request
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("capforge.telemetry")


class SpanContext(BaseModel):
    """W3C-compatible trace context."""

    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    span_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    trace_flags: int = 1


class Span(BaseModel):
    """Represents a single timed unit of work in CapForge runtime."""

    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    start_time: float = Field(default_factory=time.time)
    end_time: float | None = None
    duration_ms: float | None = None
    status: str = "OK"  # "OK" | "ERROR"
    error_message: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self.events.append(
            {
                "name": name,
                "timestamp": time.time(),
                "attributes": attributes or {},
            }
        )

    def end(self, status: str = "OK", error: str | None = None) -> None:
        self.end_time = time.time()
        self.duration_ms = round((self.end_time - self.start_time) * 1000.0, 3)
        self.status = status
        if error:
            self.error_message = error
            self.status = "ERROR"

    def to_otlp_span(self) -> dict[str, Any]:
        """Convert span to standard OTLP JSON format."""
        start_nano = int(self.start_time * 1e9)
        end_nano = int((self.end_time or time.time()) * 1e9)

        attrs = []
        for k, v in self.attributes.items():
            if isinstance(v, bool):
                val_dict = {"boolValue": v}
            elif isinstance(v, int):
                val_dict = {"intValue": v}
            elif isinstance(v, float):
                val_dict = {"doubleValue": v}
            else:
                val_dict = {"stringValue": str(v)}
            attrs.append({"key": k, "value": val_dict})

        return {
            "traceId": self.trace_id,
            "spanId": self.span_id,
            "parentSpanId": self.parent_span_id or "",
            "name": self.name,
            "kind": 1,  # SPAN_KIND_INTERNAL
            "startTimeUnixNano": str(start_nano),
            "endTimeUnixNano": str(end_nano),
            "attributes": attrs,
            "status": {
                "code": 1 if self.status == "OK" else 2,
                "message": self.error_message or "",
            },
        }


# Global context variable for active span
_current_span_var: contextvars.ContextVar[Span | None] = contextvars.ContextVar("current_span", default=None)


class TraceManager:
    """Manages span lifecycles, distributed context propagation, and span storage."""

    def __init__(self, max_buffer_size: int = 5000):
        self.max_buffer_size = max_buffer_size
        self._spans: list[Span] = []

    def get_current_span(self) -> Span | None:
        return _current_span_var.get()

    def get_current_trace_id(self) -> str:
        span = self.get_current_span()
        return span.trace_id if span else uuid.uuid4().hex

    @contextmanager
    def start_span(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
        parent_trace_id: str | None = None,
        parent_span_id: str | None = None,
    ):
        """Context manager to create, activate, and automatically end a trace span."""
        parent_span = self.get_current_span()

        trace_id = parent_trace_id or (parent_span.trace_id if parent_span else uuid.uuid4().hex)
        p_span_id = parent_span_id or (parent_span.span_id if parent_span else None)

        span = Span(
            name=name,
            trace_id=trace_id,
            span_id=uuid.uuid4().hex[:16],
            parent_span_id=p_span_id,
            attributes=attributes or {},
        )

        token = _current_span_var.set(span)
        try:
            yield span
            if span.end_time is None:
                span.end(status="OK")
        except Exception as e:
            if span.end_time is None:
                span.end(status="ERROR", error=str(e))
            raise
        finally:
            _current_span_var.reset(token)
            self._record_span(span)

    def _record_span(self, span: Span) -> None:
        self._spans.append(span)
        if len(self._spans) > self.max_buffer_size:
            self._spans.pop(0)

    def list_spans(
        self,
        trace_id: str | None = None,
        name: str | None = None,
        limit: int = 100,
    ) -> list[Span]:
        """Query recorded spans with optional filtering."""
        filtered = self._spans
        if trace_id:
            filtered = [s for s in filtered if s.trace_id == trace_id]
        if name:
            filtered = [s for s in filtered if name.lower() in s.name.lower()]
        return filtered[-limit:]

    def export_spans_to_dict(self) -> list[dict[str, Any]]:
        """Export all buffered spans as dictionaries."""
        return [s.model_dump() for s in self._spans]

    def export_spans_to_json(self, file_path: Path | str | None = None) -> str:
        """Export buffered spans to JSON string and optionally save to file."""
        data = json.dumps(self.export_spans_to_dict(), indent=2, default=str)
        if file_path:
            p = Path(file_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(data, encoding="utf-8")
        return data

    def export_to_otlp(self, endpoint: str | None = None) -> bool:
        """Export buffered spans to an OpenTelemetry collector endpoint (e.g. http://localhost:4318/v1/traces)."""
        ep = endpoint or os.environ.get("CAPFORGE_OTLP_ENDPOINT")
        if not ep or not self._spans:
            return False

        otlp_payload = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "capforge"}},
                            {"key": "service.version", "value": {"stringValue": "1.1.0"}},
                        ]
                    },
                    "scopeSpans": [
                        {
                            "scope": {"name": "capforge.telemetry"},
                            "spans": [s.to_otlp_span() for s in self._spans],
                        }
                    ],
                }
            ]
        }

        try:
            req = urllib.request.Request(
                ep,
                data=json.dumps(otlp_payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return resp.status in (200, 201, 202)
        except Exception as e:
            logger.debug("Failed to export OTLP spans: %s", e)
            return False

    def inject_trace_context(self, carrier: dict[str, str]) -> dict[str, str]:
        """Inject current span into carrier as standard W3C traceparent header."""
        span = self.get_current_span()
        if span:
            carrier["traceparent"] = f"00-{span.trace_id}-{span.span_id}-01"
        return carrier

    def extract_trace_context(self, carrier: dict[str, str]) -> tuple[str | None, str | None]:
        """Extract trace_id and span_id from W3C traceparent header."""
        tp = carrier.get("traceparent") or carrier.get("TRACEPARENT")
        if tp:
            parts = tp.split("-")
            if len(parts) >= 4:
                return parts[1], parts[2]
        return None, None

    def clear(self) -> None:
        self._spans.clear()


# Default singleton instance
trace_manager = TraceManager()


# ---------------------------------------------------------------------------
# OpenTelemetry GenAI Semantic Conventions
# ---------------------------------------------------------------------------


class GenAISemanticConventions:
    """Standardized GenAI telemetry attribute keys conforming to OpenTelemetry specs."""

    SYSTEM = "gen_ai.system"  # e.g., "capforge", "gemini", "openai", "ollama"
    REQUEST_MODEL = "gen_ai.request.model"
    REQUEST_TEMPERATURE = "gen_ai.request.temperature"
    REQUEST_MAX_TOKENS = "gen_ai.request.max_tokens"
    RESPONSE_ID = "gen_ai.response.id"
    RESPONSE_FINISH_REASONS = "gen_ai.response.finish_reasons"
    USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
    USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
    CAPABILITY_ID = "capforge.capability.id"
    CAPABILITY_VERSION = "capforge.capability.version"
    CAPABILITY_STATUS = "capforge.capability.status"
    SANDBOX_DRIVER = "capforge.sandbox.driver"
    VERIFICATION_PASSED = "capforge.verification.passed"
    REPAIR_PASS = "capforge.repair.pass"


def record_llm_call(
    model: str,
    system: str = "capforge",
    temperature: float = 0.2,
    input_tokens: int = 0,
    output_tokens: int = 0,
    duration_ms: float = 0.0,
    error: str | None = None,
) -> Span:
    """Helper to record a standardized GenAI span in active trace context."""
    _parent_span = trace_manager.get_current_span()
    with trace_manager.start_span(f"gen_ai.{system}.completion") as s:
        s.set_attribute(GenAISemanticConventions.SYSTEM, system)
        s.set_attribute(GenAISemanticConventions.REQUEST_MODEL, model)
        s.set_attribute(GenAISemanticConventions.REQUEST_TEMPERATURE, temperature)
        s.set_attribute(GenAISemanticConventions.USAGE_INPUT_TOKENS, input_tokens)
        s.set_attribute(GenAISemanticConventions.USAGE_OUTPUT_TOKENS, output_tokens)
        if error:
            s.end(status="ERROR", error=error)
        return s


def instrument_capability(capability_id: str) -> Callable:
    """Decorator to instrument capability execution with OpenTelemetry tracing."""

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with trace_manager.start_span(f"capability.execute.{capability_id}") as span:
                span.set_attribute(GenAISemanticConventions.CAPABILITY_ID, capability_id)
                return fn(*args, **kwargs)

        return wrapper

    return decorator

"""CapForge OpenTelemetry-Compatible Distributed Tracing (discussion.mdx §29, §50).

Provides W3C trace context generation, thread-local span propagation, latency profiling,
and structured span recording for capability execution, event routing, and learning pipelines.
"""

from __future__ import annotations

import contextvars
import time
import uuid
from contextlib import contextmanager
from typing import Any

from pydantic import BaseModel, Field


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


# Global context variable for active span
_current_span_var: contextvars.ContextVar[Span | None] = contextvars.ContextVar("current_span", default=None)


class TraceManager:
    """Manages span lifecycles, distributed context propagation, and span storage."""

    def __init__(self, max_buffer_size: int = 2000):
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
        limit: int = 50,
    ) -> list[Span]:
        """Query recorded spans with optional filtering."""
        filtered = self._spans
        if trace_id:
            filtered = [s for s in filtered if s.trace_id == trace_id]
        if name:
            filtered = [s for s in filtered if name.lower() in s.name.lower()]
        return filtered[-limit:]

    def clear(self) -> None:
        self._spans.clear()


# Default singleton instance
trace_manager = TraceManager()

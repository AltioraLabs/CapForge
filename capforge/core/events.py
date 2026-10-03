"""CapForge Event Gateway & Experience Engine.

Provides the Universal Event Model ingestion pipeline and
intelligent experience filtering to determine which agent events
are worth learning from (discussion.mdx §9, §16).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from capforge.core.models import AgentEvent, EventType

logger = logging.getLogger("capforge.events")


class EventGateway:
    """Receives, normalises, and dispatches agent events to registered handlers and stream brokers."""

    def __init__(self, broker: Any | None = None) -> None:
        from capforge.events.broker import InMemoryStreamBroker

        self._handlers: dict[EventType, list[Callable[[AgentEvent], None]]] = defaultdict(list)
        self._event_log: list[AgentEvent] = []
        self._max_log_size: int = 10_000
        self.broker = broker if broker is not None else InMemoryStreamBroker()

    def subscribe(self, event_type: EventType, handler: Callable[[AgentEvent], None]) -> None:
        """Register a handler for a specific event type."""
        self._handlers[event_type].append(handler)

    def subscribe_all(self, handler: Callable[[AgentEvent], None]) -> None:
        """Register a handler that receives every event type."""
        for et in EventType:
            self._handlers[et].append(handler)

    def emit(self, event: AgentEvent) -> None:
        """Emit an event through the gateway to all subscribed handlers and the stream broker."""
        # Store in log
        self._event_log.append(event)
        if len(self._event_log) > self._max_log_size:
            self._event_log = self._event_log[-self._max_log_size :]

        # Publish to distributed stream broker
        if self.broker is not None:
            try:
                self.broker.publish(f"events.{event.event_type.value}", event)
            except Exception:
                logger.exception("Failed publishing event %s to stream broker", event.event_id)

        logger.info(
            "event_emitted",
            extra={
                "event_id": event.event_id,
                "event_type": event.event_type.value,
                "agent_id": event.agent_id,
                "run_id": event.run_id,
            },
        )

        for handler in self._handlers.get(event.event_type, []):
            try:
                handler(event)
            except Exception:
                logger.exception("Handler error for event %s", event.event_id)

    def get_recent_events(self, limit: int = 50) -> list[AgentEvent]:
        """Return the most recent events from the log."""
        return self._event_log[-limit:]

    def get_events_by_run(self, run_id: str) -> list[AgentEvent]:
        """Return all events for a specific run."""
        return [e for e in self._event_log if e.run_id == run_id]


class ExperienceFilter:
    """Determines whether an agent event is worth learning from (discussion.mdx §16).

    Ignore:
      - Routine success
      - Duplicate experience
      - Trivial failure
      - Known failure
      - Low-value variation

    Learn:
      - Novel failure
      - Repeated failure (same tool > threshold)
      - Capability gap
      - Unexpected successful strategy
      - High-value recovery
      - New tool discovery
      - Repeatedly useful procedure
      - Transferable solution
    """

    # Events that always trigger learning evaluation
    LEARN_EVENT_TYPES = frozenset(
        {
            EventType.CAPABILITY_GAP_DETECTED,
            EventType.LEARNING_STARTED,
            EventType.SKILL_CANDIDATE_CREATED,
        }
    )

    # Events that may trigger learning depending on context
    MAYBE_LEARN_EVENT_TYPES = frozenset(
        {
            EventType.TOOL_FAILED,
            EventType.TASK_FAILED,
            EventType.SKILL_FAILED,
        }
    )

    def __init__(self, failure_threshold: int = 3) -> None:
        self.failure_threshold = failure_threshold
        self._failure_counts: dict[str, int] = defaultdict(int)
        self._seen_errors: set[str] = set()

    def should_learn(self, event: AgentEvent) -> bool:
        """Evaluate whether this event should trigger the learning pipeline."""
        # Always learn from gap detections
        if event.event_type in self.LEARN_EVENT_TYPES:
            return True

        # Evaluate failure events
        if event.event_type in self.MAYBE_LEARN_EVENT_TYPES:
            return self._evaluate_failure(event)

        return False

    def _evaluate_failure(self, event: AgentEvent) -> bool:
        """Determine if a failure event is novel or repeated enough to learn from."""
        error_sig = self._error_signature(event)

        # Novel failure — never seen before
        if error_sig not in self._seen_errors:
            self._seen_errors.add(error_sig)
            return True

        # Repeated failure — same tool or pattern beyond threshold
        tool_key = event.tool_name or event.event_type.value
        self._failure_counts[tool_key] += 1
        if self._failure_counts[tool_key] >= self.failure_threshold:
            self._failure_counts[tool_key] = 0  # Reset after triggering
            return True

        return False

    def _error_signature(self, event: AgentEvent) -> str:
        """Generate a deduplicated signature for an error event."""
        parts = [
            event.event_type.value,
            event.tool_name or "no_tool",
            event.error_type or "no_type",
            (event.error_message or "")[:100],
        ]
        return "|".join(parts)

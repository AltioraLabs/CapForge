"""CapForge Statistical Trigger Engine.

Implements Level 0 (deterministic telemetry) and Level 1 (lightweight statistical trigger detection)
from discussion.mdx §23, §24 and SPECIFICATION §22, §26 #14-#15.

Prevents expensive LLM invocations by identifying statistically significant failure trends,
error spikes, and latency regressions before dispatching to LLM diagnosis.
"""

from __future__ import annotations

import collections
import enum
import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from capforge.core.models import AgentEvent, EventType, RiskLevel

logger = logging.getLogger("capforge.trigger")


class TriggerType(str, enum.Enum):
    FAILURE_RATE_ACCELERATION = "failure_rate_acceleration"
    REPEATED_TOOL_FAILURE = "repeated_tool_failure"
    LATENCY_DEGRADATION = "latency_degradation"
    HIGH_SEVERITY_FAILURE = "high_severity_failure"
    CAPABILITY_GAP = "capability_gap"


class TriggerEvent(BaseModel):
    """Payload emitted when a statistically significant anomaly triggers Level 2 diagnosis."""

    trigger_type: TriggerType
    capability_id: str | None = None
    tool_name: str | None = None
    severity: RiskLevel = RiskLevel.MEDIUM
    rationale: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MetricWindow:
    """Sliding window of recent execution outcomes and latencies for an entity."""

    def __init__(self, window_size: int = 50) -> None:
        self.window_size = window_size
        self.outcomes: collections.deque[bool] = collections.deque(maxlen=window_size)  # True=success, False=failure
        self.latencies_ms: collections.deque[float] = collections.deque(maxlen=window_size)

    def record(self, success: bool, latency_ms: float = 0.0) -> None:
        self.outcomes.append(success)
        if latency_ms > 0:
            self.latencies_ms.append(latency_ms)

    @property
    def total_count(self) -> int:
        return len(self.outcomes)

    @property
    def failure_rate(self) -> float:
        if not self.outcomes:
            return 0.0
        failures = sum(1 for x in self.outcomes if not x)
        return failures / len(self.outcomes)

    @property
    def avg_latency_ms(self) -> float:
        if not self.latencies_ms:
            return 0.0
        return sum(self.latencies_ms) / len(self.latencies_ms)


class TriggerEngine:
    """Monitors telemetry metrics to detect statistically sound evolution triggers."""

    def __init__(
        self,
        repeated_failure_threshold: int = 3,
        failure_rate_threshold: float = 0.15,
        min_samples_for_rate: int = 10,
    ) -> None:
        self.repeated_failure_threshold = repeated_failure_threshold
        self.failure_rate_threshold = failure_rate_threshold
        self.min_samples_for_rate = min_samples_for_rate

        self._windows: dict[str, MetricWindow] = collections.defaultdict(MetricWindow)
        self._consecutive_failures: dict[str, int] = collections.defaultdict(int)

    def process_event(self, event: AgentEvent) -> TriggerEvent | None:
        """Processes an incoming normalized event and checks for evolution trigger conditions."""
        # 1. Immediate trigger on explicit gap detection
        if event.event_type == EventType.CAPABILITY_GAP_DETECTED:
            return TriggerEvent(
                trigger_type=TriggerType.CAPABILITY_GAP,
                capability_id=event.metadata.get("missing_capability"),
                severity=RiskLevel.HIGH,
                rationale="Explicit capability gap detected by task analyzer",
                metrics={"task_id": event.task_id},
            )

        target_key = event.tool_name or event.metadata.get("capability_id") or "general"
        window = self._windows[target_key]

        # 2. Record tool outcomes
        if event.event_type in (EventType.TOOL_SUCCEEDED, EventType.SKILL_COMPLETED, EventType.TASK_COMPLETED):
            self._consecutive_failures[target_key] = 0
            latency = float(event.metadata.get("latency_ms", 0.0))
            window.record(success=True, latency_ms=latency)
            return None

        if event.event_type in (EventType.TOOL_FAILED, EventType.SKILL_FAILED, EventType.TASK_FAILED):
            self._consecutive_failures[target_key] += 1
            latency = float(event.metadata.get("latency_ms", 0.0))
            window.record(success=False, latency_ms=latency)

            # Check: Consecutive repeated failures
            if self._consecutive_failures[target_key] >= self.repeated_failure_threshold:
                consecutive = self._consecutive_failures[target_key]
                self._consecutive_failures[target_key] = 0  # reset after firing
                return TriggerEvent(
                    trigger_type=TriggerType.REPEATED_TOOL_FAILURE,
                    tool_name=event.tool_name,
                    capability_id=event.metadata.get("capability_id"),
                    severity=RiskLevel.MEDIUM,
                    rationale=f"Tool or skill failed {consecutive} times consecutively",
                    metrics={
                        "consecutive_failures": consecutive,
                        "error_type": event.error_type,
                        "error_message": event.error_message,
                    },
                )

            # Check: Accelerated failure rate over sample window
            if window.total_count >= self.min_samples_for_rate:
                fail_rate = window.failure_rate
                if fail_rate >= self.failure_rate_threshold:
                    return TriggerEvent(
                        trigger_type=TriggerType.FAILURE_RATE_ACCELERATION,
                        tool_name=event.tool_name,
                        capability_id=event.metadata.get("capability_id"),
                        severity=RiskLevel.HIGH if fail_rate > 0.35 else RiskLevel.MEDIUM,
                        rationale=f"Failure rate ({fail_rate:.1%}) exceeded threshold ({self.failure_rate_threshold:.1%})",
                        metrics={
                            "failure_rate": fail_rate,
                            "window_size": window.total_count,
                            "avg_latency_ms": window.avg_latency_ms,
                        },
                    )

        return None


# Global default instance
trigger_engine = TriggerEngine()

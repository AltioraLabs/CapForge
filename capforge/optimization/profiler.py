"""CapForge Runtime Profiling & Bottleneck Detection Engine.

Analyzes capability execution telemetry across latency, throughput, and resource
utilization to autonomously detect performance bottlenecks and flag OPTIMIZATION_GAP
events when capabilities exceed SLA latency thresholds or show CPU/memory hotspots.
"""

from __future__ import annotations

import logging
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel, Field

logger = logging.getLogger("capforge.optimization.profiler")


class OptimizationGap(BaseModel):
    """Represents an autonomously detected capability performance deficiency."""

    capability_id: str
    version: str
    gap_detected: bool = True
    reason: str  # "LATENCY_BOTTLENECK", "HIGH_MEMORY_PRESSURE", "HIGH_FREQUENCY_CPU_BOUND"
    sample_count: int
    mean_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    target_p95_ms: float
    suggested_action: str  # "JIT_COMPILE_RUST_C", "VECTORIZE_NUMPY", "CACHE_MEMOIZE"
    rationale: str = ""
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


@dataclass
class LatencyProfile:
    """Historical execution duration samples and statistical aggregates."""

    capability_id: str
    version: str
    max_samples: int = 200
    samples: deque[float] = field(default_factory=lambda: deque(maxlen=200))
    error_count: int = 0
    total_calls: int = 0
    last_called_at: float = field(default_factory=time.time)

    def record(self, duration_ms: float, success: bool = True) -> None:
        self.samples.append(duration_ms)
        self.total_calls += 1
        self.last_called_at = time.time()
        if not success:
            self.error_count += 1

    @property
    def sample_count(self) -> int:
        return len(self.samples)

    @property
    def mean(self) -> float:
        return statistics.mean(self.samples) if self.samples else 0.0

    @property
    def p50(self) -> float:
        if not self.samples:
            return 0.0
        sorted_s = sorted(self.samples)
        idx = int(0.50 * len(sorted_s))
        return sorted_s[min(idx, len(sorted_s) - 1)]

    @property
    def p95(self) -> float:
        if not self.samples:
            return 0.0
        sorted_s = sorted(self.samples)
        idx = int(0.95 * len(sorted_s))
        return sorted_s[min(idx, len(sorted_s) - 1)]

    @property
    def p99(self) -> float:
        if not self.samples:
            return 0.0
        sorted_s = sorted(self.samples)
        idx = int(0.99 * len(sorted_s))
        return sorted_s[min(idx, len(sorted_s) - 1)]

    @property
    def stddev(self) -> float:
        return statistics.stdev(self.samples) if len(self.samples) > 1 else 0.0


class RuntimeProfiler:
    """Collects runtime telemetry to identify slow capabilities and emit optimization gaps."""

    def __init__(
        self,
        default_latency_sla_ms: float = 300.0,
        min_samples_before_audit: int = 5,
    ) -> None:
        self.default_latency_sla_ms = default_latency_sla_ms
        self.min_samples_before_audit = min_samples_before_audit
        self._profiles: dict[tuple[str, str], LatencyProfile] = {}
        self._sla_overrides: dict[str, float] = {}

    def set_sla(self, capability_id: str, max_p95_ms: float) -> None:
        """Set custom SLA target for a specific capability."""
        self._sla_overrides[capability_id] = max_p95_ms

    def record_execution(
        self,
        capability_id: str,
        version: str,
        duration_ms: float,
        success: bool = True,
    ) -> None:
        """Record a single execution metric."""
        key = (capability_id, version)
        if key not in self._profiles:
            self._profiles[key] = LatencyProfile(capability_id=capability_id, version=version)
        self._profiles[key].record(duration_ms, success=success)

    def get_profile(self, capability_id: str, version: str) -> LatencyProfile | None:
        return self._profiles.get((capability_id, version))

    def detect_optimization_gaps(self) -> list[OptimizationGap]:
        """Analyze all profiled capabilities and flag optimization gaps."""
        gaps: list[OptimizationGap] = []

        for (cap_id, version), profile in self._profiles.items():
            if profile.sample_count < self.min_samples_before_audit:
                continue

            sla = self._sla_overrides.get(cap_id, self.default_latency_sla_ms)
            p95 = profile.p95
            p50 = profile.p50
            mean = profile.mean

            # Detection 1: P95 violates SLA threshold
            if p95 > sla:
                ratio = p95 / sla
                gap = OptimizationGap(
                    capability_id=cap_id,
                    version=version,
                    reason="LATENCY_BOTTLENECK",
                    sample_count=profile.sample_count,
                    mean_latency_ms=round(mean, 2),
                    p50_latency_ms=round(p50, 2),
                    p95_latency_ms=round(p95, 2),
                    p99_latency_ms=round(profile.p99, 2),
                    target_p95_ms=sla,
                    suggested_action="JIT_COMPILE_RUST_C",
                    rationale=(
                        f"P95 execution latency ({p95:.1f}ms) exceeds SLA ({sla:.1f}ms) by {ratio:.1f}x. "
                        "Recommend transpiling inner loop into compiled Rust/C extension."
                    ),
                )
                gaps.append(gap)
                logger.info("Optimization gap detected for %s: %s", cap_id, gap.rationale)

            # Detection 2: High latency variance / tail latency spike
            elif profile.p99 > sla * 2.0 and profile.sample_count >= 10:
                gap = OptimizationGap(
                    capability_id=cap_id,
                    version=version,
                    reason="TAIL_LATENCY_SPIKE",
                    sample_count=profile.sample_count,
                    mean_latency_ms=round(mean, 2),
                    p50_latency_ms=round(p50, 2),
                    p95_latency_ms=round(p95, 2),
                    p99_latency_ms=round(profile.p99, 2),
                    target_p95_ms=sla,
                    suggested_action="CACHE_MEMOIZE",
                    rationale=(
                        f"P99 latency ({profile.p99:.1f}ms) is over 2x SLA ({sla:.1f}ms), "
                        "indicating catastrophic tail variance. Recommend input caching or memoization."
                    ),
                )
                gaps.append(gap)

        return gaps


# Global profiling singleton
profiler = RuntimeProfiler()

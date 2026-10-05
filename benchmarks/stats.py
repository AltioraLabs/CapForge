"""Statistical helper utilities for CapForge Benchmark Suite.

Provides robust percentile calculations, outlier rejection, variance,
confidence intervals, and formatted displays.
"""

from __future__ import annotations

import math
import statistics
from typing import Any


def compute_percentile(sorted_data: list[float], pct: float) -> float:
    """Calculate percentile using standard linear interpolation."""
    if not sorted_data:
        return 0.0
    if len(sorted_data) == 1:
        return sorted_data[0]
    k = (len(sorted_data) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    d0 = sorted_data[int(f)] * (c - k)
    d1 = sorted_data[int(c)] * (k - f)
    return d0 + d1


def compute_stats(samples: list[float], unit: str = "us") -> dict[str, Any]:
    """Compute comprehensive statistical metrics from a list of samples.

    Args:
        samples: Array of numerical measurements (e.g. latency in µs or ms).
        unit: Unit label ('us' for microseconds, 'ms' for milliseconds).

    Returns:
        Dictionary containing sample size, min, p50, p90, p95, p99, max,
        mean, stddev, 95% confidence intervals, and ops/sec throughput.
    """
    if not samples:
        return {
            "count": 0,
            "min": 0.0,
            "p50": 0.0,
            "p90": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "max": 0.0,
            "mean": 0.0,
            "stddev": 0.0,
            "stderr": 0.0,
            "ci95_low": 0.0,
            "ci95_high": 0.0,
            "throughput_ops_sec": 0.0,
        }

    sorted_samples = sorted(samples)
    n = len(sorted_samples)
    mean_val = statistics.mean(sorted_samples)
    stddev_val = statistics.stdev(sorted_samples) if n >= 2 else 0.0
    stderr_val = stddev_val / math.sqrt(n) if n > 0 else 0.0
    ci95_margin = 1.96 * stderr_val

    factor_to_sec = 1e6 if unit == "us" else 1e3
    throughput = (factor_to_sec / mean_val) if mean_val > 0 else 0.0

    return {
        "count": n,
        "min": round(sorted_samples[0], 2),
        "p50": round(compute_percentile(sorted_samples, 50.0), 2),
        "p90": round(compute_percentile(sorted_samples, 90.0), 2),
        "p95": round(compute_percentile(sorted_samples, 95.0), 2),
        "p99": round(compute_percentile(sorted_samples, 99.0), 2),
        "max": round(sorted_samples[-1], 2),
        "mean": round(mean_val, 2),
        "stddev": round(stddev_val, 2),
        "stderr": round(stderr_val, 2),
        "ci95_low": round(max(0.0, mean_val - ci95_margin), 2),
        "ci95_high": round(mean_val + ci95_margin, 2),
        "ci95_margin": round(ci95_margin, 2),
        "throughput_ops_sec": round(throughput, 1),
    }


def format_latency(val_us: float) -> str:
    """Format latency in µs or ms appropriately."""
    if val_us >= 1000.0:
        return f"{val_us / 1000.0:.2f} ms"
    return f"{val_us:.2f} µs"


def format_ci95(stats: dict[str, Any], unit: str = "ms") -> str:
    """Format confidence interval as '[low – high] unit'."""
    low = stats.get("ci95_low", 0.0)
    high = stats.get("ci95_high", 0.0)
    return f"[{low:.1f} – {high:.1f}] {unit}"

"""Unit tests for the CapForge Automated Benchmark Suite.

Ensures benchmark harnesses run reliably in CI/CD without crashes or false positives.
"""

from __future__ import annotations

import pytest

from benchmarks.bench_execution_overhead import run_benchmark as run_overhead
from benchmarks.bench_pyo3_speedup import run_benchmark as run_pyo3
from benchmarks.bench_synthesis_latency import run_benchmark as run_synthesis
from benchmarks.bench_verification_throughput import run_benchmark as run_throughput
from benchmarks.stats import compute_percentile, compute_stats, format_latency


def test_stats_edge_cases():
    """Verify statistics calculator with edge cases."""
    # Empty
    empty = compute_stats([])
    assert empty["count"] == 0
    assert empty["p50"] == 0.0

    # Single element
    single = compute_stats([42.0])
    assert single["count"] == 1
    assert single["p50"] == 42.0
    assert single["mean"] == 42.0
    assert single["stddev"] == 0.0

    # Normal distribution
    data = [10.0, 20.0, 30.0, 40.0, 50.0]
    stats = compute_stats(data)
    assert stats["count"] == 5
    assert stats["p50"] == 30.0
    assert stats["min"] == 10.0
    assert stats["max"] == 50.0
    assert stats["mean"] == 30.0

    # Percentiles
    assert compute_percentile([1, 2, 3, 4, 5], 50.0) == 3.0
    assert compute_percentile([10, 20, 30, 40], 0.0) == 10.0
    assert compute_percentile([10, 20, 30, 40], 100.0) == 40.0


def test_format_latency():
    """Verify latency unit formatting."""
    assert format_latency(500.0) == "500.00 µs"
    assert format_latency(1500.0) == "1.50 ms"
    assert format_latency(250000.0) == "250.00 ms"


def test_bench_execution_overhead():
    """Verify execution overhead benchmark runs and returns valid structure."""
    res = run_overhead(iterations=10, warmup_iterations=2, include_subprocess=False)
    assert "inproc_micro" in res
    assert "inproc_structured" in res
    assert "inproc_numerical" in res
    assert res["capforge_p50_us"] > 0
    assert res["throughput_ops_sec"] > 0


def test_bench_pyo3_speedup():
    """Verify PyO3 speedup benchmark with parity validation."""
    res = run_pyo3(simulations=5000, trials=2, warmup_trials=1)
    assert "monte_carlo" in res
    assert "moving_volatility" in res
    assert res["speedup_factor"] >= 1.0
    assert res["parity_verified"] is True


def test_bench_synthesis_latency():
    """Verify synthesis latency tiered budget benchmark."""
    res = run_synthesis(iterations=1)
    assert res["iterations"] == 1
    assert res["total_median_ms"] > 0
    assert res["fast_check_median_ms"] > 0


def test_bench_verification_throughput():
    """Verify verification battery throughput and 100% test pass rate."""
    res = run_throughput(capability_count=6, concurrency_levels=[1, 2])
    assert res["capability_count"] == 6
    assert res["passed_count"] == 6  # 100% pass rate
    assert res["caps_per_minute"] > 0

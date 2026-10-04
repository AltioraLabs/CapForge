"""Benchmark: Raw Python Execution vs CapForge Execution Runtime Overhead.

Scientifically measures the latency delta introduced by CapForge's runtime layers:
  1. In-Process Guarded Mode: CodeGuardian AST Firewall + SchemaValidator + Telemetry Tracing
     (Measures the true software framework overhead on active capabilities).
  2. Subprocess Isolation Mode: Full OS process-level sandboxing with resource boundaries.

Tests 3 distinct production workloads:
  - Workload A (Micro/Light): String processing & length parsing.
  - Workload B (Structured Agent Tool): Multi-record list aggregation & schema coercion.
  - Workload C (Numerical Compute): Black-Scholes European option pricing calculation.
"""

from __future__ import annotations

import gc
import math
import time
from typing import Any

from rich.console import Console
from rich.table import Table

from benchmarks.stats import compute_stats, format_latency
from capforge import CapForgeClient, capability


# ---------------------------------------------------------------------------
# Workload A: Micro / Light
# ---------------------------------------------------------------------------
@capability(
    id="bench_workload_micro",
    name="Micro String Processor",
    description="Micro string length and character count",
    domain="benchmark",
)
def micro_task(text: str = "") -> dict:
    return {"length": len(text), "status": "ok"}


def raw_micro_task(text: str = "") -> dict:
    return {"length": len(text), "status": "ok"}


# ---------------------------------------------------------------------------
# Workload B: Structured Agent Tool Data Aggregator
# ---------------------------------------------------------------------------
@capability(
    id="bench_workload_structured",
    name="Structured Record Aggregator",
    description="Validates and aggregates structured financial transaction records",
    domain="benchmark",
)
def structured_task(records: list[dict] | None = None) -> dict:
    items = records or []
    total = sum(float(r.get("amount", 0.0)) for r in items)
    count = len(items)
    avg = total / count if count > 0 else 0.0
    return {"count": count, "total": total, "average": avg, "status": "ok"}


def raw_structured_task(records: list[dict] | None = None) -> dict:
    items = records or []
    total = sum(float(r.get("amount", 0.0)) for r in items)
    count = len(items)
    avg = total / count if count > 0 else 0.0
    return {"count": count, "total": total, "average": avg, "status": "ok"}


# ---------------------------------------------------------------------------
# Workload C: Numerical Compute (Black-Scholes Option Pricing)
# ---------------------------------------------------------------------------
@capability(
    id="bench_workload_numerical",
    name="Black-Scholes Numerical Calculator",
    description="Calculates European call option price using Black-Scholes formula",
    domain="benchmark",
)
def numerical_task(spot: float = 100.0, strike: float = 100.0, rate: float = 0.05, vol: float = 0.2, expiry: float = 1.0) -> dict:

    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * expiry) / (vol * math.sqrt(expiry))
    d2 = d1 - vol * math.sqrt(expiry)
    # Approximation of normal CDF
    cdf_d1 = 0.5 * (1.0 + math.erf(d1 / math.sqrt(2.0)))
    cdf_d2 = 0.5 * (1.0 + math.erf(d2 / math.sqrt(2.0)))
    call_price = spot * cdf_d1 - strike * math.exp(-rate * expiry) * cdf_d2
    return {"call_price": round(call_price, 4), "status": "ok"}


def raw_numerical_task(spot: float = 100.0, strike: float = 100.0, rate: float = 0.05, vol: float = 0.2, expiry: float = 1.0) -> dict:

    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * expiry) / (vol * math.sqrt(expiry))
    d2 = d1 - vol * math.sqrt(expiry)
    cdf_d1 = 0.5 * (1.0 + math.erf(d1 / math.sqrt(2.0)))
    cdf_d2 = 0.5 * (1.0 + math.erf(d2 / math.sqrt(2.0)))
    call_price = spot * cdf_d1 - strike * math.exp(-rate * expiry) * cdf_d2
    return {"call_price": round(call_price, 4), "status": "ok"}


# ---------------------------------------------------------------------------
# Benchmark Runner
# ---------------------------------------------------------------------------
def run_benchmark(
    iterations: int = 50,
    warmup_iterations: int = 10,
    include_subprocess: bool = True,
) -> dict[str, Any]:
    console = Console()
    import logging
    logging.getLogger("capforge").setLevel(logging.ERROR)
    sample_records = [{"id": f"txn_{i}", "amount": 10.0 + (i % 20) * 1.5} for i in range(25)]

    # 1. Raw Python Baseline
    gc.collect()
    raw_times_micro: list[float] = []
    # Warmup
    for _ in range(warmup_iterations):
        _ = raw_micro_task("hello world benchmarking string")
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        _ = raw_micro_task("hello world benchmarking string")
        raw_times_micro.append((time.perf_counter_ns() - t0) / 1000.0)  # µs

    raw_times_struct: list[float] = []
    for _ in range(warmup_iterations):
        _ = raw_structured_task(sample_records)
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        _ = raw_structured_task(sample_records)
        raw_times_struct.append((time.perf_counter_ns() - t0) / 1000.0)

    raw_times_num: list[float] = []
    for _ in range(warmup_iterations):
        _ = raw_numerical_task(100.0, 105.0, 0.05, 0.25, 0.5)
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        _ = raw_numerical_task(100.0, 105.0, 0.05, 0.25, 0.5)
        raw_times_num.append((time.perf_counter_ns() - t0) / 1000.0)

    # 2. CapForge Guarded In-Process Mode
    gc.collect()
    inproc_times_micro: list[float] = []
    inproc_times_struct: list[float] = []
    inproc_times_num: list[float] = []

    with CapForgeClient(enable_trust_chain=False, sandbox_driver="inprocess") as client:
        client.register(micro_task, promote=True)
        client.register(structured_task, promote=True)
        client.register(numerical_task, promote=True)

        # Warmup
        for _ in range(warmup_iterations):
            _ = client.execute("bench_workload_micro", {"text": "hello world benchmarking string"})
            _ = client.execute("bench_workload_structured", {"records": sample_records})
            _ = client.execute("bench_workload_numerical", {"spot": 100.0, "strike": 105.0})

        for _ in range(iterations):
            t0 = time.perf_counter_ns()
            _ = client.execute("bench_workload_micro", {"text": "hello world benchmarking string"})
            inproc_times_micro.append((time.perf_counter_ns() - t0) / 1000.0)

        for _ in range(iterations):
            t0 = time.perf_counter_ns()
            _ = client.execute("bench_workload_structured", {"records": sample_records})
            inproc_times_struct.append((time.perf_counter_ns() - t0) / 1000.0)

        for _ in range(iterations):
            t0 = time.perf_counter_ns()
            _ = client.execute("bench_workload_numerical", {"spot": 100.0, "strike": 105.0})
            inproc_times_num.append((time.perf_counter_ns() - t0) / 1000.0)

    # 3. Subprocess Isolated Mode (Tested on smaller sample due to OS process spawn latency)
    subprocess_times: list[float] = []
    if include_subprocess:
        subp_iters = min(iterations, 10)
        with CapForgeClient(enable_trust_chain=False, sandbox_driver="subprocess") as subp_client:
            subp_client.register(micro_task, promote=True)
            # Warmup
            _ = subp_client.execute("bench_workload_micro", {"text": "warmup"})
            for _ in range(subp_iters):
                t0 = time.perf_counter_ns()
                _ = subp_client.execute("bench_workload_micro", {"text": "hello world benchmarking string"})
                subprocess_times.append((time.perf_counter_ns() - t0) / 1000.0)

    # Compute Statistics
    stats_raw_micro = compute_stats(raw_times_micro, unit="us")
    stats_inproc_micro = compute_stats(inproc_times_micro, unit="us")
    stats_inproc_struct = compute_stats(inproc_times_struct, unit="us")
    stats_inproc_num = compute_stats(inproc_times_num, unit="us")
    stats_subp = compute_stats(subprocess_times, unit="us") if subprocess_times else None

    overhead_inproc_p50 = stats_inproc_micro["p50"] - stats_raw_micro["p50"]

    results: dict[str, Any] = {
        "iterations": iterations,
        "raw_micro": stats_raw_micro,
        "inproc_micro": stats_inproc_micro,
        "inproc_structured": stats_inproc_struct,
        "inproc_numerical": stats_inproc_num,
        "subprocess_micro": stats_subp,
        "capforge_p50_us": stats_inproc_micro["p50"],
        "overhead_p50_us": round(overhead_inproc_p50, 2),
        "throughput_ops_sec": stats_inproc_micro["throughput_ops_sec"],
    }

    # Render Visual Summary
    table = Table(
        title="CapForge Execution Runtime Overhead Benchmark",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Workload / Execution Tier", style="bold white")
    table.add_column("Raw Python", justify="right")
    table.add_column("CapForge Guarded", justify="right", style="bold green")
    table.add_column("Overhead Delta", justify="right", style="yellow")
    table.add_column("Throughput", justify="right", style="cyan")

    table.add_row(
        "Micro Task (p50 / median)",
        format_latency(stats_raw_micro["p50"]),
        format_latency(stats_inproc_micro["p50"]),
        f"+{format_latency(overhead_inproc_p50)}",
        f"{stats_inproc_micro['throughput_ops_sec']:,.0f} ops/s",
    )
    table.add_row(
        "Micro Task (p95)",
        format_latency(stats_raw_micro["p95"]),
        format_latency(stats_inproc_micro["p95"]),
        f"+{format_latency(stats_inproc_micro['p95'] - stats_raw_micro['p95'])}",
        "-",
    )
    table.add_row(
        "Structured Agent Tool (p50)",
        format_latency(compute_stats(raw_times_struct)["p50"]),
        format_latency(stats_inproc_struct["p50"]),
        f"+{format_latency(stats_inproc_struct['p50'] - compute_stats(raw_times_struct)['p50'])}",
        f"{stats_inproc_struct['throughput_ops_sec']:,.0f} ops/s",
    )
    table.add_row(
        "Numerical Black-Scholes (p50)",
        format_latency(compute_stats(raw_times_num)["p50"]),
        format_latency(stats_inproc_num["p50"]),
        f"+{format_latency(stats_inproc_num['p50'] - compute_stats(raw_times_num)['p50'])}",
        f"{stats_inproc_num['throughput_ops_sec']:,.0f} ops/s",
    )
    if stats_subp:
        table.add_row(
            "[dim]Subprocess Sandbox Isolation (p50)[/dim]",
            format_latency(stats_raw_micro["p50"]),
            f"[dim]{format_latency(stats_subp['p50'])}[/dim]",
            f"[dim]+{format_latency(stats_subp['p50'] - stats_raw_micro['p50'])} (OS barrier)[/dim]",
            f"[dim]{stats_subp['throughput_ops_sec']:,.0f} ops/s[/dim]",
        )

    console.print(table)
    return results


if __name__ == "__main__":
    run_benchmark(iterations=100)

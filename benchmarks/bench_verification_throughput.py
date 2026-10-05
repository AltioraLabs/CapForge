"""Benchmark: Verification Throughput & Multi-Thread Concurrency Scaling.

Measures the sustained validation throughput of the CapForge 5-Level Verification Battery:
  - L0 Security Gate (CodeGuardian AST static analysis)
  - L1 Structural & Formal Invariant Check
  - L2 Functional Execution in Isolated Sandbox
  - L3 Property Fuzzing & Generalization
  - L4 Historical Zero-Regression Battery

Evaluates multi-threaded concurrency scaling (1 vs 2 vs 4 worker threads) and
per-capability validation latency percentiles (p50, p95, p99).
"""

from __future__ import annotations

import concurrent.futures
import logging
import sys
import time
from pathlib import Path
from typing import Any

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rich.console import Console
from rich.table import Table

from benchmarks.stats import compute_stats, format_ci95
from capforge.core.models import (
    Capability,
    CapabilityStatus,
    TestCase,
    TestType,
    ToolPermissions,
)
from capforge.verification.evaluator import CapabilityEvaluator
from capforge.verification.sandbox import InProcessSandboxDriver, SandboxRunner


def _create_sample_capability(idx: int) -> Capability:
    """Generate a valid candidate capability with multi-tier tests."""
    factor = idx % 5 + 1
    expected_smoke = 5 * factor
    expected_boundary = 0 * factor

    return Capability(
        id=f"throughput_test_cap_{idx}",
        name=f"Throughput Cap {idx}",
        description="Benchmark capability for verification throughput testing",
        code_body=(
            f"def execute(x=10, **kw):\n"
            f"    factor = {factor}\n"
            f"    return {{'result': x * factor, 'status': 'ok'}}\n"
        ),
        permissions=ToolPermissions(),
        status=CapabilityStatus.CANDIDATE,
        verification_tests=[
            TestCase(
                id=f"test_{idx}_smoke",
                name="Smoke Test",
                test_type=TestType.HAPPY_PATH,
                inputs={"x": 5},
                assert_expression=f"output.get('result') == {expected_smoke} and output.get('status') == 'ok'",
            ),
            TestCase(
                id=f"test_{idx}_boundary",
                name="Boundary Test",
                test_type=TestType.EDGE_CASE,
                inputs={"x": 0},
                assert_expression=f"output.get('result') == {expected_boundary} and output.get('status') == 'ok'",
            ),
        ],
    )


def evaluate_batch(
    capabilities: list[Capability],
    concurrency: int = 4,
    use_inprocess_sandbox: bool = True,
) -> tuple[int, float, list[float]]:
    """Execute evaluation battery over a batch of capabilities with worker threads."""
    driver = InProcessSandboxDriver() if use_inprocess_sandbox else None
    sandbox = SandboxRunner(driver=driver) if driver else None
    evaluator = CapabilityEvaluator(sandbox=sandbox)

    latencies_ms: list[float] = []
    passed_count = 0

    t0 = time.perf_counter_ns()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_to_start = {executor.submit(evaluator.evaluate, cap): time.perf_counter_ns() for cap in capabilities}
        for future in concurrent.futures.as_completed(future_to_start):
            res = future.result()
            lat_ms = (time.perf_counter_ns() - future_to_start[future]) / 1e6
            latencies_ms.append(lat_ms)
            if res.passed:
                passed_count += 1

    total_time_sec = (time.perf_counter_ns() - t0) / 1e9
    return passed_count, total_time_sec, latencies_ms


def run_benchmark(
    capability_count: int = 30,
    concurrency_levels: list[int] | None = None,
    use_inprocess_sandbox: bool = True,
) -> dict[str, Any]:
    console = Console()
    logging.getLogger("capforge").setLevel(logging.ERROR)

    concurrency_levels = concurrency_levels or [1, 2, 4]
    capabilities = [_create_sample_capability(i) for i in range(capability_count)]

    # Warmup
    _ = evaluate_batch(capabilities[:2], concurrency=2, use_inprocess_sandbox=use_inprocess_sandbox)

    results_by_concurrency: dict[int, dict[str, Any]] = {}
    baseline_throughput = 0.0

    table = Table(
        title="CapForge Verification Battery Throughput & Concurrency Scaling",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Concurrency (Threads)", style="bold cyan", justify="center")
    table.add_column("Total Time", justify="right")
    table.add_column("Latency (p50 / p95)", justify="right")
    table.add_column("Throughput (caps/sec)", justify="right")
    table.add_column("Throughput (caps/min)", justify="right", style="bold green")
    table.add_column("Efficiency", justify="center", style="yellow")
    table.add_column("Pass Rate", justify="center", style="green")

    for c in concurrency_levels:
        passed, duration_sec, latencies = evaluate_batch(
            capabilities,
            concurrency=c,
            use_inprocess_sandbox=use_inprocess_sandbox,
        )
        stats = compute_stats(latencies, unit="ms")
        caps_per_sec = capability_count / duration_sec if duration_sec > 0 else 0.0
        caps_per_min = caps_per_sec * 60.0

        if c == 1:
            baseline_throughput = caps_per_sec
            efficiency_str = "100% (baseline)"
        else:
            efficiency = (caps_per_sec / (baseline_throughput * c)) * 100.0 if baseline_throughput > 0 else 100.0
            efficiency_str = f"{efficiency:.0f}%"

        pass_rate_str = f"{passed}/{capability_count} (100%)" if passed == capability_count else f"{passed}/{capability_count}"

        results_by_concurrency[c] = {
            "threads": c,
            "passed_count": passed,
            "pass_rate_pct": (passed / capability_count) * 100.0 if capability_count > 0 else 0.0,
            "total_time_sec": round(duration_sec, 2),
            "caps_per_second": round(caps_per_sec, 1),
            "caps_per_minute": round(caps_per_min, 1),
            "latency_p50_ms": stats["p50"],
            "latency_p95_ms": stats["p95"],
            "latency_mean_ms": stats["mean"],
            "latency_ci95": format_ci95(stats, "ms"),
        }

        table.add_row(
            f"{c} worker(s)",
            f"{duration_sec:.2f} s",
            f"{stats['p50']:.1f} / {stats['p95']:.1f} ms [{stats['ci95_low']:.1f}–{stats['ci95_high']:.1f}]",
            f"{caps_per_sec:.1f} caps/s",
            f"[bold green]{caps_per_min:,.0f} caps/min[/bold green]",
            efficiency_str,
            f"[green]{pass_rate_str}[/green]" if passed == capability_count else f"[red]{pass_rate_str}[/red]",
        )

    console.print(table)

    target_concurrency = max(concurrency_levels)
    best = results_by_concurrency[target_concurrency]

    return {
        "capability_count": capability_count,
        "results_by_concurrency": results_by_concurrency,
        "concurrency": target_concurrency,
        "passed_count": best["passed_count"],
        "total_time_sec": best["total_time_sec"],
        "caps_per_second": best["caps_per_second"],
        "caps_per_minute": best["caps_per_minute"],
        "avg_latency_ms": best["latency_mean_ms"],
    }


if __name__ == "__main__":
    run_benchmark(capability_count=30, concurrency_levels=[1, 2, 4])

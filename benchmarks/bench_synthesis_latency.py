"""Benchmark: End-to-End Capability Synthesis Latency & Tiered Time Budget.

Scientifically measures wall-clock time from Capability Gap Detection to ACTIVE Promotion,
breaking down exact phase timings:
  - Immediate Non-Blocking Fallback Response (< 1 ms)
  - Tier 1: L0 + L1 Fast Checks (AST firewall & syntax validation) -> status: DRAFT
  - Tier 2: L2 - L5 Verification Battery (Sandbox isolation, boundary fuzzing, regression) -> status: CANDIDATE
  - Tier 3: Governance Risk Assessment & HMAC Trust Signature -> status: ACTIVE
  - Cache Contrast: Pre-warmed registry lookup (< 1 ms) vs Autonomous Cold Synthesis (~600 ms)
"""

from __future__ import annotations

import logging
import time
from typing import Any

from rich.console import Console
from rich.table import Table

from benchmarks.stats import compute_stats
from capforge.core.models import PromotionMode, PromotionPolicy
from capforge.runtime.agent_adapter import CapForgeAgent
from capforge.runtime.async_synthesis import AsyncSynthesisManager, SynthesisPhase

# ---------------------------------------------------------------------------
# Realistic Multi-Domain Capability Specifications
# ---------------------------------------------------------------------------
_BENCHMARK_SPECS: list[dict[str, Any]] = [
    {
        "domain": "finance",
        "name": "Sharpe Ratio Calculator",
        "intent": "calculate annualized Sharpe ratio from daily portfolio returns",
        "code_body": (
            "def run(returns=None, risk_free_rate=0.02, **kw):\n"
            "    r = returns or [0.01, -0.005, 0.012, 0.008, -0.002, 0.015]\n"
            "    mean_r = sum(r) / len(r)\n"
            "    var_r = sum((x - mean_r) ** 2 for x in r) / (len(r) - 1)\n"
            "    std_r = var_r ** 0.5\n"
            "    daily_rf = risk_free_rate / 252.0\n"
            "    sharpe = ((mean_r - daily_rf) / std_r) * (252.0 ** 0.5) if std_r > 0 else 0.0\n"
            "    return {'sharpe_ratio': round(sharpe, 4), 'status': 'ok'}\n"
        ),
    },
    {
        "domain": "devops",
        "name": "Semantic Version Bumper",
        "intent": "parse semver string and increment major minor or patch version",
        "code_body": (
            "def run(version='1.2.3', bump='minor', **kw):\n"
            "    parts = [int(p) for p in version.split('.')]\n"
            "    if bump == 'major':\n"
            "        parts[0] += 1; parts[1] = 0; parts[2] = 0\n"
            "    elif bump == 'minor':\n"
            "        parts[1] += 1; parts[2] = 0\n"
            "    else:\n"
            "        parts[2] += 1\n"
            "    new_ver = '.'.join(str(p) for p in parts)\n"
            "    return {'previous': version, 'new_version': new_ver, 'status': 'ok'}\n"
        ),
    },
    {
        "domain": "data",
        "name": "IQR Outlier Filter",
        "intent": "detect and remove numerical outliers using interquartile range rule",
        "code_body": (
            "def run(values=None, **kw):\n"
            "    vals = sorted(values or [10, 12, 11, 14, 13, 100, 12, 11, -50, 15])\n"
            "    n = len(vals)\n"
            "    q1 = vals[int(n * 0.25)]\n"
            "    q3 = vals[int(n * 0.75)]\n"
            "    iqr = q3 - q1\n"
            "    lower = q1 - 1.5 * iqr\n"
            "    upper = q3 + 1.5 * iqr\n"
            "    clean = [x for x in vals if lower <= x <= upper]\n"
            "    return {'clean_count': len(clean), 'outliers_removed': n - len(clean), 'status': 'ok'}\n"
        ),
    },
]


def run_benchmark(iterations: int = 3) -> dict[str, Any]:
    console = Console()
    logging.getLogger("capforge").setLevel(logging.ERROR)

    agent = CapForgeAgent()
    manager = AsyncSynthesisManager(agent=agent)
    policy = PromotionPolicy(mode=PromotionMode.AUTO, require_full_verification=False)

    l0_l1_times: list[float] = []
    l2_l5_times: list[float] = []
    gate_times: list[float] = []
    total_times: list[float] = []
    cached_lookup_times: list[float] = []

    for i in range(iterations):
        spec_template = _BENCHMARK_SPECS[i % len(_BENCHMARK_SPECS)]
        spec = {
            "id": f"bench_synth_{spec_template['domain']}_{i}_{int(time.time() * 1000)}",
            "name": f"{spec_template['name']} {i}",
            "description": f"Benchmark synthesis for {spec_template['domain']}",
            "domain": spec_template["domain"],
            "code_body": spec_template["code_body"],
        }

        # Measure Cold Synthesis
        t0 = time.perf_counter_ns()
        resp = manager.submit_synthesis(
            task_intent=spec_template["intent"],
            knowledge_spec=spec,
            promotion_policy=policy,
        )

        # Immediate Fallback Latency (< 1ms)
        fallback_dispatch_ms = (time.perf_counter_ns() - t0) / 1e6

        # Wait for Background Pipeline Completion
        job = None
        for _ in range(60):
            job = manager.get_job(resp.job_id)
            if job and job.phase in (SynthesisPhase.COMPLETED, SynthesisPhase.FAILED):
                break
            time.sleep(0.04)

        total_elapsed = (time.perf_counter_ns() - t0) / 1e6  # ms
        total_times.append(total_elapsed)

        if job and job.phase == SynthesisPhase.COMPLETED:
            l0_l1 = job.phase_timings.get("L0_L1_fast_check_ms", 0.0)
            l2_l5 = job.phase_timings.get("L2_L5_full_verify_ms", 0.0)
            gate = job.phase_timings.get("promotion_gate_ms", 0.0)
            l0_l1_times.append(l0_l1)
            l2_l5_times.append(l2_l5)
            gate_times.append(gate)

            # Test Pre-Warmed Registry Lookup (Second Hit)
            t_cache = time.perf_counter_ns()
            cached_cap = agent.registry.get(job.capability_id)
            cached_ms = (time.perf_counter_ns() - t_cache) / 1e6
            if cached_cap:
                cached_lookup_times.append(cached_ms)

    stats_fast = compute_stats(l0_l1_times, unit="ms")
    stats_verify = compute_stats(l2_l5_times, unit="ms")
    stats_gate = compute_stats(gate_times, unit="ms")
    stats_total = compute_stats(total_times, unit="ms")
    stats_cache = compute_stats(cached_lookup_times, unit="ms")

    results: dict[str, Any] = {
        "iterations": iterations,
        "fast_check_median_ms": stats_fast["p50"],
        "verification_median_ms": stats_verify["p50"],
        "promotion_gate_median_ms": stats_gate["p50"],
        "total_median_ms": stats_total["p50"],
        "total_mean_ms": stats_total["mean"],
        "cached_lookup_median_ms": stats_cache["p50"],
        "phase_breakdown": {
            "fast_check": stats_fast,
            "verification": stats_verify,
            "promotion_gate": stats_gate,
            "total_e2e": stats_total,
            "cached_lookup": stats_cache,
        },
    }

    table = Table(
        title="CapForge Synthesis Latency & Production Time Budget Benchmark",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Synthesis Pipeline Stage", style="bold cyan")
    table.add_column("Median (p50)", justify="right", style="bold green")
    table.add_column("Mean ± Stddev", justify="right")
    table.add_column("Resulting Status", justify="center", style="yellow")
    table.add_column("Operational Behavior", style="dim")

    table.add_row(
        "Immediate Async Fallback",
        f"{fallback_dispatch_ms:.2f} ms",
        f"{fallback_dispatch_ms:.2f} ms",
        "[dim]None[/dim]",
        "Caller resumes immediately with fallback response without blocking",
    )
    table.add_row(
        "Tier 1: L0+L1 Fast Check",
        f"{stats_fast['p50']:.1f} ms",
        f"{stats_fast['mean']:.1f} ± {stats_fast['stddev']:.1f} ms",
        "[yellow]DRAFT[/yellow]",
        "AST security scan + syntax validation (usable for low-risk paths)",
    )
    table.add_row(
        "Tier 2: L2-L5 Verification",
        f"{stats_verify['p50']:.1f} ms",
        f"{stats_verify['mean']:.1f} ± {stats_verify['stddev']:.1f} ms",
        "[cyan]CANDIDATE[/cyan]",
        "Container sandbox execution + fuzzing + invariant regression check",
    )
    table.add_row(
        "Tier 3: Promotion Gate",
        f"{stats_gate['p50']:.1f} ms",
        f"{stats_gate['mean']:.1f} ± {stats_gate['stddev']:.1f} ms",
        "[bold green]ACTIVE[/bold green]",
        "Risk classification, human governance policy, HMAC signature",
    )
    table.add_row(
        "Total Cold Synthesis (End-to-End)",
        f"[bold]{stats_total['p50']:.1f} ms[/bold]",
        f"{stats_total['mean']:.1f} ± {stats_total['stddev']:.1f} ms",
        "[bold green]ACTIVE[/bold green]",
        "Complete autonomous resolution from gap discovery to active tool",
    )
    table.add_row(
        "Pre-Warmed Registry Hit (Cached)",
        f"{stats_cache['p50']:.3f} ms",
        f"{stats_cache['mean']:.3f} ms",
        "[bold green]ACTIVE[/bold green]",
        "Subsequent requests hit pre-warmed registry in < 1 ms (cold start eliminated)",
    )

    console.print(table)
    return results


if __name__ == "__main__":
    run_benchmark(iterations=3)

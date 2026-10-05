"""Comprehensive Test Battery for CapForge Advanced Features.

Verifies:
1. Runtime Profiling & Bottleneck Detection (SLA violations & OPTIMIZATION_GAP emission).
2. Python-to-Rust / C Hot-Path Transpiler & PyO3 Blueprint Generation.
3. Continuous Test Expansion & AST Mutation Testing Engine.
4. Formal Verification & SMT Invariant Prover (Z3 & SymPy).
5. Bi-Directional Model Context Protocol (MCP) Server & SSE Transport.
"""

from __future__ import annotations

import os

os.environ["CAPFORGE_DEV_MODE"] = "true"  # noqa: E402

import pytest
from fastapi.testclient import TestClient

from capforge.core.models import Capability, ParameterSpec, TestCase, TestType
from capforge.mcp.server import CapForgeMCPServer
from capforge.optimization.profiler import RuntimeProfiler
from capforge.optimization.transpiler import HotPathAnalyzer, RustTranspiler
from capforge.registry.store import CapabilityRegistry
from capforge.server.app import app
from capforge.verification.formal import (
    PreExecutionContractChecker,
    SMTInvariantVerifier,
)
from capforge.verification.mutation import MutationEngine

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_monte_carlo_capability() -> Capability:
    """A capability with iterative simulation hot path."""
    code = """
def execute(inputs: dict) -> dict:
    import math
    returns = inputs.get("returns", [0.01, -0.02, 0.015, -0.005, 0.02])
    num_simulations = inputs.get("num_simulations", 100)
    confidence = inputs.get("confidence", 0.95)

    if not returns:
        return {"status": "FAILED", "error": "Empty returns"}

    # Monte Carlo simulation loop
    mean_ret = sum(returns) / len(returns)
    sim_results = []
    for i in range(num_simulations):
        val = mean_ret * (1.0 + (i % 5) * 0.01)
        sim_results.append(val)

    sim_results.sort()
    cutoff_idx = int((1.0 - confidence) * len(sim_results))
    var_estimate = abs(sim_results[min(cutoff_idx, len(sim_results) - 1)])

    return {
        "status": "SUCCESS",
        "var_estimate": round(var_estimate, 4),
        "simulations_run": num_simulations,
    }
"""
    return Capability(
        id="monte_carlo_var_sim",
        name="Monte Carlo VaR Simulator",
        description="Simulates portfolio returns to estimate tail risk via Monte Carlo",
        domain="risk",
        code_body=code,
        inputs={
            "returns": ParameterSpec(name="returns", type="list[float]", required=False, default=[0.01, -0.02]),
            "num_simulations": ParameterSpec(name="num_simulations", type="int", required=False, default=50),
            "confidence": ParameterSpec(name="confidence", type="float", required=False, default=0.95),
        },
        outputs={
            "status": ParameterSpec(name="status", type="string"),
            "var_estimate": ParameterSpec(name="var_estimate", type="float"),
        },
        verification_tests=[
            TestCase(
                id="test_mc_basic",
                name="Basic Monte Carlo Test",
                test_type=TestType.HAPPY_PATH,
                inputs={"returns": [0.01, -0.02, 0.03], "num_simulations": 20},
                assert_expression="output['status'] == 'SUCCESS' and output['var_estimate'] >= 0",
            )
        ],
    )


# ---------------------------------------------------------------------------
# 1. Runtime Profiling & Bottleneck Detection Tests
# ---------------------------------------------------------------------------


def test_runtime_profiler_telemetry_and_optimization_gap():
    """Verify latency percentile calculation and OPTIMIZATION_GAP emission upon SLA breach."""
    custom_profiler = RuntimeProfiler(default_latency_sla_ms=100.0, min_samples_before_audit=5)

    # Record 10 fast executions within SLA
    for i in range(10):
        custom_profiler.record_execution("fast_tool", "1.0.0", duration_ms=45.0 + i)

    gaps = custom_profiler.detect_optimization_gaps()
    assert len(gaps) == 0, "No gaps expected when executing within SLA"

    # Record slow executions that violate 100ms SLA
    for i in range(10):
        custom_profiler.record_execution("heavy_monte_carlo", "1.0.0", duration_ms=450.0 + (i * 20))

    gaps = custom_profiler.detect_optimization_gaps()
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap.capability_id == "heavy_monte_carlo"
    assert gap.reason == "LATENCY_BOTTLENECK"
    assert gap.suggested_action == "JIT_COMPILE_RUST_C"
    assert gap.p95_latency_ms > 100.0
    assert gap.gap_detected is True
    assert "exceeds SLA" in gap.rationale


# ---------------------------------------------------------------------------
# 2. Python-to-Rust / Hot-Path Transpiler Tests
# ---------------------------------------------------------------------------


def test_hot_path_analyzer_and_rust_transpiler(sample_monte_carlo_capability):
    """Verify AST hot path detection, PyO3 blueprint generation, and capability optimization."""
    analyzer = HotPathAnalyzer()
    report = analyzer.analyze(sample_monte_carlo_capability.code_body)

    assert report.has_loops is True
    assert report.has_simulations is True
    assert "O(SIMULATIONS*N)" in report.estimated_complexity

    transpiler = RustTranspiler()
    rust_blueprint = transpiler.generate_rust_pyo3_blueprint(sample_monte_carlo_capability)

    assert "use pyo3::prelude::*;" in rust_blueprint
    assert "monte_carlo_var_sim" in rust_blueprint
    assert "#[pyfunction]" in rust_blueprint

    # Transpile and verify functional equivalence
    success, optimized_cap, diag = transpiler.transpile_and_optimize(sample_monte_carlo_capability)
    assert success is True
    assert "optimized" in optimized_cap.tags
    assert "rust_pyo3_ready" in optimized_cap.tags
    assert "compiled_kernel" in optimized_cap.features
    assert "opt" in optimized_cap.version


# ---------------------------------------------------------------------------
# 3. Continuous Test Expansion & Mutation Testing Tests
# ---------------------------------------------------------------------------


def test_mutation_engine_and_test_hardening(sample_monte_carlo_capability):
    """Verify AST mutants generation, kill score computation, and test expansion."""
    engine = MutationEngine()
    mutants = engine.generate_mutants(sample_monte_carlo_capability.code_body, max_mutants=10)

    assert len(mutants) > 0
    assert any(m.operator_name in ("COMPARISON_FLIP", "ARITHMETIC_SWAP") for m in mutants)

    # Run evaluation and auto-expand test cases
    initial_test_count = len(sample_monte_carlo_capability.verification_tests)
    report, hardened_cap = engine.evaluate_and_expand(sample_monte_carlo_capability)

    assert report.total_mutants > 0
    assert 0.0 <= report.mutation_score <= 1.0
    assert len(hardened_cap.verification_tests) >= initial_test_count
    assert "mutation_hardened" in hardened_cap.tags


# ---------------------------------------------------------------------------
# 4. Formal Verification & SMT Invariant Prover Tests
# ---------------------------------------------------------------------------


def test_pre_execution_contract_checker_safe(sample_monte_carlo_capability):
    """Verify static contract checker on safe capability."""
    checker = PreExecutionContractChecker()
    ok, violations = checker.check_contracts(sample_monte_carlo_capability)
    assert ok is True
    assert len(violations) == 0


def test_pre_execution_contract_checker_catches_unbounded_recursion():
    """Verify static contract checker blocks unbounded recursion."""
    bad_code = """
def execute(inputs: dict) -> dict:
    return execute(inputs)  # Unbounded self-call with no base case
"""
    bad_cap = Capability(
        id="infinite_recurse",
        name="Infinite Recurse",
        description="Bad recursive capability",
        code_body=bad_code,
    )
    checker = PreExecutionContractChecker()
    ok, violations = checker.check_contracts(bad_cap)
    assert ok is False
    assert any("recursion" in v.lower() for v in violations)


def test_pre_execution_contract_checker_catches_infinite_while_loop():
    """Verify static contract checker blocks while True with no exit."""
    bad_code = """
def execute(inputs: dict) -> dict:
    x = 1
    while True:
        x += 1
    return {"status": "SUCCESS"}
"""
    bad_cap = Capability(
        id="infinite_loop",
        name="Infinite Loop",
        description="Bad while loop",
        code_body=bad_code,
    )
    checker = PreExecutionContractChecker()
    ok, violations = checker.check_contracts(bad_cap)
    assert ok is False
    assert any("infinite loop" in v.lower() for v in violations)


def test_smt_invariant_verifier_with_z3_and_sympy(sample_monte_carlo_capability):
    """Verify Z3 and SymPy formal mathematical proof verification.

    Solvers are optional dependencies: without them the verifier degrades to
    static contracts only (asserted here); with them the full SMT battery runs.
    """
    sympy = pytest.importorskip("sympy", reason="optional SMT dependency not installed")
    pytest.importorskip("z3", reason="optional SMT dependency not installed")
    assert sympy is not None
    verifier = SMTInvariantVerifier()
    report = verifier.verify_invariants(sample_monte_carlo_capability)

    assert report.passed is True
    assert report.static_contracts_passed is True
    assert report.smt_invariants_passed is True
    assert len(report.invariants_proven) >= 3
    assert any("monotonicity" in p.lower() for p in report.invariants_proven)
    assert any("confidence" in p.lower() for p in report.invariants_proven)
    assert any("finiteness" in p.lower() for p in report.invariants_proven)


def test_smt_verifier_degrades_without_solvers(sample_monte_carlo_capability):
    """Without sympy/z3 the verifier must skip SMT (not crash), keeping static contracts."""
    from capforge.verification import formal as formal_module

    if formal_module._SOLVERS_AVAILABLE:
        pytest.skip("solvers installed; degradation path not exercised")
    report = formal_module.formal_verifier.verify_invariants(sample_monte_carlo_capability)
    assert report.static_contracts_passed is True
    assert report.smt_invariants_passed is False
    assert "sympy" in report.diagnostics or "z3" in report.diagnostics


def test_smt_generic_non_financial_capability():
    """Verify SMT theorem proving on an arbitrary non-financial capability.

    Proves test assertion consistency, zero-division safety, and SymPy finiteness
    without requiring or forcing quantitative/financial domain assumptions.
    """
    pytest.importorskip("sympy", reason="optional SMT dependency not installed")
    pytest.importorskip("z3", reason="optional SMT dependency not installed")

    generic_cap = Capability(
        id="text_token_counter",
        name="Token Counter",
        description="Calculates tokens and token ratios",
        domain="nlp",
        code_body="""
def execute(inputs: dict) -> dict:
    text = inputs.get("text", "")
    words = text.split()
    count = len(words)
    total_len = sum(len(w) for w in words)
    avg_len = total_len / count if count > 0 else 0.0
    return {"status": "SUCCESS", "token_count": count, "avg_token_len": avg_len}
""",
        inputs={"text": ParameterSpec(name="text", type="string", required=True)},
        outputs={"status": ParameterSpec(name="status", type="string")},
        verification_tests=[
            TestCase(
                id="test_token_positive",
                name="Positive tokens test",
                test_type=TestType.HAPPY_PATH,
                inputs={"text": "capforge formal verification"},
                assert_expression="output['status'] == 'SUCCESS' and output['token_count'] > 0 and output['avg_token_len'] >= 0.0",
            )
        ],
    )

    verifier = SMTInvariantVerifier()
    report = verifier.verify_invariants(generic_cap)

    assert report.passed is True
    assert report.static_contracts_passed is True
    assert report.smt_invariants_passed is True
    assert len(report.invariants_proven) >= 2
    assert any("assertion invariant" in p.lower() for p in report.invariants_proven)
    assert any("zero-division safety" in p.lower() for p in report.invariants_proven)


# ---------------------------------------------------------------------------
# 5. Bi-Directional Model Context Protocol (MCP) Tests
# ---------------------------------------------------------------------------


def test_mcp_server_dynamic_capability_exposure(sample_monte_carlo_capability, tmp_path):
    """Verify every registered capability is dynamically exposed as an MCP tool."""
    db_file = tmp_path / "mcp_test.db"
    registry = CapabilityRegistry(db_path=db_file)
    registry.register(sample_monte_carlo_capability)

    server = CapForgeMCPServer(registry=registry)
    tools = server.get_tool_definitions()

    tool_names = [t["name"] for t in tools]
    # Meta tools
    assert "capforge_search_capabilities" in tool_names
    assert "capforge_execute_capability" in tool_names
    # Dynamically registered capability tool
    expected_tool_name = f"capforge_{sample_monte_carlo_capability.id}"
    assert expected_tool_name in tool_names

    # Check input schema matches parameters
    dynamic_tool = next(t for t in tools if t["name"] == expected_tool_name)
    assert dynamic_tool["inputSchema"]["type"] == "object"
    assert "returns" in dynamic_tool["inputSchema"]["properties"]
    assert "confidence" in dynamic_tool["inputSchema"]["properties"]

    # Execute dynamic capability through MCP tools/call
    msg = {
        "jsonrpc": "2.0",
        "id": "req-1",
        "method": "tools/call",
        "params": {
            "name": expected_tool_name,
            "arguments": {"returns": [0.02, -0.01, 0.03], "num_simulations": 10},
        },
    }
    resp = server.handle_message(msg)
    assert "result" in resp
    content = resp["result"]["content"][0]["text"]
    assert "SUCCESS" in content


def test_mcp_sse_endpoint_fastapi():
    """Verify MCP SSE endpoint returns standard text/event-stream headers."""
    client = TestClient(app)
    # Test message handler
    msg_payload = {
        "jsonrpc": "2.0",
        "id": "ping-1",
        "method": "ping",
        "params": {},
    }
    resp = client.post("/v1/mcp/messages", json=msg_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == "ping-1"

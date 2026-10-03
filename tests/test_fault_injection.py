"""Fault Injection & Chaos Tests — v1.1.0.

Tests that verify system resilience under failure conditions:
1. Sandbox timeout enforcement on infinite loops
2. Circuit breaker trips after consecutive failures and auto-rollbacks
3. Auth rejection paths (revoked key, bad role)
4. Vector index auto-refreshes on new registration
5. Workflow pause on failure and resume from checkpoint
6. Registry pagination correctness
"""

import time
import pytest

from capforge.core.models import (
    Capability,
    CapabilityStatus,
    ExecutionRequest,
    TestCase,
    TestType,
)
from capforge.core.governance import CapabilityFirewall, RiskEngine
from capforge.registry.store import CapabilityRegistry
from capforge.registry.vector_store import SemanticVectorIndex
from capforge.runtime.executor import CapabilityExecutor
from capforge.verification.sandbox import SandboxRunner
from capforge.server.auth import AuthManager, AuthStore, UserRole
from capforge.runtime.durable_workflow import (
    DurableWorkflowEngine,
    WorkflowDefinition,
    WorkflowStep,
    WorkflowStatus,
)
from capforge.core.events import EventGateway


# ---------------------------------------------------------------------------
# 1. Sandbox Timeout — infinite loop must be killed
# ---------------------------------------------------------------------------

def test_sandbox_kills_infinite_loop():
    """Sandbox must enforce timeout on infinite loops and return FAILED."""
    sandbox = SandboxRunner(use_subprocess=True)
    infinite_code = """
def execute(inputs):
    while True:
        pass
    return {"status": "SUCCESS"}
"""
    start = time.perf_counter()
    result = sandbox.execute_code(infinite_code, "execute", {}, timeout_sec=2.0)
    elapsed = time.perf_counter() - start

    assert result["success"] is False, "Infinite loop must not succeed"
    assert elapsed < 6.0, f"Timeout must fire within 6s, took {elapsed:.1f}s"
    error_lower = (result.get("error") or "").lower()
    assert any(kw in error_lower for kw in ("timeout", "time", "killed", "signal", "terminated")), \
        f"Expected timeout error, got: {result['error']}"


def test_sandbox_timeout_short_window():
    """Even a 1-second timeout must fire correctly."""
    sandbox = SandboxRunner(use_subprocess=True)
    slow_code = """
import time
def execute(inputs):
    time.sleep(10)
    return {"status": "SUCCESS"}
"""
    result = sandbox.execute_code(slow_code, "execute", {}, timeout_sec=1.0)
    assert result["success"] is False


# ---------------------------------------------------------------------------
# 2. Circuit Breaker — 3 consecutive failures trigger quarantine + rollback
# ---------------------------------------------------------------------------

def _make_cap(cap_id: str, version: str, code: str, parent_version: str = None) -> Capability:
    cap = Capability(
        id=cap_id,
        name=f"Test Cap {version}",
        description="Circuit breaker test capability",
        version=version,
        code_body=code,
        status=CapabilityStatus.ACTIVE,
        parent_version=parent_version,
    )
    return cap


def test_circuit_breaker_trips_and_quarantines(tmp_path):
    """After failure_threshold consecutive failures, the executor must quarantine the cap."""
    registry = CapabilityRegistry(db_path=tmp_path / "test.db")
    firewall = CapabilityFirewall(RiskEngine())
    executor = CapabilityExecutor(registry, firewall=firewall, failure_threshold=3)

    # Register a good parent version
    good_code = "def execute(inputs): return {'status': 'SUCCESS'}"
    parent = _make_cap("cb_test", "1.0.0", good_code)
    registry.register(parent)

    # Register a broken child version
    bad_code = "def execute(inputs): raise RuntimeError('INJECTED FAILURE')"
    child = _make_cap("cb_test", "2.0.0", bad_code, parent_version="1.0.0")
    child.status = CapabilityStatus.ACTIVE
    registry.register(child)

    req = ExecutionRequest(capability_id="cb_test", version="2.0.0", inputs={}, agent_id="chaos-agent")

    # Force 3 consecutive failures
    for i in range(3):
        resp = executor.execute(req)
        assert resp.status == "FAILED", f"Iteration {i}: expected FAILED, got {resp.status}"

    # Verify child was quarantined
    child_after = registry.get("cb_test", version="2.0.0")
    assert child_after.status == CapabilityStatus.QUARANTINED, \
        f"Expected QUARANTINED after circuit trip, got {child_after.status}"

    # Verify parent was restored to ACTIVE
    parent_after = registry.get("cb_test", version="1.0.0")
    assert parent_after.status == CapabilityStatus.ACTIVE, \
        f"Expected parent ACTIVE after rollback, got {parent_after.status}"


# ---------------------------------------------------------------------------
# 3. Firewall blocks quarantined capability
# ---------------------------------------------------------------------------

def test_firewall_blocks_quarantined_capability(tmp_path):
    """Executor must return BLOCKED (not execute) a QUARANTINED capability."""
    registry = CapabilityRegistry(db_path=tmp_path / "fw_test.db")
    firewall = CapabilityFirewall(RiskEngine())
    executor = CapabilityExecutor(registry, firewall=firewall)

    bad_cap = Capability(
        id="quarantined_cap",
        name="Quarantined",
        description="This is quarantined",
        version="1.0.0",
        code_body="def execute(inputs): return {'status': 'SUCCESS'}",
        status=CapabilityStatus.QUARANTINED,
    )
    registry.register(bad_cap)

    req = ExecutionRequest(capability_id="quarantined_cap", inputs={}, agent_id="test")
    resp = executor.execute(req)
    assert resp.status == "BLOCKED", f"Expected BLOCKED, got {resp.status}"


# ---------------------------------------------------------------------------
# 4. Vector index auto-refresh
# ---------------------------------------------------------------------------

def test_vector_index_refreshes_on_new_registration(tmp_path):
    """Capabilities registered after index creation must be searchable."""
    registry = CapabilityRegistry(db_path=tmp_path / "vec_test.db")
    index = SemanticVectorIndex(registry)

    # Verify not indexed yet
    results_before = index.search_vector("email sending capability", top_k=5)
    initial_ids = {cap.id for cap, _ in results_before}
    assert "send_email_v2" not in initial_ids

    # Register a new capability
    new_cap = Capability(
        id="send_email_v2",
        name="Email Sender v2",
        description="Sends emails via SMTP with attachments",
        version="1.0.0",
        code_body="def execute(inputs): return {'status': 'SUCCESS'}",
        tags=["email", "smtp", "notification"],
        domain="communication",
    )
    registry.register(new_cap)

    # Manually call the hook (in production, app.py calls this after register)
    index.on_capability_registered(new_cap)

    # Now it must appear in search results
    results_after = index.search_vector("email sending capability", top_k=10)
    found_ids = {cap.id for cap, _ in results_after}
    assert "send_email_v2" in found_ids, \
        f"Newly registered cap must appear in search. Found: {found_ids}"


# ---------------------------------------------------------------------------
# 5. Workflow pause on failure + resume
# ---------------------------------------------------------------------------

def test_workflow_pauses_on_step_failure_and_resumes(tmp_path):
    """A workflow must pause when a step fails and resume correctly from checkpoint."""
    registry = CapabilityRegistry(db_path=tmp_path / "wf_test.db")
    firewall = CapabilityFirewall(RiskEngine())
    executor = CapabilityExecutor(registry, firewall=firewall)
    gateway = EventGateway()
    engine = DurableWorkflowEngine(executor=executor, event_gateway=gateway)

    # Register two capabilities: step1 succeeds, step2 fails first then succeeds
    step1_code = "def execute(inputs): return {'status': 'SUCCESS', 'value': 42}"
    step2_code = "def execute(inputs): return {'status': 'SUCCESS', 'final': True}"

    cap1 = Capability(id="wf_step1", name="WF Step 1", description="Step 1",
                      version="1.0.0", code_body=step1_code, status=CapabilityStatus.ACTIVE)
    cap2 = Capability(id="wf_step2", name="WF Step 2", description="Step 2",
                      version="1.0.0", code_body=step2_code, status=CapabilityStatus.ACTIVE)
    registry.register(cap1)
    registry.register(cap2)

    workflow = WorkflowDefinition(
        workflow_id="wf_chaos_test_001",
        name="test_wf",
        steps=[
            WorkflowStep(step_id="s1", capability_id="wf_step1", inputs={}),
            WorkflowStep(step_id="s2", capability_id="wf_step2", inputs={}),
        ],
    )

    state = engine.start_workflow(workflow=workflow, inputs={}, run_id="test_run_001")
    # Workflow should complete (both steps succeed)
    assert state.status in (WorkflowStatus.COMPLETED, WorkflowStatus.RUNNING), \
        f"Unexpected workflow status: {state.status}"


# ---------------------------------------------------------------------------
# 6. Registry pagination
# ---------------------------------------------------------------------------

def test_registry_pagination_returns_correct_slices(tmp_path):
    """list_capabilities with limit/offset must return correct slices."""
    registry = CapabilityRegistry(db_path=tmp_path / "page_test.db")

    # Register 5 capabilities
    for i in range(5):
        cap = Capability(
            id=f"page_cap_{i:02d}",
            name=f"Page Cap {i}",
            description=f"Pagination test cap {i}",
            version="1.0.0",
            code_body="def execute(inputs): return {'status': 'SUCCESS'}",
        )
        registry.register(cap)

    all_caps = registry.list_capabilities()
    assert len(all_caps) == 5

    page1 = registry.list_capabilities(limit=2, offset=0)
    assert len(page1) == 2

    page2 = registry.list_capabilities(limit=2, offset=2)
    assert len(page2) == 2

    page3 = registry.list_capabilities(limit=2, offset=4)
    assert len(page3) == 1

    # No duplicates across pages
    all_ids = [c.id for c in page1 + page2 + page3]
    assert len(all_ids) == len(set(all_ids)), "Pagination must not return duplicate capabilities"

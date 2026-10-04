"""Tests for CapForge Asynchronous Synthesis Path (Priority 1)."""

import time

from capforge import CapForgeClient
from capforge.core.models import (
    CapabilityStatus,
    PromotionMode,
    PromotionPolicy,
)
from capforge.runtime.agent_adapter import CapForgeAgent
from capforge.runtime.async_synthesis import (
    AsyncSynthesisManager,
    SynthesisFallbackResponse,
    SynthesisPhase,
)


def test_submit_synthesis_returns_immediate_fallback():
    """Verify that submit_synthesis returns an immediate fallback response without blocking."""
    manager = AsyncSynthesisManager()
    resp = manager.submit_synthesis(
        task_intent="calculate compound interest",
        fallback_output={"estimated_rate": 0.05},
    )

    assert isinstance(resp, SynthesisFallbackResponse)
    assert resp.status == "SYNTHESIS_QUEUED"
    assert resp.fallback_output == {"estimated_rate": 0.05}
    assert resp.job_id.startswith("async_")
    assert f"/v1/synthesis/{resp.job_id}" in resp.poll_endpoint

    job = manager.get_job(resp.job_id)
    assert job is not None
    assert job.task_intent == "calculate compound interest"


def test_async_synthesis_completes_in_background():
    """Verify that background worker executes synthesis through completion."""
    agent = CapForgeAgent()
    manager = AsyncSynthesisManager(agent=agent)

    spec = {
        "id": "tax_calculator",
        "name": "Tax Calculator",
        "description": "Calculate simple tax",
        "code_body": "def run(amount=100.0, **kw):\n    amt = amount.get('amount', 100.0) if isinstance(amount, dict) else amount\n    return {'tax': float(amt) * 0.2}\n",
    }

    resp = manager.submit_synthesis(
        task_intent="calculate tax on amount",
        knowledge_spec=spec,
        promotion_policy=PromotionPolicy(mode=PromotionMode.AUTO),
    )

    # Wait for completion (max 5 seconds)
    job = None
    for _ in range(50):
        job = manager.get_job(resp.job_id)
        if job and job.phase in (SynthesisPhase.COMPLETED, SynthesisPhase.FAILED):
            break
        time.sleep(0.1)

    assert job is not None
    assert job.phase == SynthesisPhase.COMPLETED
    assert job.progress_pct == 100
    assert job.capability_id == "tax_calculator"
    assert job.fully_verified is True
    assert "L0_L1_fast_check_ms" in job.phase_timings
    assert "L2_L5_full_verify_ms" in job.phase_timings

    # Capability is registered and ACTIVE
    cap = agent.registry.get("tax_calculator")
    assert cap is not None
    assert cap.status == CapabilityStatus.ACTIVE


def test_tiered_synthesis_draft_availability():
    """Verify tiered synthesis enables DRAFT status when require_full_verification=False."""
    agent = CapForgeAgent()
    manager = AsyncSynthesisManager(agent=agent)

    policy = PromotionPolicy(
        mode=PromotionMode.AUTO,
        require_full_verification=False,
    )

    spec = {
        "id": "draft_feature_tool",
        "name": "Draft Feature Tool",
        "description": "Quick draft tool",
        "code_body": "def run(x=10, **kw):\n    val = x.get('x', 10) if isinstance(x, dict) else x\n    return {'result': int(val) * 10}\n",
    }

    resp = manager.submit_synthesis(
        task_intent="generate draft feature tool",
        knowledge_spec=spec,
        promotion_policy=policy,
    )

    # Wait for completion
    for _ in range(50):
        job = manager.get_job(resp.job_id)
        if job and job.phase == SynthesisPhase.COMPLETED:
            break
        time.sleep(0.1)

    job = manager.get_job(resp.job_id)
    assert job.phase == SynthesisPhase.COMPLETED
    assert job.draft_available is True


def test_sdk_async_synthesis_methods():
    """Verify CapForgeClient synthesize_async and poll_synthesis work smoothly."""
    with CapForgeClient() as client:
        spec = {
            "id": "sdk_async_test_tool",
            "name": "SDK Async Test",
            "description": "Testing SDK async flow",
            "code_body": "def run(msg='hi', **kw):\n    return {'echo': str(msg)}\n",
        }

        resp = client.synthesize_async(
            task_intent="echo message tool",
            knowledge_spec=spec,
            promotion_policy=PromotionPolicy(mode=PromotionMode.AUTO),
            fallback_output={"echo": "fallback"},
        )

        assert isinstance(resp, SynthesisFallbackResponse)
        assert resp.fallback_output == {"echo": "fallback"}

        # Poll status
        polled = None
        for _ in range(50):
            polled = client.poll_synthesis(resp.job_id)
            if polled and polled.phase == SynthesisPhase.COMPLETED:
                break
            time.sleep(0.1)

        assert polled is not None
        assert polled.phase == SynthesisPhase.COMPLETED

        jobs = client.list_synthesis_jobs()
        assert any(j.job_id == resp.job_id for j in jobs)


def test_agent_handle_task_async_mode(tmp_path):
    """Verify CapForgeAgent.handle_task returns fallback trace immediately when async_mode=True."""
    from capforge.registry.store import CapabilityRegistry

    reg = CapabilityRegistry(db_path=tmp_path / "fresh.db")
    agent = CapForgeAgent(registry=reg)
    trace = agent.handle_task(
        task_intent="paginate through vendor records with cursor pagination",
        task_inputs={"data": [1, 2, 3]},
        async_mode=True,
        fallback_output={"approximate_eigenvalue": 4.2},
    )

    assert trace.gap.gap_detected is True
    assert trace.async_job_id is not None
    assert trace.async_status == "SYNTHESIS_QUEUED"
    assert trace.execution_result is not None
    assert trace.execution_result.status == "ASYNC_SYNTHESIS_QUEUED"
    assert trace.execution_result.output == {"approximate_eigenvalue": 4.2}

"""Tests for Evolution Budget Manager & Statistical Trigger Engine."""

from capforge.core.budget import BudgetConfig, EvolutionBudgetManager
from capforge.core.models import AgentEvent, EventType
from capforge.core.trigger_engine import TriggerEngine, TriggerType


def test_budget_manager_quotas_and_gating():
    config = BudgetConfig(
        max_llm_calls_per_hour=5,
        max_llm_calls_per_day=10,
        max_cost_per_day_usd=1.00,
        max_sandbox_runs_per_day=3,
        min_expected_gain_pct=5.0,
    )
    mgr = EvolutionBudgetManager(config=config)

    # 1. Under minimum expected gain threshold
    allowed, reason = mgr.can_evolve("cap_1", expected_gain_pct=2.0)
    assert not allowed
    assert "below minimum threshold" in reason

    # 2. Approved evolution
    allowed, reason = mgr.can_evolve("cap_1", expected_gain_pct=8.0, estimated_cost_usd=0.10)
    assert allowed
    assert "approved" in reason.lower()

    # 3. Record expenditures
    mgr.record_llm_call(tokens=1000, cost_usd=0.60)
    mgr.record_llm_call(tokens=1000, cost_usd=0.35)  # total $0.95
    status = mgr.get_budget_status()
    assert status["daily_calls"] == 2
    assert status["daily_cost_usd"] == 0.95

    # 4. Exceed daily budget ceiling with next job
    allowed, reason = mgr.can_evolve("cap_1", estimated_cost_usd=0.10)
    assert not allowed
    assert "Daily budget ceiling exceeded" in reason

    # 5. Low-priority reservation
    mgr.reset_quotas()
    mgr.record_llm_call(cost_usd=0.85)  # Remaining budget = 15% (< 20%)
    allowed, reason = mgr.can_evolve("cap_low", priority="LOW", estimated_cost_usd=0.01)
    assert not allowed
    assert "reserved for critical capabilities" in reason

    # High priority still permitted if cost fits
    allowed, reason = mgr.can_evolve("cap_high", priority="HIGH", estimated_cost_usd=0.01)
    assert allowed


def test_trigger_engine_consecutive_failures():
    engine = TriggerEngine(repeated_failure_threshold=3)

    event_fail = AgentEvent(
        event_type=EventType.TOOL_FAILED,
        tool_name="docker.build",
        error_type="TIMEOUT",
        error_message="Connection timed out",
    )

    assert engine.process_event(event_fail) is None
    assert engine.process_event(event_fail) is None

    # 3rd consecutive failure triggers
    trigger = engine.process_event(event_fail)
    assert trigger is not None
    assert trigger.trigger_type == TriggerType.REPEATED_TOOL_FAILURE
    assert trigger.tool_name == "docker.build"
    assert trigger.metrics["consecutive_failures"] == 3


def test_trigger_engine_gap_detection():
    engine = TriggerEngine()

    gap_event = AgentEvent(
        event_type=EventType.CAPABILITY_GAP_DETECTED,
        task_id="task_999",
        metadata={"missing_capability": "k8s_incident_triage"},
    )

    trigger = engine.process_event(gap_event)
    assert trigger is not None
    assert trigger.trigger_type == TriggerType.CAPABILITY_GAP
    assert trigger.capability_id == "k8s_incident_triage"

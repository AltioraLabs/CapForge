"""Tests for CapForge OpenTelemetry Distributed Tracing (discussion.mdx §29, §50)."""

import pytest
from capforge.core.telemetry import trace_manager, TraceManager
from capforge.core.models import Capability, CapabilityStatus, ExecutionRequest
from capforge.registry.store import CapabilityRegistry
from capforge.runtime.executor import CapabilityExecutor


@pytest.fixture(autouse=True)
def clean_traces():
    trace_manager.clear()
    yield
    trace_manager.clear()


def test_span_context_nesting():
    tm = TraceManager()
    with tm.start_span("parent_work", attributes={"user": "agent_alpha"}) as parent:
        parent.set_attribute("step", 1)
        with tm.start_span("child_work") as child:
            child.set_attribute("step", 2)
            child.add_event("subtask_completed", {"items": 5})

    spans = tm.list_spans()
    assert len(spans) == 2

    # Child should be recorded first or list contains both
    child_span = next(s for s in spans if s.name == "child_work")
    parent_span = next(s for s in spans if s.name == "parent_work")

    assert child_span.trace_id == parent_span.trace_id
    assert child_span.parent_span_id == parent_span.span_id
    assert child_span.attributes["step"] == 2
    assert len(child_span.events) == 1
    assert child_span.events[0]["name"] == "subtask_completed"
    assert child_span.duration_ms is not None
    assert parent_span.duration_ms is not None


def test_span_error_handling():
    tm = TraceManager()
    with pytest.raises(ValueError):
        with tm.start_span("failing_operation") as span:
            span.set_attribute("attempt", 1)
            raise ValueError("Simulated operational failure")

    spans = tm.list_spans(name="failing_operation")
    assert len(spans) == 1
    assert spans[0].status == "ERROR"
    assert "Simulated operational failure" in spans[0].error_message


def test_executor_automatic_tracing(tmp_path):
    db_path = tmp_path / "telemetry_test.db"
    reg = CapabilityRegistry(db_path=db_path)
    cap = Capability(
        id="telemetry_test_cap",
        name="Telemetry Test",
        description="Verifies telemetry span capture",
        status=CapabilityStatus.ACTIVE,
        code_body="def execute(inputs): return {'status': 'SUCCESS', 'data': 42}",
    )
    reg.register(cap)

    executor = CapabilityExecutor(registry=reg)
    req = ExecutionRequest(capability_id="telemetry_test_cap", inputs={}, agent_id="agent_otel")
    resp = executor.execute(req)
    assert resp.status == "SUCCESS"

    spans = trace_manager.list_spans(name="capability_execute:telemetry_test_cap")
    assert len(spans) >= 1
    span = spans[-1]
    assert span.attributes["capability_id"] == "telemetry_test_cap"
    assert span.attributes["agent_id"] == "agent_otel"
    assert span.attributes["status"] == "SUCCESS"
    assert span.duration_ms is not None

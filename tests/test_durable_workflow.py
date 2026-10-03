"""Tests for CapForge Resilient Durable Workflow Engine (v0.7.0)."""

import pytest
from fastapi.testclient import TestClient

from capforge.core.models import Capability, CapabilityStatus, ParameterSpec
from capforge.registry.store import CapabilityRegistry
from capforge.runtime.durable_workflow import (
    DurableWorkflowEngine,
    WorkflowDefinition,
    WorkflowStatus,
    WorkflowStep,
)
from capforge.runtime.executor import CapabilityExecutor
from capforge.server.app import app


@pytest.fixture
def workflow_env(tmp_path):
    db_path = tmp_path / "wf_test.db"
    reg = CapabilityRegistry(db_path=db_path)
    executor = CapabilityExecutor(registry=reg)
    engine = DurableWorkflowEngine(executor=executor)

    # Capability 1: normalize text
    cap1 = Capability(
        id="normalize_text",
        name="Normalize Text",
        description="Strips leading/trailing whitespace",
        inputs={"text": ParameterSpec(name="text", type="string", required=True)},
        status=CapabilityStatus.ACTIVE,
        code_body="""def execute(inputs):
    return {"cleaned": inputs.get("text", "").strip()}
""",
    )
    reg.register(cap1)

    # Capability 2: tag word count
    cap2 = Capability(
        id="count_words",
        name="Count Words",
        description="Counts words in input string",
        inputs={"text": ParameterSpec(name="text", type="string", required=True)},
        status=CapabilityStatus.ACTIVE,
        code_body="""def execute(inputs):
    text = inputs.get("text", "")
    return {"word_count": len(text.split()), "original": text}
""",
    )
    reg.register(cap2)

    return {"reg": reg, "executor": executor, "engine": engine}


def test_durable_workflow_success_execution(workflow_env):
    engine: DurableWorkflowEngine = workflow_env["engine"]

    wf = WorkflowDefinition(
        workflow_id="wf_text_pipeline",
        name="Text Cleaning Pipeline",
        steps=[
            WorkflowStep(
                step_id="step1",
                capability_id="normalize_text",
                input_mappings={"text": "$inputs.raw_text"},
            ),
            WorkflowStep(
                step_id="step2",
                capability_id="count_words",
                input_mappings={"text": "$steps.step1.output.cleaned"},
            ),
        ],
        output_mappings={
            "processed_text": "$steps.step1.output.cleaned",
            "words": "$steps.step2.output.word_count",
        },
    )

    state = engine.start_workflow(wf, {"raw_text": "   autonomous capforge agent   "})

    assert state.status == WorkflowStatus.COMPLETED
    assert state.checkpoints["step1"].status == "COMPLETED"
    assert state.checkpoints["step2"].status == "COMPLETED"
    assert state.checkpoints["step1"].attempt_count == 1
    assert state.checkpoints["step2"].attempt_count == 1
    assert state.final_output["processed_text"] == "autonomous capforge agent"
    assert state.final_output["words"] == 3


def test_durable_workflow_pause_and_resume(workflow_env):
    reg: CapabilityRegistry = workflow_env["reg"]
    engine: DurableWorkflowEngine = workflow_env["engine"]

    # Register initially buggy capability
    buggy_cap = Capability(
        id="buggy_service",
        name="Buggy Service",
        description="Simulates upstream transient error",
        inputs={"val": ParameterSpec(name="val", type="integer")},
        status=CapabilityStatus.ACTIVE,
        code_body="""def execute(inputs):
    raise ValueError("Transient upstream connection failed")
""",
    )
    reg.register(buggy_cap)

    wf = WorkflowDefinition(
        workflow_id="wf_pause_resume",
        name="Pause and Resume Pipeline",
        steps=[
            WorkflowStep(
                step_id="prep",
                capability_id="normalize_text",
                input_mappings={"text": "$inputs.text"},
            ),
            WorkflowStep(
                step_id="call_buggy",
                capability_id="buggy_service",
                input_mappings={"val": 10},
                max_retries=1,
            ),
        ],
    )

    state = engine.start_workflow(wf, {"text": "hello world"})

    # Should pause due to failure in step 2
    assert state.status == WorkflowStatus.PAUSED
    assert state.checkpoints["prep"].status == "COMPLETED"
    assert state.checkpoints["prep"].attempt_count == 1
    assert state.checkpoints["call_buggy"].status == "FAILED"
    assert "Transient upstream connection failed" in str(state.error)

    # Now repair the capability in the registry
    fixed_cap = Capability(
        id="buggy_service",
        name="Buggy Service (Fixed)",
        description="Fixed version of buggy service",
        inputs={"val": ParameterSpec(name="val", type="integer")},
        status=CapabilityStatus.ACTIVE,
        code_body="""def execute(inputs):
    return {"resolved": True, "val": inputs.get("val", 0) * 2}
""",
    )
    reg.register(fixed_cap)

    # Resume workflow from checkpoint
    resumed_state = engine.resume_workflow(state.run_id)

    assert resumed_state.status == WorkflowStatus.COMPLETED
    # Notice: step1 was NOT re-executed! It stayed attempt_count == 1
    assert resumed_state.checkpoints["prep"].attempt_count == 1
    assert resumed_state.checkpoints["call_buggy"].status == "COMPLETED"
    assert resumed_state.checkpoints["call_buggy"].output["resolved"] is True


def test_durable_workflow_continue_on_failure(workflow_env):
    reg: CapabilityRegistry = workflow_env["reg"]
    engine: DurableWorkflowEngine = workflow_env["engine"]

    faulty_cap = Capability(
        id="non_critical_metric",
        name="Non Critical Metric",
        description="Non-critical telemetry collector",
        status=CapabilityStatus.ACTIVE,
        code_body="""def execute(inputs):
    raise RuntimeError("Metrics service degraded")
""",
    )
    reg.register(faulty_cap)

    wf = WorkflowDefinition(
        workflow_id="wf_continue",
        name="Continue On Failure Pipeline",
        steps=[
            WorkflowStep(
                step_id="s1",
                capability_id="normalize_text",
                input_mappings={"text": "$inputs.raw"},
            ),
            WorkflowStep(
                step_id="s2",
                capability_id="non_critical_metric",
                continue_on_failure=True,
                max_retries=0,
            ),
            WorkflowStep(
                step_id="s3",
                capability_id="count_words",
                input_mappings={"text": "$steps.s1.output.cleaned"},
            ),
        ],
    )

    state = engine.start_workflow(wf, {"raw": "testing resilience"})
    assert state.status == WorkflowStatus.COMPLETED
    assert state.checkpoints["s1"].status == "COMPLETED"
    assert state.checkpoints["s2"].status == "FAILED"
    assert state.checkpoints["s3"].status == "COMPLETED"


def test_api_workflow_endpoints():
    client = TestClient(app)

    payload = {
        "workflow": {
            "workflow_id": "api_test_wf",
            "name": "API Test Workflow",
            "steps": [],
        },
        "inputs": {"sample": "data"},
    }

    resp = client.post("/v1/workflows/execute", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    run_id = data["run_id"]
    assert data["status"] == "COMPLETED"

    # Query by run_id
    get_resp = client.get(f"/v1/workflows/{run_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["run_id"] == run_id

    # List workflows
    list_resp = client.get("/v1/workflows")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) >= 1

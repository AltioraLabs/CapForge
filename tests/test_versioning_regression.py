"""Unit tests for Versioning and Regression Protection."""

import tempfile
from pathlib import Path

import pytest

from capforge.core.exceptions import RegressionDetectedError
from capforge.core.models import Capability, CapabilityStatus, TestCase, TestType
from capforge.registry.store import CapabilityRegistry
from capforge.versioning.manager import VersionManager


@pytest.fixture
def temp_registry():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    registry = CapabilityRegistry(db_path=db_path)
    yield registry
    if db_path.exists():
        try:
            db_path.unlink()
        except Exception:
            pass


def test_regression_blocks_breaking_version(temp_registry):
    vm = VersionManager(temp_registry)

    # Version 1.0.0 handles tasks returning {'status': 'OK', 'task_id': 1}
    v1 = Capability(
        id="order_processor",
        name="Order Processor",
        version="1.0.0",
        description="Version 1",
        code_body="def execute(inputs): return {'status': 'OK', 'task_id': inputs.get('id', 1)}",
        verification_tests=[
            TestCase(
                id="test_task_1",
                name="Must preserve task 1 contract",
                test_type=TestType.HAPPY_PATH,
                inputs={"id": 1},
                assert_expression="output.get('task_id') == 1"
            )
        ]
    )
    vm.promote_to_active(v1, skip_regression=True, skip_risk_check=True)

    # Version 2.0.0 accidentally breaks task 1 (returns task_id: 999 unconditionally)
    v2 = Capability(
        id="order_processor",
        name="Order Processor",
        version="2.0.0",
        description="Version 2",
        code_body="def execute(inputs): return {'status': 'OK', 'task_id': 999}",
        verification_tests=[
            TestCase(
                id="test_task_2",
                name="Must work for task 2",
                test_type=TestType.HAPPY_PATH,
                inputs={"id": 2},
                assert_expression="output.get('status') == 'OK'"
            )
        ]
    )

    # Promoting v2 MUST raise RegressionDetectedError because test_task_1 fails!
    with pytest.raises(RegressionDetectedError):
        vm.promote_to_active(v2)


def test_circuit_breaker_auto_rollback(temp_registry):
    """Verify that repeated runtime failures trip circuit breaker and roll back to parent version."""
    from capforge.core.models import ExecutionRequest
    from capforge.runtime.executor import CapabilityExecutor

    # Stable v1
    v1 = Capability(
        id="payment_gateway",
        name="Payment Gateway",
        version="1.0.0",
        status=CapabilityStatus.ACTIVE,
        description="Stable v1",
        code_body="def execute(inputs): return {'status': 'SUCCESS', 'version': '1.0.0'}",
    )
    temp_registry.register(v1)

    # Flaky/failing v2 with parent_version="1.0.0"
    v2 = Capability(
        id="payment_gateway",
        name="Payment Gateway",
        version="2.0.0",
        parent_version="1.0.0",
        status=CapabilityStatus.ACTIVE,
        description="Failing v2",
        code_body="def execute(inputs): raise RuntimeError('Payment upstream 503')",
    )
    temp_registry.register(v2)

    executor = CapabilityExecutor(
        temp_registry,
        failure_threshold=2,
        auto_rollback_enabled=True,
    )

    # Call 1: fails
    res1 = executor.execute(ExecutionRequest(capability_id="payment_gateway", version="2.0.0"))
    assert res1.status == "FAILED"
    assert executor._consecutive_failures["payment_gateway"] == 1

    # Call 2: fails again -> trips circuit breaker -> auto-rolls back to v1.0.0!
    res2 = executor.execute(ExecutionRequest(capability_id="payment_gateway", version="2.0.0"))
    assert res2.status == "FAILED"
    assert "CIRCUIT BREAKER" in res2.error

    # Verify v2 is now QUARANTINED and v1 is ACTIVE
    v2_state = temp_registry.get("payment_gateway", version="2.0.0")
    assert v2_state.status == CapabilityStatus.QUARANTINED

    v1_state = temp_registry.get("payment_gateway", version="1.0.0")
    assert v1_state.status == CapabilityStatus.ACTIVE

    # Execution without version now dispatches to restored active v1.0.0 and succeeds!
    res3 = executor.execute(ExecutionRequest(capability_id="payment_gateway"))
    assert res3.status == "SUCCESS"
    assert res3.output["version"] == "1.0.0"

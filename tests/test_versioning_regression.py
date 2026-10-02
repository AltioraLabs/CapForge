"""Unit tests for Versioning and Regression Protection."""

import tempfile
from pathlib import Path
import pytest

from skillforge.core.models import (
    Capability,
    CapabilityStatus,
    TestCase,
    TestType
)
from skillforge.core.exceptions import RegressionDetectedError
from skillforge.registry.store import CapabilityRegistry
from skillforge.versioning.manager import VersionManager


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
    vm.promote_to_active(v1, skip_regression=True)

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

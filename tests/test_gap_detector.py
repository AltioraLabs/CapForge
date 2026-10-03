"""Unit tests for Task Analysis and Capability Gap Detection."""

import tempfile
from pathlib import Path
import pytest

from capforge.core.models import Capability, CapabilityStatus
from capforge.registry.store import CapabilityRegistry
from capforge.discovery.gap_detector import CapabilityGapDetector


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


def test_gap_detection_on_empty_registry(temp_registry):
    detector = CapabilityGapDetector(temp_registry)
    task = "Analyze GitHub repository dependencies and identify security vulnerabilities"
    gap = detector.evaluate_task(task)

    assert gap.gap_detected is True
    assert len(gap.missing_primitives) > 0
    assert len(gap.suggested_acquisition_sources) > 0


def test_gap_resolved_after_registration(temp_registry):
    detector = CapabilityGapDetector(temp_registry)
    task = "Query QuantumMetrics API for CPU telemetry and audit anomalies"

    # Initially missing
    initial_gap = detector.evaluate_task(task)
    assert initial_gap.gap_detected is True

    # Register capability satisfying requirements
    cap = Capability(
        id="quantummetrics_data_analysis",
        name="QuantumMetrics Telemetry & Anomaly Auditor",
        version="1.0.0",
        status=CapabilityStatus.ACTIVE,
        description="Extracts telemetry metrics and audits anomalies from QuantumMetrics API",
        tags=["telemetry", "anomaly", "quantummetrics", "audit"],
        domain="data_analysis",
        code_body="def execute(inputs): return {'status': 'SUCCESS'}"
    )
    temp_registry.register(cap)

    # Re-evaluate
    resolved_gap = detector.evaluate_task(task)
    assert resolved_gap.gap_detected is False

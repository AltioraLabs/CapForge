"""Tests for CapForge LearningJobWorker asynchronous daemon."""

import pytest
import time
from capforge.acquisition.jobs import LearningJobManager
from capforge.acquisition.worker import LearningJobWorker
from capforge.runtime.agent_adapter import CapForgeAgent
from capforge.registry.store import CapabilityRegistry


@pytest.fixture
def worker_env(tmp_path):
    db_path = tmp_path / "worker_test.db"
    reg = CapabilityRegistry(db_path=db_path)
    agent = CapForgeAgent(registry=reg)
    manager = LearningJobManager(agent=agent)
    worker = LearningJobWorker(manager=manager, max_workers=2, poll_interval_sec=0.1)
    return worker, manager, reg


def test_worker_lifecycle_and_async_execution(worker_env):
    worker, manager, reg = worker_env

    # Queue a job
    job = manager.create_job(
        task_intent="Calculate SHA256 checksum of data buffer",
        task_inputs={"buffer": "capforge_production_verification"},
        knowledge_spec={
            "id": "sha256_checksum",
            "name": "SHA256 Checksum",
            "code_body": "def execute(buffer=''): import hashlib; return {'status': 'SUCCESS', 'checksum': hashlib.sha256(str(buffer).encode()).hexdigest()}",
        },
    )
    assert job.status == "QUEUED"

    # Start worker
    worker.start()
    assert worker.is_running()

    # Wait for completion
    finished = worker.wait_idle(timeout_sec=15.0)
    assert finished, "Worker did not finish processing job within timeout."

    updated_job = manager.get_job(job.job_id)
    assert updated_job is not None
    assert updated_job.status in ("COMPLETED", "FAILED")
    assert updated_job.progress_pct == 100

    # Stop worker
    worker.stop(timeout_sec=2.0)
    assert not worker.is_running()

"""Unit tests for LearningJobManager (§19, §38, §46)."""

from capforge.acquisition.jobs import LearningJobManager
from capforge.registry.store import CapabilityRegistry
from capforge.runtime.agent_adapter import CapForgeAgent


def test_learning_job_lifecycle():
    reg = CapabilityRegistry()
    sf_agent = CapForgeAgent(reg)
    mgr = LearningJobManager(sf_agent)

    # 1. Create job with explicit code_body spec for fast isolated execution
    job = mgr.create_job(
        task_intent="Analyze cluster resource saturation",
        task_inputs={"cluster": "prod-1"},
        knowledge_spec={
            "id": "cluster_saturation_analysis",
            "name": "Cluster Saturation Analysis",
            "code_body": "def execute(cluster=''): return {'status': 'SUCCESS', 'saturation': 0.72}",
        },
    )
    assert job.job_id.startswith("job_")
    assert job.status == "QUEUED"
    assert job.progress_pct == 0

    # 2. Retrieve job
    fetched = mgr.get_job(job.job_id)
    assert fetched is not None
    assert fetched.job_id == job.job_id

    # 3. List jobs
    all_jobs = mgr.list_jobs()
    assert len(all_jobs) >= 1

    # 4. Synchronous execution
    completed_job = mgr.execute_job_sync(job.job_id)
    assert completed_job.status in ("COMPLETED", "FAILED")
    assert completed_job.progress_pct == 100

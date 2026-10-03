"""Tests for CapForge Capability Composition Pipelines (discussion.mdx §20)."""

import pytest

from capforge.core.models import Capability, CapabilityStatus
from capforge.registry.store import CapabilityRegistry
from capforge.runtime.executor import CapabilityExecutor
from capforge.runtime.pipeline import (
    CapabilityPipeline,
    CapabilityPipelineRunner,
    PipelineStep,
)


@pytest.fixture
def pipeline_env(tmp_path):
    db_path = tmp_path / "pipeline_test.db"
    reg = CapabilityRegistry(db_path=db_path)
    executor = CapabilityExecutor(registry=reg)

    # Capability 1: URL parser
    cap1 = Capability(
        id="url_parser",
        name="URL Parser",
        description="Extracts host domain from URL",
        status=CapabilityStatus.ACTIVE,
        code_body="""def execute(inputs):
    url = inputs.get('url', '')
    domain = url.replace('https://', '').replace('http://', '').split('/')[0]
    return {'domain': domain, 'path': '/' + '/'.join(url.split('/')[3:]) if '/' in url.replace('https://', '') else '/'}
""",
    )
    reg.register(cap1)

    # Capability 2: DNS lookup
    cap2 = Capability(
        id="dns_lookup",
        name="DNS Lookup",
        description="Resolves domain to IP",
        status=CapabilityStatus.ACTIVE,
        code_body="""def execute(inputs):
    domain = inputs.get('domain', '')
    if not domain or domain == 'invalid.fail':
        raise ValueError('Domain resolution failed')
    return {'ip': '93.184.216.34', 'ttl': 300, 'resolved_domain': domain}
""",
    )
    reg.register(cap2)

    # Capability 3: Fallback DNS
    cap3 = Capability(
        id="fallback_dns",
        name="Fallback Cached DNS",
        description="Fallback static DNS resolution",
        status=CapabilityStatus.ACTIVE,
        code_body="""def execute(inputs):
    return {'ip': '1.1.1.1', 'ttl': 60, 'resolved_domain': inputs.get('domain', 'cached')}
""",
    )
    reg.register(cap3)

    runner = CapabilityPipelineRunner(executor)
    return runner, reg


def test_pipeline_success_chain(pipeline_env):
    runner, _ = pipeline_env

    pipeline = CapabilityPipeline(
        pipeline_id="url_to_ip_chain",
        name="URL to IP Resolution Pipeline",
        steps=[
            PipelineStep(
                step_id="parse_step",
                capability_id="url_parser",
                input_mappings={"url": "$inputs.target_url"},
            ),
            PipelineStep(
                step_id="dns_step",
                capability_id="dns_lookup",
                input_mappings={"domain": "$steps.parse_step.output.domain"},
            ),
        ],
        output_mappings={
            "domain": "$steps.parse_step.output.domain",
            "ip": "$steps.dns_step.output.ip",
            "original_url": "$inputs.target_url",
        },
    )

    res = runner.run_pipeline(pipeline, {"target_url": "https://example.com/api/v1"})
    assert res.status == "SUCCESS"
    assert res.final_output["domain"] == "example.com"
    assert res.final_output["ip"] == "93.184.216.34"
    assert res.final_output["original_url"] == "https://example.com/api/v1"
    assert len(res.step_results) == 2


def test_pipeline_failure_abort(pipeline_env):
    runner, _ = pipeline_env

    pipeline = CapabilityPipeline(
        pipeline_id="failing_pipeline",
        name="Failing Pipeline",
        steps=[
            PipelineStep(
                step_id="dns_step",
                capability_id="dns_lookup",
                input_mappings={"domain": "$inputs.domain"},
                continue_on_failure=False,
            ),
            PipelineStep(
                step_id="never_runs",
                capability_id="url_parser",
                input_mappings={"url": "https://google.com"},
            ),
        ],
    )

    res = runner.run_pipeline(pipeline, {"domain": "invalid.fail"})
    assert res.status == "FAILED"
    assert "Step 'dns_step' failed" in res.error
    assert "never_runs" not in res.step_results


def test_pipeline_fallback_recovery(pipeline_env):
    runner, _ = pipeline_env

    pipeline = CapabilityPipeline(
        pipeline_id="fallback_pipeline",
        name="Fallback Recovery Pipeline",
        steps=[
            PipelineStep(
                step_id="dns_step",
                capability_id="dns_lookup",
                input_mappings={"domain": "$inputs.domain"},
                fallback_capability_id="fallback_dns",
                continue_on_failure=False,
            ),
        ],
        output_mappings={"ip": "$steps.dns_step.output.ip"},
    )

    res = runner.run_pipeline(pipeline, {"domain": "invalid.fail"})
    assert res.status == "SUCCESS"
    assert res.final_output["ip"] == "1.1.1.1"

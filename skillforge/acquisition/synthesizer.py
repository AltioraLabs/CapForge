"""SkillForge Capability Synthesizer.

Converts acquired API specifications, documentation schemas, or procedure traces
into a validated, executable Capability object with tests and parameter schemas.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from skillforge.core.models import (
    Capability,
    CapabilityStatus,
    ExecutionMode,
    ParameterSpec,
    TestCase,
    TestType,
    ToolRequirement
)


class CapabilitySynthesizer:
    """Synthesizes structured, testable Capability objects."""

    def synthesize_api_capability(
        self,
        capability_id: str,
        name: str,
        description: str,
        domain: str,
        base_url: str,
        endpoints: List[Dict[str, Any]],
        auth_type: str = "Bearer",
        tags: Optional[List[str]] = None,
        code_override: Optional[str] = None
    ) -> Capability:
        """Synthesize a complete capability for interacting with an API service."""
        tags = tags or ["api", "integration", domain]

        # Generate standard inputs
        inputs = {
            "api_key": ParameterSpec(name="api_key", type="string", description="API key or token for authentication", required=True),
            "endpoint_path": ParameterSpec(name="endpoint_path", type="string", description="Relative API endpoint", required=False, default=endpoints[0]["path"] if endpoints else "/"),
            "params": ParameterSpec(name="params", type="dict", description="Query parameters", required=False, default={})
        }

        outputs = {
            "status": ParameterSpec(name="status", type="string", description="Execution status e.g. SUCCESS/FAILED"),
            "records": ParameterSpec(name="records", type="list", description="Fetched and processed records"),
            "summary": ParameterSpec(name="summary", type="dict", description="Aggregated metrics and count")
        }

        # Python Code Body implementing execute(inputs: dict) -> dict
        if code_override:
            code_body = code_override
        else:
            code_body = f'''
import httpx
import json

def execute(inputs: dict) -> dict:
    api_key = inputs.get("api_key")
    if not api_key:
        return {{"status": "FAILED", "error": "MISSING_API_KEY", "records": [], "summary": {{}}}}

    base_url = "{base_url}".rstrip("/")
    endpoint = inputs.get("endpoint_path", "{endpoints[0]["path"] if endpoints else "/"}").lstrip("/")
    url = f"{{base_url}}/{{endpoint}}"
    params = inputs.get("params", {{}})

    headers = {{
        "Authorization": f"Bearer {{api_key}}",
        "Accept": "application/json"
    }}

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, params=params, headers=headers)
            if resp.status_code == 401:
                return {{"status": "FAILED", "error": "UNAUTHORIZED", "records": [], "summary": {{}}}}
            if resp.status_code == 429:
                return {{"status": "FAILED", "error": "RATE_LIMITED", "records": [], "summary": {{}}}}
            
            data = resp.json()
            items = data.get("items", []) if isinstance(data, dict) else data
            return {{
                "status": "SUCCESS",
                "records": items,
                "summary": {{
                    "count": len(items) if isinstance(items, list) else 1,
                    "raw_status": resp.status_code
                }}
            }}
    except Exception as e:
        return {{"status": "FAILED", "error": str(e), "records": [], "summary": {{}}}}
'''.strip()

        # Generate initial Verification Tests
        tests = [
            TestCase(
                id=f"test_{capability_id}_happy_path",
                name="Verify standard authorized retrieval",
                test_type=TestType.HAPPY_PATH,
                inputs={"api_key": "valid_mock_token", "params": {"limit": 10}},
                expected_keys=["status", "records", "summary"],
                assert_expression="output['status'] == 'SUCCESS'"
            ),
            TestCase(
                id=f"test_{capability_id}_missing_key",
                name="Verify graceful failure on missing authorization key",
                test_type=TestType.EDGE_CASE,
                inputs={"api_key": "", "params": {}},
                assert_expression="output['status'] == 'FAILED' and output.get('error') == 'MISSING_API_KEY'"
            ),
            TestCase(
                id=f"test_{capability_id}_invariant_output_shape",
                name="Verify structured output invariant conformance",
                test_type=TestType.SECURITY_INVARIANT,
                inputs={"api_key": "valid_mock_token"},
                assert_expression="isinstance(output['records'], list) and isinstance(output['summary'], dict)"
            )
        ]

        tools_required = [
            ToolRequirement(name="httpx_network_egress", description="Network access to query target API", permissions=["network"])
        ]

        return Capability(
            id=capability_id,
            name=name,
            version="1.0.0",
            status=CapabilityStatus.EXPERIMENTAL,
            description=description,
            domain=domain,
            tags=tags,
            inputs=inputs,
            outputs=outputs,
            execution_mode=ExecutionMode.CODE,
            code_body=code_body,
            entrypoint_function="execute",
            verification_tests=tests,
            tools_required=tools_required,
            changelog="Candidate capability synthesized by SkillForge Acquisition Engine."
        )

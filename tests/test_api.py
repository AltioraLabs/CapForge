"""Integration tests for the FastAPI REST API."""

import pytest
from fastapi.testclient import TestClient

from capforge.server.app import app


@pytest.fixture
def client():
    return TestClient(app)


class TestHealthEndpoint:
    def test_health_check(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["service"] == "capforge"


class TestDashboardAPI:
    def test_dashboard_ui(self, client):
        resp = client.get("/dashboard")
        assert resp.status_code == 200
        assert "CapForge" in resp.text
        assert "Capability Control Center" in resp.text

    def test_dashboard_stats(self, client):
        resp = client.get("/v1/dashboard/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "capabilities_count" in data
        assert "active_learning_jobs" in data
        assert "agents_connected" in data


class TestDiscoveryAPI:
    def test_analyze_task(self, client):
        resp = client.post(
            "/v1/capabilities/analyze", json={"task_intent": "Analyze GitHub repository for security vulnerabilities"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "gap_detected" in data
        assert "missing_primitives" in data

    def test_search_capabilities(self, client):
        # Register capability first
        client.post(
            "/v1/capabilities/register",
            json={
                "id": "searchable_security_scan",
                "name": "Searchable Security Scan",
                "description": "Scan container images for vulnerabilities",
                "tags": ["security", "docker", "vulnerabilities"],
                "code_body": "def execute(inputs): return {}",
            },
        )

        resp = client.post(
            "/v1/capabilities/search",
            json={
                "query": "security vulnerabilities docker",
                "top_k": 3,
            },
        )
        assert resp.status_code == 200
        results = resp.json()
        assert isinstance(results, list)
        assert any(c["id"] == "searchable_security_scan" for c in results)

    def test_legacy_analyze_still_works(self, client):
        resp = client.post("/api/tasks/analyze", json={"task_intent": "Simple task"})
        assert resp.status_code == 200


class TestRegistryAPI:
    def test_list_capabilities(self, client):
        resp = client.get("/v1/capabilities")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_register_capability(self, client):
        cap = {
            "id": "api_test_cap",
            "name": "API Test Capability",
            "description": "A test capability",
            "code_body": "def execute(inputs): return {'status': 'OK'}",
        }
        resp = client.post("/v1/capabilities/register", json=cap)
        assert resp.status_code == 200
        assert resp.json()["id"] == "api_test_cap"

    def test_get_capability_not_found(self, client):
        resp = client.get("/v1/capabilities/nonexistent_cap_12345")
        assert resp.status_code == 404


class TestManifestAPI:
    def test_manifest_export_and_import(self, client):
        # Register a test capability
        cap_id = "manifest_test_cap"
        client.post(
            "/v1/capabilities/register",
            json={
                "id": cap_id,
                "name": "Manifest Test Cap",
                "description": "Test manifest export/import",
                "code_body": "def execute(inputs): return {'status': 'ok'}",
            },
        )

        # 1. Export
        resp = client.get(f"/v1/capabilities/{cap_id}/manifest")
        assert resp.status_code == 200
        assert "capability_id: manifest_test_cap" in resp.text

        # 2. Modify and Import under new ID
        modified_yaml = resp.text.replace("manifest_test_cap", "imported_test_cap")
        import_resp = client.post(
            "/v1/capabilities/manifest/import",
            content=modified_yaml,
            headers={"Content-Type": "text/plain"},
        )
        assert import_resp.status_code == 200
        assert import_resp.json()["id"] == "imported_test_cap"


class TestLearningJobsAPI:
    def test_create_and_get_learning_job(self, client):
        resp = client.post(
            "/v1/learning/jobs",
            json={
                "task_intent": "Analyze pod network latency",
                "task_inputs": {"pod": "gateway"},
                "knowledge_spec": {
                    "id": "pod_network_latency",
                    "name": "Pod Network Latency Analyzer",
                    "code_body": "def execute(pod=''): return {'status': 'SUCCESS', 'latency_ms': 12}",
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"].startswith("job_")
        assert data["progress_pct"] == 100

        # Retrieve job by ID
        get_resp = client.get(f"/v1/learning/jobs/{data['job_id']}")
        assert get_resp.status_code == 200
        assert get_resp.json()["job_id"] == data["job_id"]


class TestEventAPI:
    def test_receive_event(self, client):
        event = {
            "event_type": "tool_failed",
            "agent_id": "test_agent",
            "run_id": "run_1",
            "tool_name": "github.get_repo",
            "error_type": "TIMEOUT",
            "error_message": "Connection timed out",
        }
        resp = client.post("/v1/events", json=event)
        assert resp.status_code == 200
        data = resp.json()
        assert data["received"] is True
        assert "should_learn" in data

    def test_get_recent_events(self, client):
        resp = client.get("/v1/events/recent?limit=10")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestGovernanceAPI:
    def test_primitives_endpoint(self, client):
        resp = client.get("/v1/primitives")
        assert resp.status_code == 200
        data = resp.json()
        assert "auth_bearer" in data

    def test_governance_tickets_endpoint(self, client):
        resp = client.get("/v1/governance/tickets")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestMCPAndPipelineAPI:
    def test_mcp_tools_endpoint(self, client):
        resp = client.get("/mcp/tools")
        assert resp.status_code == 200
        tools = resp.json()["tools"]
        assert len(tools) >= 5

    def test_mcp_rpc_endpoint(self, client):
        resp = client.post(
            "/mcp/rpc",
            json={
                "jsonrpc": "2.0",
                "id": 100,
                "method": "ping",
                "params": {},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["jsonrpc"] == "2.0"
        assert resp.json()["id"] == 100

    def test_pipelines_run_endpoint(self, client):
        cap_payload = {
            "id": "pipe_echo_cap",
            "name": "Pipeline Echo",
            "description": "Echoes text",
            "status": "ACTIVE",
            "code_body": "def execute(inputs): return {'echo': inputs.get('text', '')}",
        }
        client.post("/v1/capabilities/register", json=cap_payload)

        pipeline_payload = {
            "pipeline": {
                "pipeline_id": "api_test_pipe",
                "name": "API Test Pipeline",
                "steps": [
                    {
                        "step_id": "step_1",
                        "capability_id": "pipe_echo_cap",
                        "input_mappings": {"text": "$inputs.user_input"},
                    }
                ],
                "output_mappings": {"processed": "$steps.step_1.output.echo"},
            },
            "initial_inputs": {"user_input": "hello capforge"},
        }
        resp = client.post("/v1/pipelines/run", json=pipeline_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["pipeline_id"] == "api_test_pipe"
        assert data["status"] == "SUCCESS"
        assert data["final_output"]["processed"] == "hello capforge"


class TestTelemetryAndGovernanceAPI:
    def test_telemetry_spans_endpoint(self, client):
        resp = client.get("/v1/telemetry/spans?limit=10")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_governance_ticket_approve_and_reject(self, client):
        # 1. Trigger high-risk capability registration to generate ticket
        high_risk_cap = {
            "id": "critical_api_test_cap",
            "name": "Critical Action",
            "description": "High risk test",
            "code_body": "def execute(inputs): return eval(inputs['code'])",
        }
        client.post("/v1/capabilities/register", json=high_risk_cap)

        # 2. List tickets
        tickets_resp = client.get("/v1/governance/tickets?status=PENDING")
        assert tickets_resp.status_code == 200
        tickets = tickets_resp.json()
        assert len(tickets) >= 1
        target_ticket = next(t for t in tickets if t["capability_id"] == "critical_api_test_cap")

        # 3. Approve ticket
        approve_resp = client.post(
            f"/v1/governance/tickets/{target_ticket['ticket_id']}/approve",
            json={"reviewer": "secops_lead", "notes": "Approved for testing"},
        )
        assert approve_resp.status_code == 200
        assert approve_resp.json()["status"] == "APPROVED"
        assert approve_resp.json()["reviewed_by"] == "secops_lead"


class TestBudgetAndBenchmarkAPI:
    def test_get_budget(self, client):
        resp = client.get("/v1/budget")
        assert resp.status_code == 200
        data = resp.json()
        assert "daily_calls" in data
        assert "daily_cost_usd" in data
        assert "max_cost_usd" in data

    def test_list_and_get_benchmarks(self, client):
        resp = client.get("/v1/benchmarks")
        assert resp.status_code == 200
        suites = resp.json()
        assert "software_engineering_v1" in suites

        detail_resp = client.get("/v1/benchmarks/software_engineering_v1")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["id"] == "software_engineering_v1"
        assert len(detail["tasks"]) >= 2

    def test_privacy_sanitize_endpoint(self, client):
        resp = client.post(
            "/v1/privacy/sanitize",
            json={
                "text": "Call agent with key sk-proj-1234567890abcdef1234567890 and email test@corp.org",
                "data": {"secret_token": "my-secret-token", "count": 10},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "[REDACTED_OPENAI_KEY]" in data["sanitized_text"]
        assert "[REDACTED_EMAIL]" in data["sanitized_text"]
        assert data["sanitized_data"]["secret_token"] == "[REDACTED_SECRET]"
        assert data["sanitized_data"]["count"] == 10

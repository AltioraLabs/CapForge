"""CapForge Enterprise General Availability (v1.0.0 GA) Integration & Test Suite."""

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from capforge.cli import app as cli_app
from capforge.core.models import Capability, CapabilityStatus, ParameterSpec
from capforge.registry.store import CapabilityRegistry
from capforge.registry.vector_store import DenseVectorEmbeddingEngine, SemanticVectorIndex
from capforge.server.app import app
from capforge.server.auth import AuthManager, UserRole


@pytest.fixture
def auth(tmp_path):
    from capforge.server.auth import AuthStore

    store = AuthStore(db_path=tmp_path / "auth_test.db")
    return AuthManager(store=store)


@pytest.fixture
def enterprise_reg(tmp_path):
    db_path = tmp_path / "v1_test.db"
    reg = CapabilityRegistry(db_path=db_path)

    # Capability A: Payments
    cap_pay = Capability(
        id="payment_processor",
        name="Credit Card Payment Processor",
        description="Processes credit card billing and checkout invoices",
        domain="finance",
        tags=["payment", "billing", "checkout", "stripe"],
        inputs={"amount": ParameterSpec(name="amount", type="number")},
        status=CapabilityStatus.ACTIVE,
        code_body="def execute(inputs): return {'charged': True}",
    )
    reg.register(cap_pay)

    # Capability B: Security Firewall
    cap_sec = Capability(
        id="firewall_scanner",
        name="Network Firewall Scanner",
        description="Scans network ports and detects intrusion packet breach",
        domain="security",
        tags=["firewall", "network", "ports", "breach"],
        inputs={"target": ParameterSpec(name="target", type="string")},
        status=CapabilityStatus.ACTIVE,
        code_body="def execute(inputs): return {'breaches_found': 0}",
    )
    reg.register(cap_sec)

    return reg


def test_auth_manager_key_creation_and_authentication(auth):
    raw_token, record = auth.create_api_key(
        name="Fintech Agent",
        role=UserRole.AGENT_RUNNER,
        tenant_namespace="finance",
    )

    assert raw_token.startswith("sf_live_")
    assert record.name == "Fintech Agent"
    assert record.role == UserRole.AGENT_RUNNER
    assert record.tenant_namespace == "finance"

    # Authenticate valid token
    auth_rec = auth.authenticate(raw_token)
    assert auth_rec is not None
    assert auth_rec.key_id == record.key_id

    # Authenticate invalid / tampered token
    assert auth.authenticate("sf_live_invalid_fake_key") is None
    assert auth.authenticate(None) is None


def test_auth_manager_authorization_and_revocation(auth):
    raw_token, record = auth.create_api_key(
        name="Dev Key",
        role=UserRole.AGENT_RUNNER,
        tenant_namespace="finance",
    )

    # Allowed role and correct namespace
    assert auth.authorize(record, allowed_roles=[UserRole.AGENT_RUNNER], target_namespace="finance") is True

    # Wrong namespace boundary
    assert auth.authorize(record, allowed_roles=[UserRole.AGENT_RUNNER], target_namespace="security") is False

    # Disallowed role
    assert auth.authorize(record, allowed_roles=[UserRole.ADMIN], target_namespace="finance") is False

    # Revocation
    assert auth.revoke_key(record.key_id) is True
    assert auth.authenticate(raw_token) is None
    assert auth.authorize(record, allowed_roles=[UserRole.AGENT_RUNNER], target_namespace="finance") is False


def test_dense_vector_embeddings_and_hybrid_search(enterprise_reg):
    engine = DenseVectorEmbeddingEngine(dimension=128)
    v1 = engine.embed_text("charge credit card and billing invoice")
    v2 = engine.embed_text("network firewall port scanner intrusion")
    v_query = engine.embed_text("billing payment")

    # Cosine similarity check
    sim_pay = engine.cosine_similarity(v_query, v1)
    sim_sec = engine.cosine_similarity(v_query, v2)
    assert sim_pay > sim_sec

    # Semantic Vector Store & Hybrid Search
    v_store = SemanticVectorIndex(enterprise_reg, embedding_engine=engine)

    # Search for payments
    pay_results = v_store.hybrid_search("checkout payment billing", alpha=0.6, top_k=2)
    assert len(pay_results) >= 1
    assert pay_results[0][0].id == "payment_processor"
    assert pay_results[0][1] > 0.3

    # Search for security
    sec_results = v_store.hybrid_search("packet breach network scanner", alpha=0.6, top_k=2)
    assert len(sec_results) >= 1
    assert sec_results[0][0].id == "firewall_scanner"
    assert sec_results[0][1] > 0.3


def test_cli_diagnostics_and_version():
    runner = CliRunner()

    res_ver = runner.invoke(cli_app, ["version"])
    assert res_ver.exit_code == 0
    assert "1." in res_ver.stdout  # matches 1.0.0, 1.1.0, etc.

    res_health = runner.invoke(cli_app, ["health"])
    assert res_health.exit_code == 0
    assert "SQLite Storage" in res_health.stdout
    assert "Subprocess Sandbox" in res_health.stdout


def test_api_v1_auth_and_hybrid_search_endpoints():
    """Test hybrid search (public) and key provisioning (requires admin auth)."""
    client = TestClient(app)

    # 1. Hybrid search endpoint — public, no auth required
    search_payload = {
        "query": "financial billing transactions",
        "alpha": 0.5,
        "top_k": 3,
    }
    resp = client.post("/v1/capabilities/hybrid-search", json=search_payload)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    # 2. Key provisioning — requires ADMIN or OPERATOR key
    # Use the bootstrap root admin key (always present in test env with dev_mode=true)
    admin_key = "sf_live_master_admin_secret"  # bootstrap key from auth.py
    key_payload = {
        "name": "E2E Automated Worker",
        "role": "AGENT_RUNNER",
        "tenant_namespace": "production",
    }
    key_resp = client.post(
        "/v1/auth/keys",
        json=key_payload,
        headers={"X-CapForge-Key": admin_key},
    )
    assert key_resp.status_code == 200, f"Key create failed: {key_resp.text}"
    data = key_resp.json()
    assert "api_key" in data
    assert data["api_key"].startswith("sf_live_")
    key_id = data["record"]["key_id"]

    # 3. List keys — requires ADMIN or OPERATOR key
    list_resp = client.get("/v1/auth/keys", headers={"X-CapForge-Key": admin_key})
    assert list_resp.status_code == 200
    assert any(k["key_id"] == key_id for k in list_resp.json())

    # 4. Revoke key — requires ADMIN key
    revoke_resp = client.post(
        f"/v1/auth/keys/{key_id}/revoke",
        headers={"X-CapForge-Key": admin_key},
    )
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["revoked"] is True

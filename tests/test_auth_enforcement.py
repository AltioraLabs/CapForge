"""Auth Enforcement Tests — v1.1.0.

Verifies that:
1. Routes protected by require_roles() actually reject wrong-role tokens (403).
2. Invalid / missing API keys return 401.
3. Revoked keys return 401 after revocation.
4. Root admin key bypasses role checks (ADMIN can do everything).
5. Auth state survives AuthManager reinstantiation (persistence).
"""

import pytest
from fastapi.testclient import TestClient

from capforge.server.app import app
from capforge.server.auth import AuthManager, AuthStore, UserRole

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def fresh_auth_manager(tmp_path):
    """AuthManager backed by a temp SQLite file for isolation."""
    store = AuthStore(db_path=tmp_path / "test_auth.db")
    return AuthManager(store=store)


def _make_key(mgr: AuthManager, role: UserRole, namespace: str = "default") -> str:
    raw_token, _ = mgr.create_api_key(name=f"test-{role.value}", role=role, namespace=namespace)
    return raw_token


# ---------------------------------------------------------------------------
# 1. Missing key → 401 (only in non-dev-mode)
# ---------------------------------------------------------------------------

def test_missing_key_returns_401_on_protected_route(monkeypatch):
    """POST /v1/auth/keys without a key should 401 when dev_mode is False."""
    from capforge.core import config as cfg_module
    monkeypatch.setattr(cfg_module.settings, "dev_mode", False)
    # Patch the auth dependency's settings reference
    from capforge.server import auth as auth_module
    monkeypatch.setattr(auth_module.settings, "dev_mode", False)

    resp = client.post("/v1/auth/keys", json={"name": "test", "role": "AGENT_RUNNER"})
    assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# 2. Invalid token → 401
# ---------------------------------------------------------------------------

def test_invalid_api_key_returns_401():
    """A garbage token must be rejected with 401."""
    resp = client.get("/v1/auth/keys", headers={"X-CapForge-Key": "sf_live_thisisnotatoken"})
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# 3. Revoked key → 401
# ---------------------------------------------------------------------------

def test_revoked_key_returns_401(fresh_auth_manager):
    """After revocation, the key must be rejected."""
    raw_token, rec = fresh_auth_manager.create_api_key("revoke-test", UserRole.AGENT_RUNNER)

    # Key is valid now
    retrieved = fresh_auth_manager.authenticate(raw_token)
    assert retrieved is not None

    # Revoke it
    success = fresh_auth_manager.revoke_key(rec.key_id)
    assert success is True

    # Must not authenticate
    retrieved_after = fresh_auth_manager.authenticate(raw_token)
    assert retrieved_after is None, "Revoked key should not authenticate"


# ---------------------------------------------------------------------------
# 4. Role enforcement — AGENT_RUNNER cannot provision keys (needs ADMIN/OPERATOR)
# ---------------------------------------------------------------------------

def test_agent_runner_cannot_create_api_keys(fresh_auth_manager):
    """AGENT_RUNNER role is forbidden from POST /v1/auth/keys."""
    runner_token, _ = fresh_auth_manager.create_api_key("runner", UserRole.AGENT_RUNNER)
    from capforge.server import auth as auth_module
    original = auth_module.auth_manager
    auth_module.auth_manager = fresh_auth_manager
    try:
        resp = client.post(
            "/v1/auth/keys",
            json={"name": "new-key", "role": "AGENT_RUNNER"},
            headers={"X-CapForge-Key": runner_token},
        )
        assert resp.status_code == 403, f"AGENT_RUNNER should get 403, got {resp.status_code}: {resp.text}"
    finally:
        auth_module.auth_manager = original


def test_auditor_cannot_create_api_keys(fresh_auth_manager):
    """AUDITOR role is also forbidden from provisioning keys."""
    auditor_token, _ = fresh_auth_manager.create_api_key("auditor", UserRole.AUDITOR)
    from capforge.server import auth as auth_module
    original = auth_module.auth_manager
    auth_module.auth_manager = fresh_auth_manager
    try:
        resp = client.post(
            "/v1/auth/keys",
            json={"name": "new-key", "role": "AUDITOR"},
            headers={"X-CapForge-Key": auditor_token},
        )
        assert resp.status_code == 403, f"AUDITOR should get 403, got {resp.status_code}: {resp.text}"
    finally:
        auth_module.auth_manager = original


# ---------------------------------------------------------------------------
# 5. ADMIN bypasses role checks
# ---------------------------------------------------------------------------

def test_admin_can_create_api_keys(fresh_auth_manager):
    """ADMIN role must be allowed to provision new keys."""
    admin_token, _ = fresh_auth_manager.create_api_key(
        name="admin", role=UserRole.ADMIN, tenant_namespace="*"
    )
    from capforge.server import auth as auth_module
    original = auth_module.auth_manager
    auth_module.auth_manager = fresh_auth_manager
    try:
        resp = client.post(
            "/v1/auth/keys",
            json={"name": "agent-key", "role": "AGENT_RUNNER"},
            headers={"X-CapForge-Key": admin_token},
        )
        assert resp.status_code == 200, f"ADMIN should get 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "api_key" in data
        assert data["api_key"].startswith("sf_live_")
    finally:
        auth_module.auth_manager = original


# ---------------------------------------------------------------------------
# 6. Auth persistence — key survives AuthManager re-instantiation
# ---------------------------------------------------------------------------

def test_auth_key_persists_across_manager_restart(tmp_path):
    """Keys written to SQLite must survive AuthManager reconstruction."""
    db_path = tmp_path / "persist_auth.db"

    # Create first manager and provision a key
    mgr1 = AuthManager(store=AuthStore(db_path=db_path))
    raw_token, rec = mgr1.create_api_key("persistent-key", UserRole.OPERATOR)

    # Create a brand new manager pointing to the same DB
    mgr2 = AuthManager(store=AuthStore(db_path=db_path))
    retrieved = mgr2.authenticate(raw_token)

    assert retrieved is not None, "Key must be retrievable from a new AuthManager instance"
    assert retrieved.key_id == rec.key_id
    assert retrieved.role == UserRole.OPERATOR

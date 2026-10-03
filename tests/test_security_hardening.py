"""Security hardening regression tests (no network, no LLM required).

Covers the 2026-10-04 audit fixes:
  1. Global API auth gate (401 outside dev mode, health stays public).
  2. Webhook SSRF guard (metadata/private targets blocked by default).
  3. Assert-expression AST whitelist (dunder escapes rejected).
  4. Sandbox auto-resolution (docker-if-available else subprocess).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from capforge.core import config as cfg_module
from capforge.events.webhooks import WebhookManager, WebhookSubscription
from capforge.security.ssrf_guard import (
    SSRFBlockedError,
    redact_url,
    validate_webhook_url,
)
from capforge.server import auth as auth_module
from capforge.server.app import app
from capforge.verification.evaluator import _assert_expr_is_safe
from capforge.verification.sandbox import get_sandbox_driver

client = TestClient(app, raise_server_exceptions=False)


def _dev_mode(monkeypatch, value: bool):
    monkeypatch.setattr(cfg_module.settings, "dev_mode", value)
    monkeypatch.setattr(auth_module.settings, "dev_mode", value)


# ---------------------------------------------------------------------------
# 1. Global auth gate
# ---------------------------------------------------------------------------


def test_health_public_without_key_prod_mode(monkeypatch):
    _dev_mode(monkeypatch, False)
    assert client.get("/health").status_code == 200
    assert client.get("/health/ready").status_code == 200


def test_write_routes_401_without_key_prod_mode(monkeypatch):
    _dev_mode(monkeypatch, False)
    r = client.post("/v1/webhooks", json={"url": "https://example.com/hook", "events": []})
    assert r.status_code == 401
    r = client.post("/v1/capabilities/analyze", json={"task_intent": "x", "task_inputs": {}})
    assert r.status_code in (401, 404, 422)


def test_routes_open_in_dev_mode(monkeypatch):
    _dev_mode(monkeypatch, True)
    r = client.post("/v1/webhooks", json={"url": "https://example.com/hook", "events": []})
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# 2. SSRF guard
# ---------------------------------------------------------------------------


def test_ssrf_blocks_metadata_and_private_by_default():
    for bad in (
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/",
        "http://127.0.0.1:9999/hook",
        "http://10.0.0.5/hook",
        "ftp://example.com/hook",
        "http:///no-host",
    ):
        with pytest.raises(SSRFBlockedError):
            validate_webhook_url(bad)


def test_ssrf_allows_public_url():
    assert validate_webhook_url("https://example.com/hook") == "https://example.com/hook"


def test_ssrf_allows_loopback_when_explicit():
    assert validate_webhook_url("http://127.0.0.1:9999/hook", allow_private=True).startswith("http://127.0.0.1")


def test_ssrf_metadata_blocked_even_when_private_allowed():
    with pytest.raises(SSRFBlockedError):
        validate_webhook_url("http://169.254.169.254/", allow_private=True)


def test_webhook_register_rejects_ssrf_target():
    mgr = WebhookManager()
    with pytest.raises(SSRFBlockedError):
        mgr.register(WebhookSubscription(url="http://169.254.169.254/x", events=[]))
    assert mgr.list_subscriptions(active_only=False) == []


def test_webhook_rejects_embedded_credentials():
    with pytest.raises(SSRFBlockedError):
        validate_webhook_url("https://user:s3cret@example.com/hook")


def test_webhook_log_redaction_strips_tokens():
    assert redact_url("https://example.com/hook?token=abc123&x=1") == "https://example.com/hook"
    assert redact_url("https://example.com/hook") == "https://example.com/hook"


def test_webhook_subscription_quota():
    from capforge.events.webhooks import WebhookLimitExceeded

    mgr = WebhookManager(max_subscriptions=2)
    mgr.register(WebhookSubscription(url="https://example.com/a", events=[]))
    mgr.register(WebhookSubscription(url="https://example.com/b", events=[]))
    with pytest.raises(WebhookLimitExceeded):
        mgr.register(WebhookSubscription(url="https://example.com/c", events=[]))


def test_bootstrap_admin_key_is_random_per_install(tmp_path):
    from capforge.server.auth import AuthManager, AuthStore

    hashes = set()
    for i in range(2):
        store = AuthStore(db_path=tmp_path / f"auth_{i}.db")
        AuthManager(store=store)
        rec = store.get_by_id("key_root_admin")
        assert rec is not None
        hashes.add(rec.key_hash)
    assert len(hashes) == 2, "fresh installs must not share a bootstrap credential"


def test_bootstrap_admin_key_env_override(tmp_path, monkeypatch):
    from capforge.server import auth as auth_module
    from capforge.server.auth import AuthManager, AuthStore

    monkeypatch.setattr(auth_module.settings, "bootstrap_admin_key", "sf_live_test_override_key")
    store = AuthStore(db_path=tmp_path / "auth_env.db")
    AuthManager(store=store)
    rec = store.get_by_id("key_root_admin")
    assert rec is not None
    import hashlib

    assert rec.key_hash == hashlib.sha256(b"sf_live_test_override_key").hexdigest()


# ---------------------------------------------------------------------------
# 3. Assert-expression whitelist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expr",
    [
        "output.get('status') == 'SUCCESS'",
        "output.get('a', 0) > 0 or output.get('b', 0) > 0",
        "len(output.get('x', [])) == 3 and isinstance(output, dict)",
    ],
)
def test_assert_whitelist_allows_legit(expr):
    ok, reason = _assert_expr_is_safe(expr)
    assert ok, f"wrongly rejected {expr!r}: {reason}"


@pytest.mark.parametrize(
    "expr",
    [
        "output.__class__.__base__.__subclasses__()",
        "__import__('os').system('id')",
        "eval('1+1')",
        "open('/etc/passwd').read()",
        "[x for x in output]",
        "(lambda: 1)()",
    ],
)
def test_assert_whitelist_blocks_escapes(expr):
    ok, _ = _assert_expr_is_safe(expr)
    assert not ok, f"wrongly allowed {expr!r}"


# ---------------------------------------------------------------------------
# 4. Sandbox auto-resolution
# ---------------------------------------------------------------------------


def test_sandbox_auto_resolves_to_known_driver():
    driver = get_sandbox_driver("auto")
    assert type(driver).__name__ in (
        "DockerSandboxDriver",
        "ProcessSandboxDriver",
        "WasmSandboxDriver",
    )

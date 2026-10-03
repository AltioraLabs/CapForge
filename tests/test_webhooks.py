"""Tests for CapForge Webhook Event System & REST API Endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from capforge import WebhookManager, WebhookSubscription
from capforge.server.app import app


@pytest.fixture
def manager():
    return WebhookManager()


def test_webhook_register_and_list(manager):
    """Register subscriptions and verify listing and retrieval."""
    sub = WebhookSubscription(
        url="https://example.com/webhook",
        events=["skill_promoted", "task_failed"],
        secret="test_secret",
        description="Test endpoint",
    )
    registered = manager.register(sub)
    assert registered.id == sub.id
    assert registered.active is True

    # List
    active_subs = manager.list_subscriptions(active_only=True)
    assert len(active_subs) == 1
    assert active_subs[0].url == "https://example.com/webhook"

    # Get by ID
    fetched = manager.get_subscription(registered.id)
    assert fetched is not None
    assert fetched.secret == "test_secret"

    # Unregister
    removed = manager.unregister(registered.id)
    assert removed is True
    assert len(manager.list_subscriptions(active_only=True)) == 0


def test_webhook_event_filtering(manager):
    """Subscribers should only receive events matching their subscribed event list."""
    sub1 = WebhookSubscription(url="https://example.com/h1", events=["skill_promoted"])
    sub2 = WebhookSubscription(url="https://example.com/h2", events=["task_failed"])
    sub_all = WebhookSubscription(url="https://example.com/h_all", events=[])

    manager.register(sub1)
    manager.register(sub2)
    manager.register(sub_all)

    with patch("httpx.Client") as mock_client:
        mock_instance = MagicMock()
        mock_resp = MagicMock(status_code=200)
        mock_instance.post.return_value = mock_resp
        mock_instance.__enter__.return_value = mock_instance
        mock_instance.__exit__.return_value = None
        mock_client.return_value = mock_instance

        # Dispatch skill_promoted
        deliveries = manager.dispatch("skill_promoted", {"capability_id": "test_cap"})
        # Should be delivered to sub1 and sub_all, but NOT sub2
        delivered_ids = [d.webhook_id for d in deliveries]
        assert sub1.id in delivered_ids
        assert sub_all.id in delivered_ids
        assert sub2.id not in delivered_ids


def test_webhook_hmac_signing(manager):
    """Webhook requests must contain valid HMAC-SHA256 signature when secret is provided."""
    sub = WebhookSubscription(
        url="https://example.com/signed-hook",
        events=["skill_promoted"],
        secret="super_secret_hmac_key",
    )
    manager.register(sub)

    with patch("httpx.Client") as mock_client:
        mock_instance = MagicMock()
        mock_resp = MagicMock(status_code=200)
        mock_instance.post.return_value = mock_resp
        mock_instance.__enter__.return_value = mock_instance
        mock_instance.__exit__.return_value = None
        mock_client.return_value = mock_instance

        deliveries = manager.dispatch("skill_promoted", {"status": "ACTIVE"})
        assert len(deliveries) == 1
        assert deliveries[0].success is True

        # Check call arguments to verify header
        call_kwargs = mock_instance.post.call_args.kwargs
        headers = call_kwargs.get("headers", {})
        assert "X-CapForge-Signature" in headers
        assert headers["X-CapForge-Signature"].startswith("sha256=")
        assert headers["X-CapForge-Event"] == "skill_promoted"


def test_webhook_api_endpoints():
    """Test Webhook REST API endpoints on FastAPI."""
    client = TestClient(app)

    # 1. Create Webhook
    resp = client.post(
        "/v1/webhooks",
        json={
            "url": "https://api.myapp.com/capforge-events",
            "events": ["skill_promoted"],
            "secret": "api_secret",
            "description": "Production Alerting",
        },
    )
    assert resp.status_code == 200
    sub_data = resp.json()
    sub_id = sub_data["id"]
    assert sub_data["url"] == "https://api.myapp.com/capforge-events"

    # 2. List Webhooks
    resp = client.get("/v1/webhooks")
    assert resp.status_code == 200
    subs = resp.json()
    assert any(s["id"] == sub_id for s in subs)

    # 3. Get Specific Webhook
    resp = client.get(f"/v1/webhooks/{sub_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == sub_id

    # 4. Test Webhook Dispatch
    with patch("httpx.Client") as mock_client:
        mock_instance = MagicMock()
        mock_resp = MagicMock(status_code=200)
        mock_instance.post.return_value = mock_resp
        mock_instance.__enter__.return_value = mock_instance
        mock_instance.__exit__.return_value = None
        mock_client.return_value = mock_instance

        resp = client.post(
            "/v1/webhooks/test",
            json={"event_type": "skill_promoted", "payload": {"capability_id": "math_tool"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["dispatched_count"] >= 1

    # 5. Delete Webhook
    resp = client.delete(f"/v1/webhooks/{sub_id}")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True

    # 6. Verify 404 after deletion
    resp = client.get(f"/v1/webhooks/{sub_id}")
    assert resp.status_code == 404

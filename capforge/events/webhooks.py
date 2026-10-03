"""CapForge Webhook Event Subscription System.

Enables developers to register HTTP webhook callbacks that fire
when specific CapForge events occur (e.g., SKILL_PROMOTED,
CAPABILITY_GAP_DETECTED, TASK_FAILED).

Usage:
    # Via REST API:
    POST /v1/webhooks
    {
        "url": "https://myapp.com/capforge-events",
        "events": ["skill_promoted", "capability_gap_detected"],
        "secret": "my_hmac_secret"
    }

    # Via Python SDK:
    client.subscribe_webhook(
        url="https://myapp.com/events",
        events=["skill_promoted"],
    )
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field

logger = logging.getLogger("capforge.webhooks")


class WebhookSubscription(BaseModel):
    """A registered webhook endpoint and its event filter."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    url: str
    events: list[str] = Field(default_factory=list, description="Event types to subscribe to. Empty = all events.")
    secret: str | None = Field(default=None, description="HMAC-SHA256 secret for payload signing.")
    active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    description: str = ""
    failure_count: int = 0
    max_failures: int = 10


class WebhookDelivery(BaseModel):
    """Record of a webhook delivery attempt."""

    delivery_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    webhook_id: str
    event_type: str
    payload: dict
    status_code: int | None = None
    success: bool = False
    error: str | None = None
    delivered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WebhookManager:
    """Manages webhook subscriptions and delivery.

    In production, delivery would be async with retry queues.
    This implementation provides synchronous delivery with failure tracking.
    """

    def __init__(self) -> None:
        self._subscriptions: dict[str, WebhookSubscription] = {}
        self._delivery_log: list[WebhookDelivery] = []
        self._max_log_size: int = 1000

    def register(self, subscription: WebhookSubscription) -> WebhookSubscription:
        """Register a new webhook subscription."""
        self._subscriptions[subscription.id] = subscription
        logger.info(
            "Registered webhook '%s' -> %s (events=%s)",
            subscription.id,
            subscription.url,
            subscription.events or ["*"],
        )
        return subscription

    def unregister(self, webhook_id: str) -> bool:
        """Remove a webhook subscription."""
        if webhook_id in self._subscriptions:
            del self._subscriptions[webhook_id]
            return True
        return False

    def list_subscriptions(self, active_only: bool = True) -> list[WebhookSubscription]:
        """List all registered webhook subscriptions."""
        subs = list(self._subscriptions.values())
        if active_only:
            subs = [s for s in subs if s.active]
        return subs

    def get_subscription(self, webhook_id: str) -> WebhookSubscription | None:
        """Get a specific webhook subscription by ID."""
        return self._subscriptions.get(webhook_id)

    def dispatch(self, event_type: str, payload: dict) -> list[WebhookDelivery]:
        """Dispatch an event to all matching webhook subscribers.

        Args:
            event_type: The event type string (e.g., "skill_promoted").
            payload: The event payload dictionary.

        Returns:
            List of delivery results.
        """
        deliveries: list[WebhookDelivery] = []

        for sub in self._subscriptions.values():
            if not sub.active:
                continue
            if sub.events and event_type not in sub.events:
                continue

            delivery = self._deliver(sub, event_type, payload)
            deliveries.append(delivery)

            # Track in log
            self._delivery_log.append(delivery)
            if len(self._delivery_log) > self._max_log_size:
                self._delivery_log = self._delivery_log[-self._max_log_size :]

        return deliveries

    def _deliver(
        self,
        subscription: WebhookSubscription,
        event_type: str,
        payload: dict,
    ) -> WebhookDelivery:
        """Attempt to deliver a webhook payload to a subscriber."""
        delivery_id = str(uuid.uuid4())
        body = json.dumps(
            {
                "delivery_id": delivery_id,
                "event_type": event_type,
                "timestamp": datetime.now(UTC).isoformat(),
                "payload": payload,
            },
            default=str,
        )

        # Compute HMAC signature if secret is configured
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "X-CapForge-Event": event_type,
            "X-CapForge-Delivery": delivery_id,
        }
        if subscription.secret:
            signature = hmac.new(
                subscription.secret.encode(),
                body.encode(),
                hashlib.sha256,
            ).hexdigest()
            headers["X-CapForge-Signature"] = f"sha256={signature}"

        # Attempt HTTP delivery
        try:
            import httpx

            with httpx.Client(timeout=10.0) as http_client:
                response = http_client.post(subscription.url, content=body, headers=headers)
                success = 200 <= response.status_code < 300

                if not success:
                    subscription.failure_count += 1
                    if subscription.failure_count >= subscription.max_failures:
                        subscription.active = False
                        logger.warning(
                            "Webhook '%s' deactivated after %d failures",
                            subscription.id,
                            subscription.failure_count,
                        )
                else:
                    subscription.failure_count = 0

                return WebhookDelivery(
                    delivery_id=delivery_id,
                    webhook_id=subscription.id,
                    event_type=event_type,
                    payload=payload,
                    status_code=response.status_code,
                    success=success,
                )

        except Exception as e:
            subscription.failure_count += 1
            if subscription.failure_count >= subscription.max_failures:
                subscription.active = False

            logger.error("Webhook delivery to '%s' failed: %s", subscription.url, e)
            return WebhookDelivery(
                delivery_id=delivery_id,
                webhook_id=subscription.id,
                event_type=event_type,
                payload=payload,
                success=False,
                error=str(e),
            )

    def get_delivery_log(self, webhook_id: str | None = None, limit: int = 50) -> list[WebhookDelivery]:
        """Retrieve recent webhook delivery logs."""
        log = self._delivery_log
        if webhook_id:
            log = [d for d in log if d.webhook_id == webhook_id]
        return log[-limit:]


# Module-level singleton for shared access
webhook_manager = WebhookManager()

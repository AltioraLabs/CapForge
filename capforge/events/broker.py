"""CapForge Distributed Event Stream Broker (discussion.mdx §9, §35, §36).

Provides an enterprise-grade publish/subscribe and stream replay broker
for distributed agent events across multi-process clusters, worker pools, and dashboards.
"""

from __future__ import annotations

import abc
import fnmatch
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field

from capforge.core.models import AgentEvent

logger = logging.getLogger("capforge.events.broker")


class StreamMessage(BaseModel):
    """Enveloped event message residing in the stream buffer."""
    message_id: str = Field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:12]}")
    topic: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event: AgentEvent
    acknowledged_by: List[str] = Field(default_factory=list)


class BaseEventBroker(abc.ABC):
    """Abstract interface for distributed event stream brokers."""

    @abc.abstractmethod
    def publish(self, topic: str, event: AgentEvent) -> str:
        """Publish an agent event to a specific stream topic. Returns message ID."""
        pass

    @abc.abstractmethod
    def subscribe(
        self,
        topic_pattern: str,
        consumer_id: str,
        handler: Callable[[StreamMessage], None],
    ) -> None:
        """Register a consumer callback matching a topic pattern."""
        pass

    @abc.abstractmethod
    def replay(
        self,
        topic_pattern: str = "*",
        since_timestamp: Optional[str] = None,
        limit: int = 100,
    ) -> List[StreamMessage]:
        """Replay historical messages from the stream matching the filter."""
        pass

    @abc.abstractmethod
    def ack(self, consumer_id: str, message_id: str) -> bool:
        """Acknowledge message processing by a consumer group/id."""
        pass


class InMemoryStreamBroker(BaseEventBroker):
    """Zero-dependency, thread-safe in-memory stream broker with topic pattern matching & replay."""

    def __init__(self, max_buffer_size: int = 10_000):
        self.max_buffer_size = max_buffer_size
        self._buffer: List[StreamMessage] = []
        self._subscribers: List[Dict[str, Any]] = []
        self._lock = threading.RLock()

    def publish(self, topic: str, event: AgentEvent) -> str:
        msg = StreamMessage(topic=topic, event=event)

        with self._lock:
            self._buffer.append(msg)
            if len(self._buffer) > self.max_buffer_size:
                self._buffer = self._buffer[-self.max_buffer_size:]

            active_subscribers = list(self._subscribers)

        # Dispatch to matching subscribers outside write lock
        for sub in active_subscribers:
            pattern = sub["pattern"]
            if fnmatch.fnmatch(topic, pattern):
                try:
                    sub["handler"](msg)
                except Exception:
                    logger.exception(
                        "Consumer '%s' failed handling message '%s' on topic '%s'",
                        sub["consumer_id"],
                        msg.message_id,
                        topic,
                    )

        return msg.message_id

    def subscribe(
        self,
        topic_pattern: str,
        consumer_id: str,
        handler: Callable[[StreamMessage], None],
    ) -> None:
        with self._lock:
            self._subscribers.append({
                "pattern": topic_pattern,
                "consumer_id": consumer_id,
                "handler": handler,
            })

    def replay(
        self,
        topic_pattern: str = "*",
        since_timestamp: Optional[str] = None,
        limit: int = 100,
    ) -> List[StreamMessage]:
        with self._lock:
            results = []
            for msg in reversed(self._buffer):
                if fnmatch.fnmatch(msg.topic, topic_pattern):
                    if since_timestamp and msg.timestamp < since_timestamp:
                        continue
                    results.append(msg)
                    if len(results) >= limit:
                        break
            results.reverse()
            return results

    def ack(self, consumer_id: str, message_id: str) -> bool:
        with self._lock:
            for msg in self._buffer:
                if msg.message_id == message_id:
                    if consumer_id not in msg.acknowledged_by:
                        msg.acknowledged_by.append(consumer_id)
                    return True
        return False

    def clear(self) -> None:
        """Clear stream buffer (primarily for test fixtures)."""
        with self._lock:
            self._buffer.clear()
            self._subscribers.clear()


class RedisStreamBroker(BaseEventBroker):
    """Resilient Redis Stream Broker with automatic in-memory fallback.
    
    If Redis is installed and running, publishes events to Redis Streams.
    Otherwise gracefully falls back to an in-memory stream buffer.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        stream_key: str = "capforge:events",
        force_fallback: bool = False,
    ):
        self.redis_url = redis_url
        self.stream_key = stream_key
        self.force_fallback = force_fallback
        self._fallback_broker = InMemoryStreamBroker()
        self._redis_client = None
        self._is_connected = False

        if not self.force_fallback:
            self._init_redis()

    def _init_redis(self) -> None:
        try:
            import redis
            client = redis.from_url(self.redis_url, socket_timeout=1.0)
            client.ping()
            self._redis_client = client
            self._is_connected = True
            logger.info("Connected to Redis event stream at %s", self.redis_url)
        except Exception as e:
            logger.info("Redis unavailable (%s). Falling back to InMemoryStreamBroker.", e)
            self._redis_client = None
            self._is_connected = False

    @property
    def is_connected_to_redis(self) -> bool:
        return self._is_connected

    def publish(self, topic: str, event: AgentEvent) -> str:
        if self._is_connected and self._redis_client is not None:
            try:
                msg_payload = {
                    "topic": topic,
                    "event_id": event.event_id,
                    "event_type": event.event_type.value,
                    "agent_id": event.agent_id or "",
                    "run_id": event.run_id or "",
                    "payload": event.model_dump_json(),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                msg_id = self._redis_client.xadd(self.stream_key, msg_payload)
                # Also mirror into local fallback broker for local in-process consumers
                self._fallback_broker.publish(topic, event)
                return str(msg_id)
            except Exception as e:
                logger.warning("Redis xadd failed (%s). Falling back to memory broker.", e)
                self._is_connected = False

        return self._fallback_broker.publish(topic, event)

    def subscribe(
        self,
        topic_pattern: str,
        consumer_id: str,
        handler: Callable[[StreamMessage], None],
    ) -> None:
        self._fallback_broker.subscribe(topic_pattern, consumer_id, handler)

    def replay(
        self,
        topic_pattern: str = "*",
        since_timestamp: Optional[str] = None,
        limit: int = 100,
    ) -> List[StreamMessage]:
        return self._fallback_broker.replay(
            topic_pattern=topic_pattern,
            since_timestamp=since_timestamp,
            limit=limit,
        )

    def ack(self, consumer_id: str, message_id: str) -> bool:
        return self._fallback_broker.ack(consumer_id, message_id)

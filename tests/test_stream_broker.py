"""Tests for CapForge Distributed Event Stream Broker (v0.7.0)."""


import pytest
from fastapi.testclient import TestClient

from capforge.core.events import EventGateway
from capforge.core.models import AgentEvent, EventType
from capforge.events.broker import InMemoryStreamBroker, RedisStreamBroker
from capforge.server.app import app


@pytest.fixture
def broker():
    b = InMemoryStreamBroker(max_buffer_size=100)
    b.clear()
    return b


def test_in_memory_broker_pub_sub_and_wildcard_matching(broker):
    received_wildcard = []
    received_specific = []

    broker.subscribe("events.*", "worker_1", lambda msg: received_wildcard.append(msg))
    broker.subscribe("events.tool_*", "worker_2", lambda msg: received_specific.append(msg))

    ev1 = AgentEvent(event_type=EventType.TASK_STARTED, agent_id="agent_alpha")
    ev2 = AgentEvent(event_type=EventType.TOOL_FAILED, agent_id="agent_alpha", error_message="timeout")

    msg_id1 = broker.publish("events.task_started", ev1)
    msg_id2 = broker.publish("events.tool_failed", ev2)

    assert msg_id1.startswith("msg_")
    assert msg_id2.startswith("msg_")

    assert len(received_wildcard) == 2
    assert len(received_specific) == 1
    assert received_specific[0].event.event_type == EventType.TOOL_FAILED


def test_broker_historical_replay(broker):
    for i in range(5):
        ev = AgentEvent(event_type=EventType.TOOL_CALLED, agent_id=f"agent_{i}")
        broker.publish(f"events.tool_{i}", ev)

    # Replay all
    all_msgs = broker.replay("*", limit=10)
    assert len(all_msgs) == 5

    # Replay with pattern
    subset = broker.replay("events.tool_[0-2]", limit=10)
    assert len(subset) == 3


def test_consumer_ack(broker):
    ev = AgentEvent(event_type=EventType.TASK_COMPLETED)
    msg_id = broker.publish("events.task_completed", ev)

    acked = broker.ack("consumer_group_a", msg_id)
    assert acked is True

    # Re-ack should be idempotent
    re_acked = broker.ack("consumer_group_a", msg_id)
    assert re_acked is True

    replayed = broker.replay("events.task_completed")
    assert len(replayed) == 1
    assert "consumer_group_a" in replayed[0].acknowledged_by


def test_redis_broker_fallback():
    redis_broker = RedisStreamBroker(force_fallback=True)
    assert redis_broker.is_connected_to_redis is False

    ev = AgentEvent(event_type=EventType.LEARNING_STARTED, agent_id="learner_1")
    msg_id = redis_broker.publish("events.learning_started", ev)
    assert msg_id is not None

    replayed = redis_broker.replay("events.learning_started")
    assert len(replayed) == 1
    assert replayed[0].event.agent_id == "learner_1"


def test_event_gateway_broker_integration():
    custom_broker = InMemoryStreamBroker()
    gateway = EventGateway(broker=custom_broker)

    ev = AgentEvent(event_type=EventType.SKILL_PROMOTED, agent_id="promoter_bot")
    gateway.emit(ev)

    replayed = custom_broker.replay("events.skill_promoted")
    assert len(replayed) == 1
    assert replayed[0].event.agent_id == "promoter_bot"


def test_api_event_stream_endpoint():
    client = TestClient(app)
    resp = client.get("/v1/events/stream?limit=10")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

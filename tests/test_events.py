"""Unit tests for the Event Gateway and Experience Filter."""

from capforge.core.events import EventGateway, ExperienceFilter
from capforge.core.models import AgentEvent, EventType


class TestEventGateway:
    def test_emit_and_subscribe(self):
        gw = EventGateway()
        received = []

        gw.subscribe(EventType.TOOL_FAILED, lambda e: received.append(e))

        event = AgentEvent(
            event_type=EventType.TOOL_FAILED,
            agent_id="agent_1",
            run_id="run_1",
            tool_name="github.get_repo",
            error_type="TIMEOUT",
            error_message="Connection timed out",
        )
        gw.emit(event)

        assert len(received) == 1
        assert received[0].tool_name == "github.get_repo"

    def test_subscribe_all(self):
        gw = EventGateway()
        received = []

        gw.subscribe_all(lambda e: received.append(e))

        gw.emit(AgentEvent(event_type=EventType.AGENT_STARTED))
        gw.emit(AgentEvent(event_type=EventType.TOOL_CALLED))

        assert len(received) == 2

    def test_get_recent_events(self):
        gw = EventGateway()
        for i in range(10):
            gw.emit(AgentEvent(event_type=EventType.TOOL_CALLED, run_id=f"run_{i}"))

        recent = gw.get_recent_events(limit=5)
        assert len(recent) == 5
        assert recent[-1].run_id == "run_9"

    def test_get_events_by_run(self):
        gw = EventGateway()
        gw.emit(AgentEvent(event_type=EventType.TASK_STARTED, run_id="run_a"))
        gw.emit(AgentEvent(event_type=EventType.TASK_COMPLETED, run_id="run_b"))
        gw.emit(AgentEvent(event_type=EventType.TASK_FAILED, run_id="run_a"))

        run_a_events = gw.get_events_by_run("run_a")
        assert len(run_a_events) == 2


class TestExperienceFilter:
    def test_always_learn_from_gap_detection(self):
        ef = ExperienceFilter()
        event = AgentEvent(event_type=EventType.CAPABILITY_GAP_DETECTED)
        assert ef.should_learn(event) is True

    def test_learn_from_novel_failure(self):
        ef = ExperienceFilter()
        event = AgentEvent(
            event_type=EventType.TOOL_FAILED,
            tool_name="new_tool",
            error_type="NEW_ERROR",
            error_message="Never seen before",
        )
        assert ef.should_learn(event) is True

    def test_ignore_duplicate_failure(self):
        ef = ExperienceFilter()
        event = AgentEvent(
            event_type=EventType.TOOL_FAILED,
            tool_name="known_tool",
            error_type="KNOWN_ERROR",
            error_message="Seen before",
        )
        # First occurrence — novel
        assert ef.should_learn(event) is True
        # Second occurrence — duplicate (below threshold)
        assert ef.should_learn(event) is False

    def test_learn_after_repeated_failures(self):
        ef = ExperienceFilter(failure_threshold=3)
        event = AgentEvent(
            event_type=EventType.TOOL_FAILED,
            tool_name="flaky_tool",
            error_type="FLAKY",
            error_message="Intermittent",
        )
        # 1st: novel → True (added to seen_errors)
        assert ef.should_learn(event) is True
        # 2nd: duplicate, count=1 (below threshold=3) → False
        assert ef.should_learn(event) is False
        # 3rd: duplicate, count=2 (below threshold=3) → False
        assert ef.should_learn(event) is False
        # 4th: duplicate, count=3 (reached threshold) → True (counter resets)
        assert ef.should_learn(event) is True
        # 5th: duplicate, count=1 (reset, below threshold) → False
        assert ef.should_learn(event) is False

    def test_ignore_routine_success(self):
        ef = ExperienceFilter()
        event = AgentEvent(event_type=EventType.TASK_COMPLETED)
        assert ef.should_learn(event) is False

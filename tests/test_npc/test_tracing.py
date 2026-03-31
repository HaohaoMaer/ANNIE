"""Tests for the execution tracing system."""

import json
import time

import pytest

from annie.npc.tracing import EventType, TraceEvent, Tracer


class TestTraceEvent:
    def test_create_with_defaults(self):
        event = TraceEvent(
            node_name="planner",
            agent_name="npc_a",
            event_type=EventType.NODE_ENTER,
        )
        assert event.node_name == "planner"
        assert event.agent_name == "npc_a"
        assert event.event_type == EventType.NODE_ENTER
        assert event.input_summary == ""
        assert event.output_summary == ""
        assert event.metadata == {}
        assert event.duration_ms is None
        assert event.timestamp is not None


class TestTracer:
    def test_trace_appends_event(self):
        tracer = Tracer("test_npc")
        event = tracer.trace("planner", EventType.NODE_ENTER, input_summary="event X")
        assert len(tracer.events) == 1
        assert event.node_name == "planner"
        assert event.agent_name == "test_npc"
        assert event.input_summary == "event X"

    def test_trace_multiple_events(self):
        tracer = Tracer("test_npc")
        tracer.trace("planner", EventType.NODE_ENTER)
        tracer.trace("planner", EventType.TASK_CREATED, output_summary="Created 3 tasks")
        tracer.trace("planner", EventType.NODE_EXIT)
        assert len(tracer.events) == 3
        assert tracer.events[0].event_type == EventType.NODE_ENTER
        assert tracer.events[1].event_type == EventType.TASK_CREATED
        assert tracer.events[2].event_type == EventType.NODE_EXIT

    def test_trace_with_metadata(self):
        tracer = Tracer("test_npc")
        event = tracer.trace(
            "executor", EventType.SKILL_INVOKE, metadata={"skill": "conversation"}
        )
        assert event.metadata["skill"] == "conversation"

    def test_node_span_records_enter_and_exit(self):
        tracer = Tracer("test_npc")
        with tracer.node_span("planner"):
            pass
        assert len(tracer.events) == 2
        assert tracer.events[0].event_type == EventType.NODE_ENTER
        assert tracer.events[0].node_name == "planner"
        assert tracer.events[1].event_type == EventType.NODE_EXIT
        assert tracer.events[1].node_name == "planner"

    def test_node_span_measures_duration(self):
        tracer = Tracer("test_npc")
        with tracer.node_span("planner"):
            time.sleep(0.01)
        exit_event = tracer.events[1]
        assert exit_event.duration_ms is not None
        assert exit_event.duration_ms >= 5  # at least ~10ms with some tolerance

    def test_node_span_records_error_on_exception(self):
        tracer = Tracer("test_npc")
        with pytest.raises(ValueError, match="test error"):
            with tracer.node_span("executor"):
                raise ValueError("test error")
        assert len(tracer.events) == 2
        assert tracer.events[0].event_type == EventType.NODE_ENTER
        assert tracer.events[1].event_type == EventType.ERROR
        assert "test error" in tracer.events[1].output_summary
        assert tracer.events[1].duration_ms is not None

    def test_node_span_nested(self):
        tracer = Tracer("test_npc")
        with tracer.node_span("executor"):
            tracer.trace("executor", EventType.MEMORY_READ, output_summary="3 memories")
            tracer.trace("executor", EventType.SKILL_INVOKE, output_summary="conversation")
        assert len(tracer.events) == 4
        types = [e.event_type for e in tracer.events]
        assert types == [
            EventType.NODE_ENTER,
            EventType.MEMORY_READ,
            EventType.SKILL_INVOKE,
            EventType.NODE_EXIT,
        ]


class TestTracerOutput:
    def _build_sample_tracer(self) -> Tracer:
        tracer = Tracer("village_elder")
        with tracer.node_span("planner"):
            tracer.trace(
                "planner", EventType.TASK_CREATED, output_summary="Created 2 tasks"
            )
        with tracer.node_span("executor"):
            tracer.trace("executor", EventType.MEMORY_READ, output_summary="5 memories")
        with tracer.node_span("reflector"):
            tracer.trace(
                "reflector", EventType.MEMORY_WRITE, output_summary="stored 1 event"
            )
        return tracer

    def test_to_log_lines_readable(self):
        tracer = self._build_sample_tracer()
        lines = tracer.to_log_lines()
        assert len(lines) > 0
        # Each line should contain a timestamp and event type
        for line in lines:
            assert "[" in line
            assert "]" in line

    def test_to_log_lines_contains_node_names(self):
        tracer = self._build_sample_tracer()
        text = "\n".join(tracer.to_log_lines())
        assert "planner" in text
        assert "executor" in text
        assert "reflector" in text

    def test_to_json_roundtrip(self):
        tracer = self._build_sample_tracer()
        json_str = tracer.to_json()
        parsed = json.loads(json_str)
        assert isinstance(parsed, list)
        assert len(parsed) == len(tracer.events)
        # Verify roundtrip: each parsed dict should reconstruct a TraceEvent
        for item in parsed:
            event = TraceEvent(**item)
            assert event.agent_name == "village_elder"

    def test_to_json_valid_json(self):
        tracer = self._build_sample_tracer()
        json_str = tracer.to_json()
        parsed = json.loads(json_str)
        assert isinstance(parsed, list)

    def test_summary_format(self):
        tracer = self._build_sample_tracer()
        s = tracer.summary()
        # Should contain node names and timing
        assert "Planner" in s
        assert "Executor" in s
        assert "Reflector" in s
        assert "ms]" in s
        assert "->" in s

    def test_summary_empty_tracer(self):
        tracer = Tracer("test_npc")
        s = tracer.summary()
        assert "empty" in s
        assert "ms]" in s

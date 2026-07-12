from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import chromadb
from langchain_core.messages import AIMessage, BaseMessage

from annie.npc.agent import NPCAgent
from annie.npc.core.context import AgentContext
from annie.npc.core.response import ActionRequest, AgentResponse
from annie.npc.core.routes import AgentRoute
from annie.npc.tools.base_tool import ToolContext
from annie.town import (
    CurrentAction,
    NPCRegistry,
    ScheduleSegment,
    TownEvent,
    TownEventBus,
    TownObject,
    TownPerceptionPolicy,
    TownWorldEngine,
    run_multi_npc_days,
    create_small_town_state,
    run_multi_npc_day,
)


def _town_engine(tmp_path: Path) -> TownWorldEngine:
    return TownWorldEngine(
        create_small_town_state(),
        chroma_client=chromadb.PersistentClient(path=str(tmp_path / "vs")),
        history_dir=tmp_path / "history",
    )


def _tool(context: AgentContext, name: str):
    return next(tool for tool in context.tools if tool.name == name)


class _NoopAgent:
    def run(self, context: AgentContext) -> AgentResponse:
        return AgentResponse()


class _ToolRecordingLLM:
    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls: list[list[BaseMessage]] = []
        self.bound_tool_names: list[list[str]] = []

    def bind_tools(self, tools):
        names: list[str] = []
        for tool in tools:
            names.append(tool["function"]["name"])
        self.bound_tool_names.append(names)
        return self

    def invoke(self, messages, **_):
        self.calls.append(list(messages))
        if not self._responses:
            return AIMessage(content="")
        nxt = self._responses.pop(0)
        if isinstance(nxt, AIMessage):
            return nxt
        return AIMessage(content=str(nxt))


class _AliceSpeaksAgent:
    def run(self, context: AgentContext) -> AgentResponse:
        if context.npc_id == "bob":
            raise AssertionError("Bob should not consume Alice's same-tick speech")
        return AgentResponse(
            actions=[
                ActionRequest(
                    type="speak_to",
                    payload={"target_npc_id": "bob", "text": "早上好，Bob。"},
                )
            ]
        )


class _BobConsumesAgent:
    def __init__(self) -> None:
        self.inputs: list[tuple[str, str]] = []

    def run(self, context: AgentContext) -> AgentResponse:
        self.inputs.append((context.npc_id, context.input_event))
        return AgentResponse()


class _RecordingAgent:
    def __init__(self) -> None:
        self.ran: list[str] = []
        self.current_actions_seen: dict[str, dict[str, object] | None] = {}

    def run(self, context: AgentContext) -> AgentResponse:
        self.ran.append(context.npc_id)
        self.current_actions_seen[context.npc_id] = context.extra["town"].get(
            "current_action"
        )
        return AgentResponse()


class _TwoToolAgent:
    def run(self, context: AgentContext) -> AgentResponse:
        if context.extra.get("town", {}).get("conversation_session_id"):
            return AgentResponse(dialogue="早上好。")
        tool_context = ToolContext(agent_context=context, runtime={})
        _tool(context, "move_to").safe_call(
            {"destination_id": "town_square"},
            tool_context,
        )
        _tool(context, "talk_to").safe_call(
            {"target_npc_id": "bob", "topic_or_reason": "早上好。"},
            tool_context,
        )
        return AgentResponse()


class _WaitAgent:
    def __init__(self, minutes: int) -> None:
        self.minutes = minutes

    def run(self, context: AgentContext) -> AgentResponse:
        tool_context = ToolContext(agent_context=context, runtime={})
        _tool(context, "wait").safe_call({"minutes": self.minutes}, tool_context)
        return AgentResponse()


class _SmallTownDrivingAgent:
    def __init__(self) -> None:
        self._spoke: set[str] = set()
        self._interacted: set[str] = set()

    def run(self, context: AgentContext) -> AgentResponse:
        town = context.extra["town"]
        if town.get("conversation_session_id"):
            return AgentResponse(dialogue="好的。")
        tool_context = ToolContext(agent_context=context, runtime={})
        npc_id = context.npc_id
        location = town["location_id"]
        target = town["current_schedule_target_location_id"]
        exits = town["exits"]
        visible_npcs = town["visible_npc_ids"]
        object_ids = town["object_ids"]

        if npc_id == "clara" and location == "library" and "bookshelf" in object_ids:
            if "clara_bookshelf" not in self._interacted:
                _tool(context, "interact_with").safe_call(
                    {"object_id": "bookshelf", "intent": "整理归还书籍"},
                    tool_context,
                )
                self._interacted.add("clara_bookshelf")
            _tool(context, "complete_current_schedule").safe_call(
                {"note": "书籍已经整理完毕"},
                tool_context,
            )
            return AgentResponse()

        if npc_id == "alice" and location == "cafe" and "bob" in visible_npcs:
            if "alice_bob" not in self._spoke:
                _tool(context, "talk_to").safe_call(
                    {"target_npc_id": "bob", "topic_or_reason": "我来买一杯咖啡。"},
                    tool_context,
                )
                self._spoke.add("alice_bob")
            _tool(context, "complete_current_schedule").safe_call(
                {"note": "已经到咖啡馆并向 Bob 点单"},
                tool_context,
            )
            return AgentResponse()

        if npc_id == "bob" and ("Alice" in context.input_event or "alice" in context.input_event):
            if "alice" in visible_npcs:
                _tool(context, "talk_to").safe_call(
                    {"target_npc_id": "alice", "topic_or_reason": "马上为你准备。"},
                    tool_context,
                )
            return AgentResponse()

        if location == target:
            _tool(context, "complete_current_schedule").safe_call(
                {"note": "已经在目标地点"},
                tool_context,
            )
            return AgentResponse()

        if target in exits:
            destination = target
        else:
            destination = exits[0]
        _tool(context, "move_to").safe_call({"destination_id": destination}, tool_context)
        return AgentResponse()


class _ConversationAgent:
    def __init__(self, turns: dict[str, list[str]]) -> None:
        self.turns = {npc_id: list(lines) for npc_id, lines in turns.items()}
        self.inputs: list[tuple[str, str]] = []
        self.contexts: list[AgentContext] = []

    def run(self, context: AgentContext) -> AgentResponse:
        self.inputs.append((context.npc_id, context.input_event))
        self.contexts.append(context)
        town = context.extra.get("town", {})
        if town.get("conversation_session_id"):
            lines = self.turns.setdefault(context.npc_id, [])
            return AgentResponse(dialogue=lines.pop(0) if lines else "嗯。")
        if context.npc_id == "alice":
            tool_context = ToolContext(agent_context=context, runtime={})
            _tool(context, "talk_to").safe_call(
                {"target_npc_id": "bob", "topic_or_reason": "咖啡推荐"},
                tool_context,
            )
        return AgentResponse()


class _ReflectionAgent:
    def __init__(self, response: AgentResponse) -> None:
        self.response = response
        self.contexts: list[AgentContext] = []

    def run(self, context: AgentContext) -> AgentResponse:
        self.contexts.append(context)
        return self.response


def _complete_current_segment(engine: TownWorldEngine, npc_id: str) -> None:
    segment = engine.state.current_schedule_segment(npc_id)
    if segment is not None:
        engine.state.complete_schedule_segment(npc_id, segment, "test setup")


def test_npc_registry_tracks_state_and_active_filter() -> None:
    state = create_small_town_state()
    registry = NPCRegistry.from_state(state)
    registry.set_active("bob", False)

    state.move_npc("alice", "town_square")
    state.residents["alice"].location_id = "library"
    state.npc_locations["alice"] = "town_square"
    registry.sync_from_state(state)

    assert registry.active_ids(["alice", "bob", "clara"]) == ["alice", "clara"]
    assert registry.location_for("alice") == "library"


def test_event_bus_routes_targeted_events_and_deduplicates_local_events() -> None:
    bus = TownEventBus()
    targeted = TownEvent(
        id="direct",
        minute=480,
        location_id="cafe",
        actor_id="alice",
        event_type="speech",
        summary="Alice called Bob.",
        target_ids=["bob"],
    )
    local = TownEvent(
        id="local",
        minute=480,
        location_id="cafe",
        actor_id="gm",
        event_type="urgent",
        summary="An urgent local event.",
    )

    bus.publish(targeted)
    assert bus.drain("bob") == [targeted]
    assert bus.drain("bob") == []

    first = bus.unseen_visible_events("bob", [local], should_activate=lambda _: True)
    bus.mark_seen("bob", (event.id for event in first))
    second = bus.unseen_visible_events("bob", [local], should_activate=lambda _: True)

    assert first == [local]
    assert second == []


def test_speech_event_routes_to_next_tick_not_same_tick(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.move_npc("alice", "town_square")
    engine.state.move_npc("alice", "cafe")
    segment = engine.state.current_schedule_segment("bob")
    assert segment is not None
    engine.state.complete_schedule_segment("bob", segment, "pre-completed for routing test")

    first_records = engine.step(_AliceSpeaksAgent(), ["alice", "bob"])

    assert [record["npc_id"] for record in first_records] == ["alice"]
    assert engine._inboxes["bob"]

    agent = _BobConsumesAgent()
    second_records = engine.step(agent, ["bob"])

    assert [record["npc_id"] for record in second_records] == ["bob"]
    assert agent.inputs[0][0] == "bob"
    assert "Alice" in agent.inputs[0][1] or "alice" in agent.inputs[0][1]


def test_finished_idle_npc_ignores_ordinary_local_event(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.clock.minute = 10 * 60
    engine.state.events.append(
        TownEvent(
            id="ordinary_cafe_event",
            minute=10 * 60,
            location_id="cafe",
            actor_id="gm",
            event_type="notice",
            summary="咖啡馆里传来普通的杯盘声。",
        )
    )
    agent = _RecordingAgent()

    records = engine.step(agent, ["bob"])

    assert records == []
    assert agent.ran == []


def test_direct_target_event_activates_finished_idle_npc(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.clock.minute = 10 * 60
    engine.state.events.append(
        TownEvent(
            id="direct_cafe_event",
            minute=10 * 60,
            location_id="cafe",
            actor_id="gm",
            event_type="notice",
            summary="有人专门叫 Bob 去看柜台。",
            target_ids=["bob"],
        )
    )
    agent = _RecordingAgent()

    records = engine.step(agent, ["bob"])

    assert [record["npc_id"] for record in records] == ["bob"]
    assert agent.ran == ["bob"]


def test_tick_runs_ready_npcs_by_action_end_time(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.current_actions["bob"] = CurrentAction(
        npc_id="bob",
        action_type="wait",
        location_id="cafe",
        start_minute=8 * 60,
        duration_minutes=15,
        status="waiting",
    )
    engine.state.current_actions["alice"] = CurrentAction(
        npc_id="alice",
        action_type="wait",
        location_id="home_alice",
        start_minute=8 * 60,
        duration_minutes=5,
        status="waiting",
    )
    engine.state.clock.minute = 8 * 60 + 10
    agent = _RecordingAgent()

    records = engine.step(agent, ["bob", "alice"])

    assert [record["npc_id"] for record in records] == ["alice"]
    assert agent.ran == ["alice"]
    assert engine.replay_log[-1]["skipped_npc_ids"] == ["bob"]
    assert engine.replay_log[-1]["skipped_reasons"]["bob"] == "action_in_progress"
    assert engine.replay_log[-1]["current_action_lifecycle"]["bob"]["end_minute"] == 8 * 60 + 15


def test_due_current_action_finalizes_before_activation(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.set_current_action(
        "alice",
        CurrentAction(
            npc_id="alice",
            action_type="wait",
            location_id="home_alice",
            start_minute=8 * 60,
            duration_minutes=10,
            status="waiting",
            summary="Alice is waiting.",
        ),
    )
    engine.state.clock.minute = 8 * 60 + 10
    agent = _RecordingAgent()

    records = engine.step(agent, ["alice"])

    assert [record["npc_id"] for record in records] == ["alice"]
    assert agent.current_actions_seen["alice"] is None
    assert engine.state.current_action_for("alice") is None
    finalized = engine.replay_log[-1]["finalized_actions"]
    assert finalized[0]["npc_id"] == "alice"
    assert finalized[0]["action_type"] == "wait"
    assert finalized[0]["lifecycle_state"] == "finalized"
    assert engine.replay_log[-1]["snapshot"]["minute"] == 8 * 60 + 10
    assert engine.state.clock.minute == 8 * 60 + 20


def test_action_duration_gating_short_equal_and_longer_than_tick(tmp_path) -> None:
    cases = [
        (5, 8 * 60 + 10, True),
        (10, 8 * 60 + 10, True),
        (15, 8 * 60 + 10, False),
    ]
    for duration, tick_minute, should_run in cases:
        engine = _town_engine(tmp_path / str(duration))
        engine.state.set_current_action(
            "alice",
            CurrentAction(
                npc_id="alice",
                action_type="wait",
                location_id="home_alice",
                start_minute=8 * 60,
                duration_minutes=duration,
                status="waiting",
            ),
        )
        engine.state.clock.minute = tick_minute
        agent = _RecordingAgent()

        records = engine.step(agent, ["alice"])

        if should_run:
            assert [record["npc_id"] for record in records] == ["alice"]
            assert engine.state.current_action_for("alice") is None
            assert engine.replay_log[-1]["finalized_actions"][0]["end_minute"] == 8 * 60 + duration
        else:
            assert records == []
            assert engine.state.current_action_for("alice").end_minute == 8 * 60 + duration
            assert engine.replay_log[-1]["skipped_reasons"]["alice"] == "action_in_progress"


def test_resumed_due_and_in_progress_actions_match_continuous_execution(tmp_path) -> None:
    continuous = _town_engine(tmp_path / "continuous")
    continuous.step(_WaitAgent(15), ["alice"])
    snapshot_path = continuous.save_runtime_snapshot(tmp_path / "snapshot.json")
    resumed = TownWorldEngine.from_runtime_snapshot(
        snapshot_path,
        chroma_client=chromadb.PersistentClient(path=str(tmp_path / "resumed_vs")),
        memory_path=tmp_path / "resumed_vs",
        history_dir=tmp_path / "resumed_history",
    )

    continuous_blocked = continuous.step(_RecordingAgent(), ["alice"])
    resumed_blocked = resumed.step(_RecordingAgent(), ["alice"])

    assert continuous_blocked == resumed_blocked == []
    assert continuous.replay_log[-1]["skipped_reasons"] == resumed.replay_log[-1]["skipped_reasons"]
    assert continuous.state.current_action_for("alice").end_minute == resumed.state.current_action_for("alice").end_minute

    continuous.state.clock.minute = continuous.state.current_action_for("alice").end_minute
    resumed.state.clock.minute = resumed.state.current_action_for("alice").end_minute

    continuous_due = continuous.step(_RecordingAgent(), ["alice"])
    resumed_due = resumed.step(_RecordingAgent(), ["alice"])

    assert [record["npc_id"] for record in continuous_due] == ["alice"]
    assert [record["npc_id"] for record in resumed_due] == ["alice"]
    assert continuous.replay_log[-1]["finalized_actions"] == resumed.replay_log[-1]["finalized_actions"]


def test_ready_npcs_use_action_end_time_before_input_order(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.current_actions["bob"] = CurrentAction(
        npc_id="bob",
        action_type="wait",
        location_id="cafe",
        start_minute=8 * 60,
        duration_minutes=8,
        status="waiting",
    )
    engine.state.current_actions["alice"] = CurrentAction(
        npc_id="alice",
        action_type="wait",
        location_id="home_alice",
        start_minute=8 * 60,
        duration_minutes=5,
        status="waiting",
    )
    engine.state.clock.minute = 8 * 60 + 10
    agent = _RecordingAgent()

    records = engine.step(agent, ["bob", "alice"])

    assert [record["npc_id"] for record in records] == ["alice", "bob"]
    assert agent.ran == ["alice", "bob"]


def test_multiple_tools_chain_action_start_times(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.move_npc("bob", "town_square")

    records = engine.step(_TwoToolAgent(), ["alice"])

    logged_actions = cast(list[dict[str, Any]], records[0]["logged_actions"])
    assert [item["action_type"] for item in logged_actions] == ["move_to", "talk_to"]
    assert logged_actions[0]["facts"]["duration_minutes"] == 5
    assert logged_actions[0]["facts"]["end_minute"] == 8 * 60 + 5
    assert logged_actions[1]["facts"]["start_minute"] == 8 * 60 + 5
    assert logged_actions[1]["facts"]["duration_minutes"] == 1


def test_town_context_uses_local_visible_events_only(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.events.append(
        TownEvent(
            id="near",
            minute=480,
            location_id="home_alice",
            actor_id="gm",
            event_type="notice",
            summary="门口有人敲门。",
        )
    )
    engine.state.events.append(
        TownEvent(
            id="remote",
            minute=480,
            location_id="cafe",
            actor_id="gm",
            event_type="notice",
            summary="咖啡馆发生远处事件。",
        )
    )
    engine.state.events.append(
        TownEvent(
            id="hidden",
            minute=480,
            location_id="home_alice",
            actor_id="gm",
            event_type="secret",
            summary="隐藏事件不应出现。",
            visible=False,
        )
    )

    context = engine.build_context("alice", "观察本地环境。")

    assert "门口有人敲门" in context.situation
    assert "咖啡馆发生远处事件" not in context.situation
    assert "隐藏事件不应出现" not in context.situation
    assert isinstance(context.extra["town"]["current_schedule"], dict)
    assert context.extra["town"]["perception"]["visible_event_ids"] == ["near"]


def test_bounded_perception_selects_visible_content_deterministically(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.perception_policy = TownPerceptionPolicy(
        max_events=2,
        max_objects=2,
        max_npcs=1,
        max_exits=2,
    )
    engine.state.move_npc("alice", "town_square")
    engine.state.move_npc("bob", "town_square")
    engine.state.move_npc("clara", "town_square")
    square = engine.state.locations["town_square"]
    for object_id in ["aaa_marker", "bbb_marker", "ccc_marker"]:
        engine.state.objects[object_id] = TownObject(
            id=object_id,
            name=f"测试物体 {object_id}",
            location_id="town_square",
            description=f"{object_id} 的描述。",
        )
        square.object_ids.append(object_id)
    for event in [
        TownEvent(
            id="ordinary_old",
            minute=480,
            location_id="town_square",
            actor_id="gm",
            event_type="notice",
            summary="普通旧事件。",
        ),
        TownEvent(
            id="ordinary_new",
            minute=490,
            location_id="town_square",
            actor_id="gm",
            event_type="notice",
            summary="普通新事件。",
        ),
        TownEvent(
            id="targeted",
            minute=470,
            location_id="town_square",
            actor_id="gm",
            event_type="notice",
            summary="专门给 Alice 的事件。",
            target_ids=["alice"],
        ),
        TownEvent(
            id="urgent",
            minute=469,
            location_id="town_square",
            actor_id="gm",
            event_type="urgent",
            summary="紧急事件。",
        ),
    ]:
        engine.state.events.append(event)

    first = engine.build_context("alice", "观察广场。")
    second = engine.build_context("alice", "再次观察广场。")
    town = first.extra["town"]

    assert town["visible_event_ids"] == ["targeted", "urgent"]
    assert town["object_ids"] == ["aaa_marker", "bbb_marker"]
    assert town["visible_npc_ids"] == ["bob"]
    assert town["exits"] == ["home_alice", "cafe"]
    assert second.extra["town"]["visible_event_ids"] == town["visible_event_ids"]
    assert second.extra["town"]["object_ids"] == town["object_ids"]
    assert "普通新事件" not in first.situation
    assert "ccc_marker 的描述" not in first.situation
    observed = engine.observe("alice")
    assert [event["id"] for event in observed["local_events"]] == ["targeted", "urgent"]
    assert [obj["id"] for obj in observed["objects"]] == ["aaa_marker", "bbb_marker"]


def test_resident_spatial_memory_renders_known_invisible_places_and_objects(tmp_path) -> None:
    engine = _town_engine(tmp_path)

    context = engine.build_context("alice", "回忆镇上的地点。")
    town = context.extra["town"]
    known_location_ids = {
        location["id"] for location in town["perception"]["known_locations"]
    }
    known_object_ids = {
        obj["id"] for obj in town["perception"]["known_objects"]
    }

    assert "town_square" not in known_location_ids
    assert {"cafe", "library", "clinic"} <= known_location_ids
    assert "breakfast_table" not in known_object_ids
    assert {"cafe_counter", "bookshelf"} <= known_object_ids
    assert town["object_ids"] == ["breakfast_table"]
    assert "已知但当前不可见地点" in context.situation
    assert "咖啡馆柜台" in context.situation


def test_perception_smoke_script_reports_pass() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/show_town_perception.py"],
        cwd=Path(__file__).parents[2],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS targeted and urgent events survive tight event budget" in result.stdout


def test_replay_snapshot_smoke_script_reports_pass() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/show_town_replay_snapshot.py"],
        cwd=Path(__file__).parents[2],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS checkpoint snapshot present" in result.stdout
    assert "PASS reflection artifact present" in result.stdout


def test_targeted_visible_event_revises_resident_schedule(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.set_location("alice", "town_square")
    engine.state.events.append(
        TownEvent(
            id="targeted_square_revision",
            minute=8 * 60,
            location_id="town_square",
            actor_id="gm",
            event_type="notice",
            summary="有人专门请 Alice 处理广场公告。",
            target_ids=["alice"],
        )
    )

    context = engine.build_context("alice", "观察广场。")
    revision = context.extra["town"]["schedule_revision"]
    current_schedule = context.extra["town"]["current_schedule"]

    assert revision["revised"] is True
    assert revision["event_id"] == "targeted_square_revision"
    assert current_schedule["location_id"] == "town_square"
    assert current_schedule["intent"] == "处理事件：有人专门请 Alice 处理广场公告。"
    assert engine.state.residents["alice"].schedule is engine.state.schedules["alice"]
    assert engine.state.residents["alice"].schedule[0].subtasks == [
        "event:targeted_square_revision"
    ]
    assert engine.state.residents["alice"].poignancy == 4
    event_evidence = engine.state.residents["alice"].reflection_evidence[0]
    assert event_evidence.evidence_type == "event"
    assert event_evidence.metadata["event_id"] == "targeted_square_revision"
    assert event_evidence.metadata["event_type"] == "notice"
    assert event_evidence.metadata["location_id"] == "town_square"
    assert "处理事件：有人专门请 Alice 处理广场公告。" in context.situation


def test_urgent_event_survives_budget_and_triggers_schedule_revision(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.perception_policy = TownPerceptionPolicy(max_events=1)
    engine.state.set_location("alice", "town_square")
    engine.state.events.extend(
        [
            TownEvent(
                id="ordinary_newer",
                minute=8 * 60 + 5,
                location_id="town_square",
                actor_id="gm",
                event_type="notice",
                summary="普通的新事件。",
            ),
            TownEvent(
                id="urgent_older",
                minute=8 * 60,
                location_id="town_square",
                actor_id="gm",
                event_type="urgent",
                summary="广场有紧急铃声。",
            ),
        ]
    )

    context = engine.build_context("alice", "观察广场。")
    town = context.extra["town"]

    assert town["visible_event_ids"] == ["urgent_older"]
    assert town["schedule_revision"]["revised"] is True
    assert town["schedule_revision"]["event_id"] == "urgent_older"
    assert engine.state.residents["alice"].poignancy == 5
    assert engine.state.residents["alice"].reflection_evidence[0].poignancy == 5
    assert engine.state.current_schedule_segment("alice").location_id == "town_square"


def test_hidden_remote_and_budget_excluded_events_do_not_revise_schedule(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.perception_policy = TownPerceptionPolicy(max_events=1)
    engine.state.set_location("alice", "town_square")
    engine.state.events.extend(
        [
            TownEvent(
                id="ordinary_visible",
                minute=8 * 60 + 5,
                location_id="town_square",
                actor_id="gm",
                event_type="notice",
                summary="普通可见事件。",
            ),
            TownEvent(
                id="ordinary_excluded",
                minute=8 * 60,
                location_id="town_square",
                actor_id="gm",
                event_type="notice",
                summary="预算外普通事件。",
            ),
            TownEvent(
                id="hidden_targeted",
                minute=8 * 60 + 6,
                location_id="town_square",
                actor_id="gm",
                event_type="notice",
                summary="隐藏定向事件。",
                visible=False,
                target_ids=["alice"],
            ),
            TownEvent(
                id="remote_urgent",
                minute=8 * 60 + 7,
                location_id="cafe",
                actor_id="gm",
                event_type="urgent",
                summary="远处紧急事件。",
            ),
        ]
    )

    context = engine.build_context("alice", "观察广场。")
    town = context.extra["town"]

    assert town["visible_event_ids"] == ["ordinary_visible"]
    assert town["schedule_revision"] == {"revised": False}
    assert engine.state.current_schedule_segment("alice").location_id == "home_alice"


def test_reprocessing_same_event_does_not_duplicate_schedule_revision(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.set_location("alice", "town_square")
    engine.state.events.append(
        TownEvent(
            id="targeted_once",
            minute=8 * 60,
            location_id="town_square",
            actor_id="gm",
            event_type="notice",
            summary="专门请 Alice 处理一次。",
            target_ids=["alice"],
        )
    )

    first = engine.build_context("alice", "第一次观察。")
    second = engine.build_context("alice", "第二次观察。")
    event_segments = [
        segment
        for segment in engine.state.schedule_for("alice")
        if "event:targeted_once" in segment.subtasks
    ]

    assert first.extra["town"]["schedule_revision"]["revised"] is True
    assert second.extra["town"]["schedule_revision"]["revised"] is True
    assert len(event_segments) == 1


def test_talk_and_interact_tools_return_structured_observations(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.move_npc("alice", "town_square")
    engine.state.move_npc("alice", "cafe")
    context = engine.build_context("alice", "和 Bob 互动。")
    tool_context = ToolContext(agent_context=context, runtime={})

    engine._active_step_agent = _ConversationAgent({"alice": ["早上好。"], "bob": ["早上好。"]})
    speak = _tool(context, "talk_to").safe_call(
        {"target_npc_id": "bob", "topic_or_reason": "早上好。"},
        tool_context,
    )
    engine._active_step_agent = None
    interact = _tool(context, "interact_with").safe_call(
        {"object_id": "cafe_counter", "intent": "点咖啡"},
        tool_context,
    )
    failed = _tool(context, "interact_with").safe_call(
        {"object_id": "bookshelf", "intent": "拿书"},
        tool_context,
    )

    assert speak["success"] is True
    assert speak["result"]["status"] == "succeeded"
    assert speak["result"]["action_type"] == "talk_to"
    assert interact["result"]["facts"]["object_id"] == "cafe_counter"
    assert failed["result"]["status"] == "failed"
    assert failed["result"]["reason"] == "object_not_visible"


def test_affordance_context_and_tools_are_semantic_not_map_backed(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.move_npc("alice", "town_square")
    context = engine.build_context("alice", "查看公告栏。")
    tool_context = ToolContext(agent_context=context, runtime={})
    town = context.extra["town"]

    assert "location_affordances" in town
    assert "object_affordances" in town
    assert town["object_affordances"]["notice_board"][0]["id"] == "read_notices"
    assert "tile" not in str(town["perception"]).lower()
    assert "map" not in str(town["perception"]).lower()
    assert "affordances=阅读公告(read_notices)" in context.situation

    inspected = _tool(context, "inspect_affordances").safe_call(
        {"target_id": "notice_board"},
        tool_context,
    )
    used = _tool(context, "use_affordance").safe_call(
        {
            "target_id": "notice_board",
            "affordance_id": "post_notice",
            "note": "咖啡馆今天九点有新豆试饮。",
        },
        tool_context,
    )

    assert inspected["success"] is True
    assert inspected["result"]["facts"]["targets"][0]["affordances"][0]["id"] == "read_notices"
    assert used["success"] is True
    assert used["result"]["status"] == "succeeded"
    assert used["result"]["facts"]["target_kind"] == "object"
    assert used["result"]["facts"]["affordance_id"] == "post_notice"
    assert used["result"]["facts"]["duration_minutes"] == 5
    assert engine.state.events[-1].event_type == "notice"
    assert engine.action_log[-1]["action_type"] == "use_affordance"


def test_affordance_tools_reject_unknown_and_unsupported_without_state_change(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.move_npc("alice", "town_square")
    context = engine.build_context("alice", "尝试错误 affordance。")
    tool_context = ToolContext(agent_context=context, runtime={})
    event_count = len(engine.state.events)
    action_count = len(engine.action_log)

    unsupported = _tool(context, "use_affordance").safe_call(
        {
            "target_id": "notice_board",
            "affordance_id": "brew_coffee",
            "note": "尝试在公告栏煮咖啡。",
        },
        tool_context,
    )
    unknown_target = _tool(context, "use_affordance").safe_call(
        {
            "target_id": "missing_kiosk",
            "affordance_id": "read_notices",
        },
        tool_context,
    )
    free_text_unsupported = _tool(context, "interact_with").safe_call(
        {"object_id": "notice_board", "intent": "煮咖啡"},
        tool_context,
    )

    assert unsupported["result"]["status"] == "failed"
    assert unsupported["result"]["reason"] == "unsupported_affordance"
    assert "available_affordances" in unsupported["result"]["facts"]
    assert unknown_target["result"]["status"] == "failed"
    assert unknown_target["result"]["reason"] == "target_not_visible"
    assert free_text_unsupported["result"]["status"] == "failed"
    assert free_text_unsupported["result"]["reason"] == "unsupported_affordance"
    assert len(engine.state.events) == event_count
    assert len(engine.action_log) == action_count + 3
    assert all(item["status"] == "failed" for item in engine.action_log[-3:])


def test_speak_to_same_direction_has_short_cooldown(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.move_npc("alice", "town_square")
    engine.state.move_npc("alice", "cafe")

    first = engine.speak_to("alice", "bob", "早上好。")
    repeat = engine.speak_to("alice", "bob", "还是早上好。")
    reply = engine.speak_to("bob", "alice", "早上好，Alice。")

    assert first.status == "succeeded"
    assert repeat.status == "failed"
    assert repeat.reason == "recent_speak_to_cooldown"
    assert reply.status == "succeeded"


def test_observe_does_not_create_current_action_or_action_log(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    context = engine.build_context("alice", "观察环境。")
    tool_context = ToolContext(agent_context=context, runtime={})

    result = _tool(context, "observe").safe_call({}, tool_context)

    assert result["success"] is True
    assert result["result"]["status"] == "succeeded"
    assert "alice" not in engine.state.current_actions
    assert engine.action_log == []


def test_inspect_affordances_is_free_even_when_target_is_invalid(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    context = engine.build_context("alice", "查看 affordance。")
    tool_context = ToolContext(agent_context=context, runtime={})

    result = _tool(context, "inspect_affordances").safe_call(
        {"target_id": "missing_target"},
        tool_context,
    )

    assert result["success"] is True
    assert result["result"]["status"] == "failed"
    assert result["result"]["facts"]["occupancy_model"] == "instant_free"
    assert "alice" not in engine.state.current_actions


def test_town_agent_binding_excludes_disabled_builtin_action_tools(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    llm = _ToolRecordingLLM([
        '{"decision":"skip","reason":"single action","tasks":[]}',
        AIMessage(
            content="",
            tool_calls=[{"name": "observe", "args": {}, "id": "call_observe"}],
        ),
        "观察完成。",
        '{"reflection":"ok","facts":[],"relationship_notes":[]}',
    ])

    NPCAgent(llm=llm, max_retries=0).run(engine.build_context("alice", "观察环境。"))

    assert llm.bound_tool_names
    first_executor_tools = llm.bound_tool_names[0]
    assert "declare_action" not in first_executor_tools
    assert "request_action" not in first_executor_tools
    assert "memory_store" not in first_executor_tools
    assert "observe" in first_executor_tools


def test_town_wait_commit_stops_same_activation_followup(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    llm = _ToolRecordingLLM([
        AIMessage(
            content="",
            tool_calls=[{"name": "wait", "args": {"minutes": 20}, "id": "call_wait"}],
        ),
    ])

    response = NPCAgent(llm=llm, max_retries=0).run(
        engine.build_context("alice", "原地等待。")
    )
    engine.handle_response("alice", response)

    assert len(llm.calls) == 1
    assert engine.state.current_actions["alice"].action_type == "wait"
    assert engine.state.current_actions["alice"].end_minute == 8 * 60 + 20
    assert [item["action_type"] for item in engine.action_log] == ["wait"]

    records = engine.step(_NoopAgent(), ["alice"])
    assert records == []
    assert engine.replay_log[-1]["skipped_npc_ids"] == ["alice"]


def test_interrupt_immediate_effect_keeps_world_state_and_records_evidence(tmp_path) -> None:
    engine = _town_engine(tmp_path)

    move = engine.move_to("alice", "town_square")
    evidence = engine.interrupt_current_action("alice", "priority_event")

    assert move.status == "succeeded"
    assert engine.state.location_id_for("alice") == "town_square"
    assert engine.state.current_action_for("alice") is None
    assert evidence is not None
    assert evidence["lifecycle_state"] == "interrupted"
    assert evidence["effect_applied"] is True
    assert evidence["interrupted_reason"] == "priority_event"
    assert engine.action_log[-1]["lifecycle_state"] == "interrupted"


def test_multi_npc_day_smoke_generates_replay(tmp_path) -> None:
    engine = _town_engine(tmp_path)

    result = run_multi_npc_day(
        engine,
        _SmallTownDrivingAgent(),
        ["alice", "bob", "clara"],
        start_minute=8 * 60,
        end_minute=10 * 60,
        max_ticks=18,
        replay_dir=tmp_path / "replay",
    )

    action_types = [item["action_type"] for item in engine.action_log]
    assert result.ok is True
    assert "move_to" in action_types
    assert "talk_to" in action_types
    assert "interact_with" in action_types
    assert engine.state.npc_locations["alice"] == "cafe"
    assert len(engine.state.completed_schedule_segments["alice"]) == 2

    actions_path = result.replay_paths["actions"]
    timeline_path = result.replay_paths["timeline"]
    checkpoints_path = result.replay_paths["checkpoints"]
    reflections_path = result.replay_paths["reflections"]
    action_rows = [json.loads(line) for line in actions_path.read_text().splitlines()]
    checkpoint_rows = [
        json.loads(line) for line in checkpoints_path.read_text().splitlines()
    ]

    assert any(row["action_type"] == "move_to" for row in action_rows)
    assert any(row["action_type"] == "talk_to" for row in action_rows)
    assert "talk_to" in timeline_path.read_text()
    assert checkpoint_rows
    assert reflections_path.exists()
    first_snapshot = checkpoint_rows[0]["snapshot"]
    assert first_snapshot["day"] == 1
    assert first_snapshot["minute"] == 8 * 60
    assert first_snapshot["time"] == "08:00"
    assert set(first_snapshot["residents"]) == {"alice", "bob", "clara"}
    alice = first_snapshot["residents"]["alice"]
    assert alice["location_id"] == "home_alice"
    assert alice["current_schedule"]["location_id"] == "home_alice"
    assert alice["current_action"] is None
    assert checkpoint_rows[0]["records"][0]["logged_actions"][0]["action_type"] == "complete_current_schedule"
    assert (
        checkpoint_rows[0]["records"][0]["logged_actions"][0]["occupancy_model"]
        == "instant_free"
    )
    assert alice["schedule_completed"] is True
    assert "reflection_due" in alice
    assert "reflection_evidence_count" in alice
    assert isinstance(first_snapshot["conversation_sessions"], list)
    assert isinstance(first_snapshot["reflection_events"], list)


def test_replay_snapshot_records_closed_conversation_session(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.move_npc("alice", "town_square")
    engine.state.move_npc("alice", "cafe")
    _complete_current_segment(engine, "bob")
    agent = _ConversationAgent(
        {
            "alice": [
                "Bob，今天有什么咖啡推荐吗？",
                "谢谢你，我先去坐下了。",
            ],
            "bob": [
                "今天的哥伦比亚豆子很适合清晨。",
                "好的，回头见。",
            ],
        }
    )

    result = run_multi_npc_day(
        engine,
        agent,
        ["alice", "bob"],
        start_minute=8 * 60,
        max_ticks=1,
        replay_dir=tmp_path / "replay",
    )

    checkpoint = json.loads(result.replay_paths["checkpoints"].read_text().splitlines()[0])
    sessions = checkpoint["snapshot"]["conversation_sessions"]
    assert len(sessions) == 1
    assert sessions[0] == {
        "id": "conversation_1",
        "participants": ["alice", "bob"],
        "status": "closed",
        "location_id": "cafe",
        "topic_or_reason": "咖啡推荐",
        "turn_count": 4,
        "started_minute": 8 * 60,
        "ended_minute": 8 * 60 + 1,
        "close_reason": "natural_close",
    }
    assert "transcript" not in sessions[0]


def test_runner_reflection_is_opt_in_and_replayable(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.move_npc("alice", "town_square")
    engine.state.events.append(
        TownEvent(
            id="urgent_replay_reflection",
            minute=8 * 60,
            location_id="town_square",
            actor_id="gm",
            event_type="urgent",
            summary="广场响起紧急铃声。",
        )
    )
    engine.build_context("alice", "观察紧急事件。")
    engine.finish_schedule_segment("alice", "处理完紧急铃声")
    assert engine.reflection_due_for("alice") is True

    no_reflection = run_multi_npc_day(
        engine,
        _NoopAgent(),
        ["alice"],
        start_minute=8 * 60,
        max_ticks=1,
        replay_dir=tmp_path / "no_reflection",
    )

    assert no_reflection.ticks[0].reflection_count == 0
    assert engine.reflection_due_for("alice") is True
    assert engine.reflection_log == []
    no_reflection_checkpoint = json.loads(
        no_reflection.replay_paths["checkpoints"].read_text().splitlines()[0]
    )
    assert no_reflection_checkpoint["snapshot"]["reflection_events"] == []

    reflected = run_multi_npc_day(
        engine,
        _NoopAgent(),
        ["alice"],
        start_minute=8 * 60,
        max_ticks=1,
        replay_dir=tmp_path / "with_reflection",
        reflection_agent=_ReflectionAgent(
            AgentResponse(reflection="Alice 决定以后优先处理广场紧急事件。")
        ),
    )

    assert reflected.ticks[0].reflection_count == 1
    assert reflected.ticks[0].ran_npc_ids == []
    reflection_rows = [
        json.loads(line)
        for line in reflected.replay_paths["reflections"].read_text().splitlines()
    ]
    assert len(reflection_rows) == 1
    assert reflection_rows[0]["tick"] == reflected.ticks[0].tick
    assert reflection_rows[0]["npc_id"] == "alice"
    assert reflection_rows[0]["content"] == "Alice 决定以后优先处理广场紧急事件。"
    assert reflection_rows[0]["trigger_poignancy"] == 7
    assert reflection_rows[0]["evidence_count"] == 2
    checkpoint = json.loads(
        reflected.replay_paths["checkpoints"].read_text().splitlines()[-1]
    )
    snapshot = checkpoint["snapshot"]
    assert snapshot["reflection_events"] == reflection_rows
    assert snapshot["residents"]["alice"]["poignancy"] == 0
    assert snapshot["residents"]["alice"]["reflection_due"] is False
    assert snapshot["residents"]["alice"]["reflection_evidence_count"] == 0


def test_replay_snapshot_key_fields_are_deterministic(tmp_path) -> None:
    first = _run_replay_signature(tmp_path / "first")
    second = _run_replay_signature(tmp_path / "second")

    assert first == second


def test_multi_npc_day_defaults_to_resident_ids(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.npc_locations.clear()

    result = run_multi_npc_day(
        engine,
        _NoopAgent(),
        start_minute=8 * 60,
        end_minute=8 * 60,
    )

    assert result.ok is True
    assert result.npc_ids == engine.state.resident_ids()


def test_start_day_renews_schedule_and_keeps_state_town_owned(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    original_agent = object()
    engine.state.clock.day = 2

    assert engine.state.current_schedule_segment("alice") is None

    accepted = engine.start_day_for_resident(
        "alice",
        day=2,
        start_minute=8 * 60,
        end_minute=10 * 60,
    )
    resident = engine.state.residents["alice"]

    assert accepted
    assert resident.schedule_day == 2
    assert all(segment.day == 2 for segment in accepted)
    assert resident.scratch.currently
    assert resident.day_plans[2].wake_up_minute == 8 * 60
    assert resident.day_plans[2].daily_intentions
    assert engine.state.current_schedule_segment("alice") is not None
    assert not hasattr(original_agent, "schedule")
    assert any(item["stage"] == "accepted_schedule" for item in engine.planning_log)


def test_start_day_reuses_valid_current_day_schedule(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    existing = [
        ScheduleSegment(
            npc_id="alice",
            start_minute=8 * 60,
            duration_minutes=30,
            location_id="home_alice",
            intent="吃早餐",
            day=2,
        )
    ]
    engine.state.set_schedule("alice", existing, day=2)
    engine.state.clock.day = 2

    accepted = engine.start_day_for_resident(
        "alice",
        day=2,
        start_minute=8 * 60,
        end_minute=10 * 60,
    )

    assert accepted == existing
    assert engine.state.schedule_for("alice") == existing
    assert engine.state.residents["alice"].day_plans[2].validation[
        "reused_existing_schedule"
    ] is True
    assert [item["stage"] for item in engine.planning_log] == [
        "existing_schedule_reused"
    ]


def test_start_day_clears_previous_day_current_action(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.set_current_action(
        "alice",
        CurrentAction(
            npc_id="alice",
            action_type="wait",
            location_id="home_alice",
            start_minute=8 * 60,
            duration_minutes=35,
            status="waiting",
        ),
    )

    engine.start_day_for_resident(
        "alice",
        day=2,
        start_minute=8 * 60,
        end_minute=9 * 60,
    )
    assert engine.state.current_action_for("alice") is None

    result = run_multi_npc_day(
        engine,
        _SmallTownDrivingAgent(),
        ["alice"],
        start_minute=8 * 60,
        end_minute=9 * 60,
        max_ticks=8,
    )

    assert result.ticks[0].skipped_npc_ids == []
    assert result.ticks[0].ran_npc_ids == ["alice"]


def test_day_end_summary_is_distilled_memory(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.start_day_for_resident("alice", day=1, start_minute=8 * 60, end_minute=9 * 60)
    engine.finish_schedule_segment("alice", "完成第一段")

    summary = engine.end_day_for_resident("alice", day=1)

    assert "第 1 天" in summary
    records = engine.memory_for("alice").grep(
        "",
        category="impression",
        metadata_filters={"source": "town_day_summary", "day": 1},
    )
    assert len(records) == 1
    assert "完成" in records[0].content
    assert records[0].metadata["completed_count"] == 1
    day_plan = engine.state.residents["alice"].day_plans[1]
    assert day_plan.schedule_evidence
    assert any(item["status"] == "completed" for item in day_plan.schedule_evidence)
    assert "schedule_evidence" in records[0].metadata


def test_day_end_records_unfinished_overdue_and_interrupted_evidence(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    schedule = [
        ScheduleSegment(
            npc_id="alice",
            start_minute=8 * 60,
            duration_minutes=20,
            location_id="home_alice",
            intent="吃早餐",
            day=1,
        ),
        ScheduleSegment(
            npc_id="alice",
            start_minute=8 * 60 + 20,
            duration_minutes=20,
            location_id="cafe",
            intent="买咖啡",
            day=1,
        ),
    ]
    engine.plan_day_for_resident("alice", schedule, day=1)
    engine.finish_schedule_segment("alice", "吃完早餐")
    engine.move_to("alice", "town_square")
    engine.interrupt_current_action("alice", "urgent_event", minute=8 * 60 + 25)
    engine.state.clock.minute = 9 * 60

    engine.end_day_for_resident("alice", day=1)

    evidence = engine.state.residents["alice"].day_plans[1].schedule_evidence
    assert evidence[0]["status"] == "completed"
    assert evidence[1]["status"] == "missed"
    assert "overdue" in evidence[1]["flags"]
    assert "interrupted" in evidence[1]["flags"]
    planning_evidence = engine.retrieve_planning_evidence("alice")
    assert any(
        item["metadata"].get("source") == "town_unfinished_schedule"
        for item in planning_evidence
    )


def test_decompose_and_revise_active_segment_preserves_completion_evidence(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    subtasks = engine.decompose_current_schedule_segment("alice")

    assert subtasks
    assert engine.state.current_schedule_segment("alice").subtasks == subtasks

    engine.finish_schedule_segment("alice", "早餐完成")
    engine.state.clock.minute = 9 * 60
    revised = engine.revise_current_schedule_segment(
        "alice",
        reason="waiting",
        subtasks=["询问咖啡是否备好", "完成后调用 finish_schedule_segment"],
    )

    assert revised is not None
    assert revised.intent == "买咖啡"
    assert "revision:waiting" in revised.subtasks
    assert engine.state.completed_schedule_segments["alice"][0].start_minute == 8 * 60
    revision_logs = [
        item for item in engine.planning_log if item["stage"] == "schedule_revision"
    ]
    assert revision_logs
    assert revision_logs[-1]["completed_evidence"][0]["start_minute"] == 8 * 60


def test_schedule_segment_state_predicates_and_overdue_recoverability(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    segment = ScheduleSegment(
        npc_id="alice",
        start_minute=8 * 60,
        duration_minutes=20,
        location_id="home_alice",
        intent="吃早餐",
    )
    engine.plan_day_for_resident("alice", [segment], day=1)

    active = engine.schedule_segment_state("alice", segment, minute=8 * 60 + 5)
    overdue = engine.schedule_segment_state("alice", segment, minute=8 * 60 + 20)
    missed = engine.schedule_segment_state(
        "alice",
        segment,
        minute=9 * 60,
        day_end_reached=True,
    )

    assert active["base_status"] == "active"
    assert overdue["base_status"] == "pending"
    assert overdue["overdue"] is True
    assert missed["base_status"] == "missed"
    assert missed["missed"] is True
    assert engine.state.completed_schedule_segments.get("alice", []) == []

    engine.state.clock.minute = 8 * 60 + 20
    engine.step(_NoopAgent(), ["alice"])
    assert any(item["stage"] == "schedule_overdue" for item in engine.planning_log)
    assert engine.state.completed_schedule_segments.get("alice", []) == []

    engine.finish_schedule_segment("alice", "迟到但完成")
    completed = engine.schedule_segment_state("alice", segment, minute=8 * 60 + 30)
    assert completed["base_status"] == "completed"


def test_ordinary_actions_do_not_complete_schedule_segment(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    segment = engine.state.current_schedule_segment("alice")

    engine.move_to("alice", "town_square")

    assert segment is not None
    assert not engine.state.is_schedule_segment_complete("alice", segment)


def test_loop_guards_record_failed_actions_chatter_and_schedule_drift(tmp_path) -> None:
    engine = _town_engine(tmp_path)

    for _ in range(3):
        engine.move_to("alice", "moon")
    assert any(
        event["guard_type"] == "repeated_failed_action"
        for event in engine.loop_guard_events
    )

    engine.state.set_location("alice", "town_square")
    engine.state.move_npc("bob", "town_square")
    engine.speak_cooldown_minutes = 0
    for text in ["一句话一", "一句话二", "一句话三"]:
        engine.speak_to("alice", "bob", text)
    assert any(
        event["guard_type"] == "repeated_low_value_action"
        for event in engine.loop_guard_events
    )

    engine.plan_day_for_resident(
        "alice",
        [
            ScheduleSegment(
                npc_id="alice",
                start_minute=8 * 60,
                duration_minutes=60,
                location_id="cafe",
                intent="买咖啡",
            )
        ],
    )
    engine.state.set_location("alice", "home_alice")
    engine.state.clock.minute = 8 * 60 + 40
    engine.wait("alice", 5)

    context = engine.build_context("alice", "检查是否偏离日程。")

    assert any(
        event["guard_type"] == "schedule_drift"
        for event in engine.loop_guard_events
    )
    assert context.extra["town"]["loop_guard_events"]
    assert "最近 guard" in context.extra["town"]["prompt_policy"]["repeat_guard_hint"]


def test_conversation_cooldown_does_not_exempt_physical_schedule_drift(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.plan_day_for_resident(
        "alice",
        [
            ScheduleSegment(
                npc_id="alice",
                start_minute=8 * 60,
                duration_minutes=60,
                location_id="cafe",
                intent="买咖啡",
            )
        ],
    )
    engine.state.set_location("alice", "home_alice")
    engine.state.set_location("bob", "home_alice")
    engine.state.clock.minute = 8 * 60 + 40
    engine.state.conversation_cooldowns["alice|bob"] = 9 * 60

    engine._active_step_agent = _NoopAgent()
    try:
        result = engine.start_conversation("alice", "bob", "再聊咖啡")
    finally:
        engine._active_step_agent = None

    drift_events = [
        event
        for event in engine.loop_guard_events
        if event["guard_type"] == "schedule_drift"
    ]
    assert result.status == "failed"
    assert result.reason == "recent_conversation_cooldown"
    assert drift_events
    assert drift_events[-1]["details"]["schedule_location_id"] == "cafe"


def test_schedule_drift_records_blacklist_evidence_for_away_behavior(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.plan_day_for_resident(
        "alice",
        [
            ScheduleSegment(
                npc_id="alice",
                start_minute=8 * 60,
                duration_minutes=60,
                location_id="cafe",
                intent="买咖啡",
            )
        ],
    )
    engine.state.set_location("alice", "home_alice")
    engine.state.clock.minute = 8 * 60 + 40

    engine.wait("alice", 1)
    engine.state.clear_current_action("alice")
    engine.wait("alice", 1)
    engine.state.clear_current_action("alice")
    engine.execute_action("alice", ActionRequest(type="move", payload={"to": "clinic"}))
    context = engine.build_context("alice", "检查是否偏离日程。")

    drift = [
        event
        for event in engine.loop_guard_events
        if event["guard_type"] == "schedule_drift"
    ][-1]
    evidence = cast(list[dict[str, object]], drift["details"]["blacklist_evidence"])
    evidence_kinds = {item["kind"] for item in evidence}

    assert "repeated_non_schedule_locations" in evidence_kinds
    assert "repeated_wait_away_from_goal" in evidence_kinds
    assert "failed_moves_not_approaching_goal" in evidence_kinds
    assert context.extra["town"]["loop_guard_events"]


def test_schedule_drift_counts_repeated_free_observation_away_from_goal(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.plan_day_for_resident(
        "alice",
        [
            ScheduleSegment(
                npc_id="alice",
                start_minute=8 * 60,
                duration_minutes=60,
                location_id="cafe",
                intent="买咖啡",
            )
        ],
    )
    engine.state.set_location("alice", "home_alice")
    engine.state.clock.minute = 8 * 60 + 40

    engine.observe_action("alice")
    engine.inspect_affordances_action("alice")

    drift = [
        event
        for event in engine.loop_guard_events
        if event["guard_type"] == "schedule_drift"
    ][-1]
    evidence = cast(list[dict[str, object]], drift["details"]["blacklist_evidence"])

    assert any(
        item["kind"] == "repeated_free_observation_away_from_goal"
        for item in evidence
    )
    assert engine.action_log == []


def test_multi_day_runner_replays_schedule_planning_evidence(tmp_path) -> None:
    engine = _town_engine(tmp_path)

    result = run_multi_npc_days(
        engine,
        _SmallTownDrivingAgent(),
        ["alice"],
        days=2,
        start_minute=8 * 60,
        end_minute=9 * 60,
        max_ticks_per_day=8,
        replay_dir=tmp_path / "replay",
    )

    checkpoint_rows = [
        json.loads(line)
        for line in result.replay_paths["checkpoints"].read_text().splitlines()
    ]
    final_snapshot = checkpoint_rows[-1]["snapshot"]

    assert result.ok is True
    assert engine.state.residents["alice"].schedule_day == 2
    assert final_snapshot["planning_checkpoints"]
    assert any(
        item["stage"] == "accepted_schedule" and item["day"] == 2
        for item in final_snapshot["planning_checkpoints"]
    )
    assert final_snapshot["residents"]["alice"]["day_plan"]["day"] == 2
    assert "planning" in result.replay_paths["timeline"].read_text()


def test_forced_guard_check_does_not_pollute_real_replay(tmp_path) -> None:
    from scripts.validate_townworld_phase1_multiday_real_llm import (
        CheckBoard,
        force_revision_and_loop_guards,
    )

    engine = _town_engine(tmp_path / "real")
    result = run_multi_npc_day(
        engine,
        _SmallTownDrivingAgent(),
        ["alice"],
        start_minute=8 * 60,
        end_minute=9 * 60,
        max_ticks=8,
        replay_dir=tmp_path / "real_replay",
    )
    checkpoint_rows = [
        json.loads(line)
        for line in result.replay_paths["checkpoints"].read_text().splitlines()
    ]

    assert result.ok is True
    assert engine.loop_guard_events == []
    assert checkpoint_rows[-1]["snapshot"]["loop_guard_events"] == []

    forced = force_revision_and_loop_guards(
        "alice",
        CheckBoard(),
        run_dir=tmp_path / "forced",
    )
    replay_paths = engine.write_replay_artifacts(tmp_path / "real_replay_after_forced")
    final_rows = [
        json.loads(line)
        for line in replay_paths["checkpoints"].read_text().splitlines()
    ]

    assert forced["forced_guard_check_count"] > 0
    assert engine.loop_guard_events == []
    assert final_rows[-1]["snapshot"]["loop_guard_events"] == []


def _run_replay_signature(tmp_path: Path) -> list[dict[str, object]]:
    engine = _town_engine(tmp_path)
    result = run_multi_npc_day(
        engine,
        _SmallTownDrivingAgent(),
        ["alice", "bob", "clara"],
        start_minute=8 * 60,
        end_minute=10 * 60,
        max_ticks=18,
        replay_dir=tmp_path / "replay",
    )
    rows = [
        json.loads(line)
        for line in result.replay_paths["checkpoints"].read_text().splitlines()
    ]
    signature: list[dict[str, object]] = []
    for row in rows:
        snapshot = row["snapshot"]
        signature.append(
            {
                "tick": row["tick"],
                "minute": row["minute"],
                "residents": {
                    npc_id: {
                        "location_id": resident["location_id"],
                        "current_schedule": resident["current_schedule"],
                        "reflection_evidence_count": resident[
                            "reflection_evidence_count"
                        ],
                    }
                    for npc_id, resident in sorted(snapshot["residents"].items())
                },
                "conversation_sessions": [
                    {
                        "id": session["id"],
                        "status": session["status"],
                        "participants": session["participants"],
                        "turn_count": session["turn_count"],
                    }
                    for session in snapshot["conversation_sessions"]
                ],
            }
        )
    return signature


def test_multi_npc_day_runs_new_resident_schedule(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.plan_day_for_resident(
        "alice",
        [
            ScheduleSegment(
                npc_id="alice",
                start_minute=8 * 60,
                duration_minutes=30,
                location_id="town_square",
                intent="查看公告板",
            )
        ],
    )

    result = run_multi_npc_day(
        engine,
        _SmallTownDrivingAgent(),
        ["alice"],
        start_minute=8 * 60,
        max_ticks=4,
    )

    assert result.ok is True
    assert engine.state.location_id_for("alice") == "town_square"
    assert len(engine.state.completed_schedule_segments["alice"]) == 1


def test_multi_npc_day_default_ids_run_generated_resident_schedule(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    for npc_id in ["bob", "clara"]:
        _complete_current_segment(engine, npc_id)
    engine.plan_day_for_resident(
        "alice",
        [
            ScheduleSegment(
                npc_id="alice",
                start_minute=8 * 60,
                duration_minutes=30,
                location_id="town_square",
                intent="查看公告板",
            )
        ],
    )

    result = run_multi_npc_day(
        engine,
        _SmallTownDrivingAgent(),
        start_minute=8 * 60,
        max_ticks=4,
    )

    assert result.npc_ids == engine.state.resident_ids()
    assert result.ok is True
    assert engine.state.location_id_for("alice") == "town_square"
    assert len(engine.state.completed_schedule_segments["alice"]) == 1


def test_multi_npc_day_breaks_when_end_minute_reached_on_last_tick(tmp_path) -> None:
    engine = _town_engine(tmp_path)

    result = run_multi_npc_day(
        engine,
        _NoopAgent(),
        ["alice", "bob", "clara"],
        start_minute=8 * 60,
        end_minute=10 * 60,
        max_ticks=12,
    )

    assert result.ok is True
    assert result.note == ""
    assert engine.state.clock.minute == 10 * 60
    assert len(result.ticks) == 12
    assert result.reached_end_minute is True
    assert result.max_ticks_exhausted is False


def test_multi_npc_day_reports_completion_and_tick_exhaustion(tmp_path) -> None:
    complete_engine = _town_engine(tmp_path / "complete")
    complete_engine.plan_day_for_resident(
        "alice",
        [
            ScheduleSegment(
                npc_id="alice",
                start_minute=8 * 60,
                duration_minutes=30,
                location_id="town_square",
                intent="查看公告板",
            )
        ],
    )
    complete_result = run_multi_npc_day(
        complete_engine,
        _SmallTownDrivingAgent(),
        ["alice"],
        start_minute=8 * 60,
        max_ticks=4,
    )

    exhausted_engine = _town_engine(tmp_path / "exhausted")
    exhausted_result = run_multi_npc_day(
        exhausted_engine,
        _NoopAgent(),
        ["alice"],
        start_minute=8 * 60,
        end_minute=9 * 60,
        max_ticks=1,
    )

    assert complete_result.ok is True
    assert complete_result.all_current_schedules_complete is True
    assert complete_result.max_ticks_exhausted is False
    assert exhausted_result.ok is False
    assert exhausted_result.max_ticks_exhausted is True
    assert exhausted_result.reached_end_minute is False


def test_start_conversation_closes_session_and_does_not_ping_pong(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.move_npc("alice", "town_square")
    engine.state.move_npc("alice", "cafe")
    _complete_current_segment(engine, "alice")
    _complete_current_segment(engine, "bob")
    agent = _ConversationAgent(
        {
            "alice": [
                "Bob，今天有什么咖啡推荐吗？\nconversation is ongoing via start_conversation",
                "听起来不错，谢谢你，我先去坐下了。",
            ],
            "bob": [
                "今天的哥伦比亚豆子很适合清晨。\nstart_conversation should continue",
                "好的，我马上准备，回头见。",
            ],
        }
    )

    engine._active_step_agent = agent
    try:
        result = engine.start_conversation("alice", "bob", "咖啡推荐")
    finally:
        engine._active_step_agent = None

    assert result.status == "succeeded"
    session = next(iter(engine.state.conversation_sessions.values()))
    assert session.status == "closed"
    assert session.close_reason == "natural_close"
    assert len(session.turns) == 4
    assert engine.state.current_actions["alice"].action_type == "conversation"
    assert engine.state.current_actions["bob"].action_type == "conversation"
    assert any(item["action_type"] == "start_conversation" for item in engine.action_log)
    turn_contexts = [
        context
        for context in agent.contexts
        if context.extra.get("town", {}).get("conversation_session_id") == session.id
    ]
    assert turn_contexts
    assert all(context.tools == [] for context in turn_contexts)
    assert all(
        context.route == AgentRoute.DIALOGUE
        for context in turn_contexts
    )
    assert all("可以用记忆工具" in context.world_rules for context in turn_contexts)
    assert turn_contexts[0].extra["town"]["conversation_partner_id"] == "bob"
    assert turn_contexts[0].extra["town"]["relationship_cues"][0]["partner_npc_id"] == "bob"

    alice_impressions = engine.memory_for("alice").grep(
        "",
        category="impression",
        metadata_filters={
            "source": "town_conversation",
            "partner_npc_id": "bob",
        },
    )
    assert len(alice_impressions) == 1
    impression = alice_impressions[0]
    assert impression.metadata["conversation_session_id"] == session.id
    assert impression.metadata["location_id"] == "cafe"
    assert impression.metadata["close_reason"] == "natural_close"
    assert impression.metadata["topic_or_reason"] == "咖啡推荐"
    assert impression.metadata["relationship_pair_key"] == "alice|bob"
    assert "alice" in str(impression.metadata["relationship_summary"])
    assert "bob" in str(impression.metadata["relationship_summary"])
    assert "咖啡推荐" in str(impression.metadata["follow_up_intentions"])
    assert "alice:" not in impression.content
    assert "bob:" not in impression.content
    assert "conversation is ongoing via" not in impression.content
    assert "start_conversation" not in impression.content
    alice_resident = engine.state.residents["alice"]
    bob_resident = engine.state.residents["bob"]
    assert alice_resident.poignancy == 3
    assert bob_resident.poignancy == 3
    alice_evidence = alice_resident.reflection_evidence[0]
    assert alice_evidence.evidence_type == "conversation"
    assert alice_evidence.metadata["conversation_session_id"] == session.id
    assert alice_evidence.metadata["partner_npc_id"] == "bob"
    assert alice_evidence.metadata["location_id"] == "cafe"
    assert alice_evidence.metadata["close_reason"] == "natural_close"
    assert alice_evidence.metadata["topic_or_reason"] == "咖啡推荐"
    assert alice_evidence.metadata["relationship_pair_key"] == "alice|bob"
    assert "咖啡推荐" in str(alice_evidence.metadata["follow_up_intentions"])

    alice_followups = engine.memory_for("alice").grep(
        "",
        category="todo",
        metadata_filters={
            "source": "town_conversation_followup",
            "partner_npc_id": "bob",
            "status": "open",
        },
    )
    assert alice_followups
    assert "Bob" in alice_followups[0].content

    history_entries = engine.history_for("alice").read_last(1)
    assert history_entries[0].speaker == "town_conversation"
    assert "alice: Bob，今天有什么咖啡推荐吗？" in history_entries[0].content
    assert "bob: 今天的哥伦比亚豆子很适合清晨。" in history_entries[0].content
    assert "start_conversation" not in history_entries[0].content

    engine.state.clock.minute = engine.state.current_actions["alice"].end_minute
    later_context = engine.build_context("alice", "考虑是否继续和 Bob 交流。")
    cue = later_context.extra["town"]["relationship_cues"][0]
    assert cue["partner_npc_id"] == "bob"
    assert cue["cooldown_until_minute"] == session.ended_minute + engine.conversation_cooldown_minutes
    assert cue["conversation_block_reason"] == "recent_conversation_cooldown"
    assert cue["recent_conversations"] == [
        "bob: 08:00 咖啡推荐，结束=natural_close"
    ]
    assert cue["impressions"] == [impression.content]
    assert "关系线索：bob" in later_context.situation
    assert "冷却" in later_context.extra["town"]["prompt_policy"]["conversation_policy_hint"]

    planning_context = engine.build_daily_planning_context(
        "alice",
        start_minute=9 * 60,
        end_minute=10 * 60,
    )
    assert planning_context.extra["town"]["relationship_evidence"]
    assert "可用于改变今日计划的关系/对话证据" in planning_context.situation
    assert "follow_up=" in planning_context.situation

    engine.state.clock.day = 2
    day2_schedule = engine.start_day_for_resident(
        "alice",
        day=2,
        start_minute=9 * 60,
        end_minute=10 * 60,
    )
    assert day2_schedule[0].intent.startswith("跟进与 bob 的话题")

    engine.state.clock.minute = engine.state.current_actions["bob"].end_minute
    second_records = engine.step(agent, ["bob"])

    assert second_records == []


def test_schedule_completion_records_reflection_evidence(tmp_path) -> None:
    engine = _town_engine(tmp_path)

    result = engine.finish_schedule_segment("alice", "吃完早餐")

    assert result.status == "succeeded"
    resident = engine.state.residents["alice"]
    assert resident.poignancy == 2
    assert len(resident.reflection_evidence) == 1
    evidence = resident.reflection_evidence[0]
    assert evidence.evidence_type == "schedule"
    assert evidence.summary.startswith("完成日程")
    assert evidence.metadata["segment_start_minute"] == 8 * 60
    assert evidence.metadata["location_id"] == "home_alice"
    assert evidence.metadata["note"] == "吃完早餐"


def test_reflection_due_context_and_successful_memory_write(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.move_npc("alice", "town_square")
    engine.state.events.append(
        TownEvent(
            id="urgent_reflection",
            minute=8 * 60,
            location_id="town_square",
            actor_id="gm",
            event_type="urgent",
            summary="广场响起紧急铃声。",
        )
    )
    engine.build_context("alice", "观察紧急事件。")

    assert engine.reflection_due_for("alice") is False
    engine.finish_schedule_segment("alice", "处理完紧急铃声")
    assert engine.reflection_due_for("alice") is True

    context = engine.build_reflection_context("alice")
    town_reflection = context.extra["town"]["reflection"]
    assert context.tools == []
    assert context.route == AgentRoute.REFLECTION
    assert "move_to" in context.extra["disabled_tools"]
    assert town_reflection["poignancy"] == 7
    assert town_reflection["threshold"] == engine.reflection_threshold
    assert len(town_reflection["evidence"]) == 2
    assert "广场响起紧急铃声" in context.situation
    assert "transcript" not in context.situation.lower()
    assert "alice:" not in context.situation.lower()
    assert "bob:" not in context.situation.lower()

    agent = _ReflectionAgent(
        AgentResponse(reflection="Alice 意识到紧急事件会打乱日程，需要优先处理。")
    )

    assert engine.reflect_for_resident("alice", agent) is True

    resident = engine.state.residents["alice"]
    assert resident.poignancy == 0
    assert resident.reflection_evidence == []
    assert len(agent.contexts) == 1
    reflections = engine.memory_for("alice").grep(
        "",
        category="reflection",
        metadata_filters={"source": "town_reflection"},
    )
    assert len(reflections) == 1
    reflection = reflections[0]
    assert "紧急事件会打乱日程" in reflection.content
    assert reflection.metadata["trigger_poignancy"] == 7
    assert reflection.metadata["evidence_count"] == 2
    assert "event" in str(reflection.metadata["evidence_types"])
    assert "schedule" in str(reflection.metadata["evidence_types"])
    assert "urgent_reflection" not in reflection.content
    assert "episodic" not in {record.category for record in reflections}

    planning_context = engine.build_daily_planning_context(
        "alice",
        start_minute=9 * 60,
        end_minute=10 * 60,
    )
    assert any(
        item["metadata"].get("source") == "town_reflection"
        for item in planning_context.extra["town"]["planning_evidence"]
    )
    assert "紧急事件会打乱日程" in planning_context.situation


def test_conversation_or_reflection_evidence_changes_next_day_schedule(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    baseline_intent = engine.state.schedule_for("alice")[0].intent
    engine.memory_for("alice").remember(
        "跟进与 Bob 的话题：确认咖啡馆晨间推荐",
        category="todo",
        metadata={
            "source": "town_conversation_followup",
            "status": "open",
            "todo_id": "conversation_followup_test",
            "partner_npc_id": "bob",
            "conversation_session_id": "conversation_test",
        },
    )
    engine.memory_for("alice").remember(
        "Alice 认识到早晨应先处理昨天遗留的社交承诺。",
        category="reflection",
        metadata={"source": "town_reflection", "trigger_poignancy": 7},
    )

    day2_schedule = engine.start_day_for_resident(
        "alice",
        day=2,
        start_minute=8 * 60,
        end_minute=9 * 60,
    )
    day_plan = engine.state.residents["alice"].day_plans[2]

    assert day2_schedule[0].intent != baseline_intent
    assert day2_schedule[0].intent == "跟进与 Bob 的话题：确认咖啡馆晨间推荐"
    assert any("社交承诺" in item["content"] for item in day_plan.planning_evidence)


def test_npca_agent_reflection_context_uses_single_direct_llm_call(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.move_npc("alice", "town_square")
    engine.state.events.append(
        TownEvent(
            id="urgent_direct_reflection",
            minute=8 * 60,
            location_id="town_square",
            actor_id="gm",
            event_type="urgent",
            summary="广场响起紧急铃声。",
        )
    )
    engine.build_context("alice", "观察紧急事件。")
    engine.finish_schedule_segment("alice", "处理完紧急铃声")

    llm = _ToolRecordingLLM(["Alice 认识到紧急事件会压缩早餐日程，需要先判断优先级。"])
    agent = NPCAgent(llm=llm, max_retries=0)

    assert engine.reflect_for_resident("alice", agent) is True
    assert len(llm.calls) == 1
    assert llm.bound_tool_names == []
    prompt_text = "\n".join(str(message.content) for message in llm.calls[0])
    assert "请生成可写入长期记忆的反思" in prompt_text
    assert "请根据以下上下文判断是否需要多步骤计划" not in prompt_text

    reflections = engine.memory_for("alice").grep(
        "",
        category="reflection",
        metadata_filters={"source": "town_reflection"},
    )
    assert len(reflections) == 1
    assert "紧急事件会压缩早餐日程" in reflections[0].content


def test_npca_agent_direct_dialogue_context_uses_single_llm_call(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.move_npc("alice", "town_square")
    engine.state.move_npc("alice", "cafe")
    _complete_current_segment(engine, "alice")
    _complete_current_segment(engine, "bob")
    llm = _ToolRecordingLLM(["好的，你先去广场吧，回头再聊。", "好，回头见。"])
    agent = NPCAgent(llm=llm, max_retries=0)

    engine._active_step_agent = agent
    try:
        result = engine.start_conversation("alice", "bob", "咖啡推荐")
    finally:
        engine._active_step_agent = None

    assert result.status == "succeeded"
    assert len(llm.calls) >= 1
    assert llm.bound_tool_names
    assert llm.bound_tool_names[0] == [
        "memory_recall",
        "memory_grep",
        "inner_monologue",
    ]
    prompt_text = "\n".join(str(message.content) for message in llm.calls[0])
    assert "请输出这一轮台词" in prompt_text
    assert "请根据以下上下文判断是否需要多步骤计划" not in prompt_text
    session = next(iter(engine.state.conversation_sessions.values()))
    assert session.turns[0].text == "好的，你先去广场吧，回头再聊。"


def test_empty_reflection_response_keeps_evidence_and_memory_clean(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.move_npc("alice", "town_square")
    engine.state.events.append(
        TownEvent(
            id="urgent_empty_reflection",
            minute=8 * 60,
            location_id="town_square",
            actor_id="gm",
            event_type="urgent",
            summary="广场有紧急事件。",
        )
    )
    engine.build_context("alice", "观察紧急事件。")
    engine.finish_schedule_segment("alice", "处理事件")
    resident = engine.state.residents["alice"]
    evidence_before = list(resident.reflection_evidence)

    agent = _ReflectionAgent(AgentResponse())

    assert engine.reflect_for_resident("alice", agent) is False
    assert resident.poignancy == 7
    assert resident.reflection_evidence == evidence_before
    assert (
        engine.memory_for("alice").grep(
            "",
            category="reflection",
            metadata_filters={"source": "town_reflection"},
        )
        == []
    )


def test_start_conversation_respects_recent_pair_cooldown(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.move_npc("alice", "town_square")
    engine.state.move_npc("alice", "cafe")
    _complete_current_segment(engine, "alice")
    _complete_current_segment(engine, "bob")
    first_agent = _ConversationAgent(
        {
            "alice": ["有推荐吗？", "谢谢，我先这样。"],
            "bob": ["有的，试试哥伦比亚豆子。", "好的，待会见。"],
        }
    )
    engine._active_step_agent = first_agent
    try:
        engine.start_conversation("alice", "bob", "咖啡推荐")
    finally:
        engine._active_step_agent = None
    engine.state.clock.minute = engine.state.current_actions["alice"].end_minute

    engine._active_step_agent = first_agent
    try:
        result = engine.start_conversation("alice", "bob", "再聊咖啡")
    finally:
        engine._active_step_agent = None

    assert result.status == "failed"
    assert result.reason == "recent_conversation_cooldown"
    assert result.facts["cooldown_until_minute"] == (
        engine.state.conversation_cooldowns["alice|bob"]
    )
    assert engine.action_log[-1]["action_type"] == "start_conversation"
    assert engine.action_log[-1]["status"] == "failed"
    assert engine.action_log[-1]["facts"]["cooldown_until_time"]


def test_talk_to_empty_first_turn_retries_then_fails_without_cooldown(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.move_npc("alice", "town_square")
    engine.state.move_npc("alice", "cafe")
    _complete_current_segment(engine, "alice")
    _complete_current_segment(engine, "bob")
    agent = _ConversationAgent({"alice": ["", ""], "bob": ["不应调用"]})

    engine._active_step_agent = agent
    try:
        result = engine.talk_to("alice", "bob", "咖啡推荐")
    finally:
        engine._active_step_agent = None

    assert result.status == "failed"
    assert result.reason == "empty_conversation"
    assert result.facts["turn_count"] == 0
    assert "alice|bob" not in engine.state.conversation_cooldowns
    assert not any(
        item.matched_action_type == "talk_to"
        for item in engine.state.completed_schedule_segments.get("alice", [])
    )


def test_start_conversation_rejects_busy_participant(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.move_npc("alice", "town_square")
    engine.state.move_npc("alice", "cafe")
    engine.state.current_actions["bob"] = CurrentAction(
        npc_id="bob",
        action_type="conversation",
        location_id="cafe",
        start_minute=8 * 60,
        duration_minutes=10,
        status="conversation",
    )
    agent = _ConversationAgent({"alice": ["你好。"], "bob": ["你好。"]})
    context = engine.build_context("alice", "想和 Bob 聊天。")
    tool_context = ToolContext(agent_context=context, runtime={})
    engine._active_step_agent = agent
    try:
        result = _tool(context, "talk_to").safe_call(
            {"target_npc_id": "bob", "topic_or_reason": "问候"},
            tool_context,
        )
    finally:
        engine._active_step_agent = None

    assert result["success"] is True
    assert result["result"]["status"] == "failed"
    assert result["result"]["reason"] == "already_in_conversation"

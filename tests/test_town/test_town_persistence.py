from __future__ import annotations

import json
import shutil
from pathlib import Path

import chromadb
import pytest

from annie.npc.core.context import AgentContext
from annie.npc.core.response import AgentResponse
from annie.npc.tools.base_tool import ToolContext
from annie.town import (
    ConversationSession,
    ConversationTurn,
    CurrentAction,
    ReflectionEvidence,
    ResidentDayPlan,
    ScheduleCompletion,
    ScheduleSegment,
    TownEvent,
    TownPersistenceError,
    TownWorldEngine,
    create_small_town_state,
    load_run_manifest,
    resolve_manifest_paths,
)


def _engine(tmp_path: Path) -> TownWorldEngine:
    memory_path = tmp_path / "vector_store"
    return TownWorldEngine(
        create_small_town_state(),
        chroma_client=chromadb.PersistentClient(path=str(memory_path)),
        memory_path=memory_path,
        history_dir=tmp_path / "history",
    )


def _tool(context: AgentContext, name: str):
    return next(tool for tool in context.tools if tool.name == name)


class _StatelessScheduleAgent:
    def __init__(self) -> None:
        self.contexts: list[AgentContext] = []

    def run(self, context: AgentContext) -> AgentResponse:
        self.contexts.append(context)
        town = context.extra["town"]
        target = town["current_schedule_target_location_id"]
        location = town["location_id"]
        tool_context = ToolContext(agent_context=context, runtime={})
        if location == target:
            _tool(context, "complete_current_schedule").safe_call(
                {"note": "到达目标地点"},
                tool_context,
            )
            return AgentResponse()
        exits = town["exits"]
        destination = target if target in exits else exits[0]
        _tool(context, "move_to").safe_call(
            {"destination_id": destination},
            tool_context,
        )
        return AgentResponse()


def _populate_resumable_state(engine: TownWorldEngine) -> None:
    schedule = [
        ScheduleSegment(
            npc_id="alice",
            start_minute=8 * 60,
            duration_minutes=30,
            location_id="cafe",
            intent="买咖啡",
            subtasks=["走到咖啡馆", "点咖啡"],
            day=1,
        )
    ]
    engine.state.clock.minute = 8 * 60 + 10
    engine.state.set_schedule("alice", schedule, day=1)
    engine.state.set_location("alice", "cafe")
    engine.state.set_current_action(
        "alice",
        CurrentAction(
            npc_id="alice",
            action_type="interact_with",
            location_id="cafe",
            start_minute=8 * 60 + 10,
            duration_minutes=5,
            status="succeeded",
            summary="Alice 正在点咖啡。",
        ),
    )
    engine.state.completed_schedule_segments["alice"] = [
        ScheduleCompletion(
            npc_id="alice",
            start_minute=8 * 60,
            location_id="home_alice",
            note="吃完早餐",
            day=1,
        )
    ]
    resident = engine.state.residents["alice"]
    resident.scratch.currently = "正在咖啡馆执行晨间计划"
    resident.day_plans[1] = ResidentDayPlan(
        day=1,
        currently="买咖啡后去图书馆",
        wake_up_minute=7 * 60,
        daily_intentions=["买咖啡", "整理资料"],
        planning_evidence=[{"source": "memory", "summary": "昨晚决定早点去咖啡馆"}],
        validation={"ok": True},
        schedule_summary="08:00 cafe 买咖啡",
        started_minute=8 * 60,
    )
    resident.poignancy = 3
    resident.reflection_evidence.append(
        ReflectionEvidence(
            id="evidence_1",
            evidence_type="event",
            summary="Bob 提醒 Alice 咖啡馆有新公告。",
            poignancy=3,
            clock_minute=8 * 60 + 5,
            metadata={"event_id": "notice_1"},
        )
    )
    event = TownEvent(
        id="notice_1",
        minute=8 * 60 + 5,
        location_id="cafe",
        actor_id="bob",
        event_type="notice",
        summary="Bob 提醒 Alice 咖啡馆有新公告。",
        target_ids=["alice"],
    )
    engine.state.events.append(event)
    engine.event_bus.publish(event)
    engine.event_bus.mark_seen("bob", ["notice_1"])
    session = ConversationSession(
        id="conversation_1",
        participants=("alice", "bob"),
        initiator_id="alice",
        location_id="cafe",
        topic="公告",
        started_minute=8 * 60 + 6,
        max_turns=4,
        status="closed",
        close_reason="done",
        ended_minute=8 * 60 + 8,
        turns=[
            ConversationTurn(
                speaker_id="alice",
                listener_id="bob",
                text="我看到公告了。",
                minute=8 * 60 + 6,
            )
        ],
    )
    engine.state.conversation_sessions[session.id] = session
    engine.state.conversation_cooldowns["alice|bob"] = 9 * 60
    engine.loop_guard_events.append(
        {
            "day": 1,
            "minute": engine.state.clock.minute,
            "time": engine.state.clock.label(),
            "npc_id": "alice",
            "guard_type": "schedule_drift",
            "message": "测试 guard",
            "details": {"location_id": "cafe"},
        }
    )
    engine._loop_guard_keys.add((1, "alice", "schedule_drift", (("location_id", "cafe"),)))
    engine.planning_log.append({"day": 1, "npc_id": "alice", "stage": "accepted_schedule"})
    engine.replay_log.append(
        {
            "tick": 1,
            "minute": 8 * 60,
            "snapshot": engine.build_replay_snapshot(["alice"], minute=8 * 60),
        }
    )


def test_runtime_snapshot_round_trips_resumable_state(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    _populate_resumable_state(engine)

    snapshot_path = engine.save_runtime_snapshot(tmp_path / "snapshot.json", run_id="roundtrip")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert snapshot["schema_version"] == 1
    for excluded in ("agent", "llm", "chroma_collection", "history_jsonl", "tool_call_stack"):
        assert excluded not in json.dumps(snapshot, ensure_ascii=False).lower()

    loaded = TownWorldEngine.from_runtime_snapshot(
        snapshot_path,
        chroma_client=chromadb.PersistentClient(path=str(tmp_path / "loaded_vs")),
        history_dir=tmp_path / "history",
    )

    assert loaded.state.clock.minute == engine.state.clock.minute
    assert loaded.state.location_id_for("alice") == "cafe"
    assert loaded.state.current_action_for("alice").summary == "Alice 正在点咖啡。"
    assert loaded.state.conversation_sessions["conversation_1"].turns[0].text == "我看到公告了。"
    assert loaded.event_bus.inboxes["alice"][0].id == "notice_1"
    assert loaded.event_bus.seen_event_ids["bob"] == {"notice_1"}
    assert loaded.loop_guard_events == engine.loop_guard_events
    assert loaded.planning_log == engine.planning_log
    assert loaded.replay_log[-1]["tick"] == 1
    assert loaded.state.completed_schedule_segments["alice"][0].note == "吃完早餐"
    context = loaded.build_context("alice", "继续当前计划。")
    assert context.extra["town"]["current_schedule"]["intent"] == "买咖啡"
    assert loaded.state.residents["alice"].scratch.currently == "正在咖啡馆执行晨间计划"


def test_runtime_snapshot_rejects_missing_or_unsupported_schema(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    snapshot = engine.export_runtime_snapshot(run_id="invalid")
    snapshot.pop("schema_version")

    with pytest.raises(TownPersistenceError, match="schema_version"):
        TownWorldEngine.from_runtime_snapshot(snapshot)

    snapshot["schema_version"] = 999
    with pytest.raises(TownPersistenceError, match="unsupported"):
        TownWorldEngine.from_runtime_snapshot(snapshot)

    snapshot["schema_version"] = 1
    snapshot.pop("clock")
    with pytest.raises(TownPersistenceError, match="clock"):
        TownWorldEngine.from_runtime_snapshot(snapshot)


def test_run_manifest_paths_are_relative_and_movable(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "town" / "demo"
    engine = _engine(run_dir)
    replay_dir = run_dir / "replay"
    replay_dir.mkdir(parents=True)
    replay_path = replay_dir / "town_checkpoints.jsonl"
    replay_path.write_text("{}\n", encoding="utf-8")

    paths = engine.save_run(
        run_dir,
        run_id="demo",
        replay_paths={"checkpoints": replay_path},
        write_step_snapshot=True,
        model_summary={"provider": "project-config"},
        validation={"ok": True},
    )
    manifest = load_run_manifest(paths["manifest"])

    assert manifest["latest_snapshot_path"] == "state/latest.json"
    assert manifest["replay_paths"]["checkpoints"] == "replay/town_checkpoints.jsonl"
    assert manifest["history_path"] == "history"
    assert manifest["vector_store_path"] == "vector_store"

    moved = tmp_path / "moved_demo"
    shutil.move(str(run_dir), moved)
    moved_manifest = load_run_manifest(moved / "manifest.json")
    resolved = resolve_manifest_paths(moved, moved_manifest)

    assert resolved["latest_snapshot_path"] == moved / "state" / "latest.json"
    assert resolved["replay_paths"]["checkpoints"] == moved / "replay" / "town_checkpoints.jsonl"
    assert resolved["history_path"] == moved / "history"
    assert resolved["vector_store_path"] == moved / "vector_store"

    resumed = TownWorldEngine.resume_run(
        moved,
        chroma_client=chromadb.PersistentClient(path=str(moved / "vector_store")),
    )
    assert resumed.state.clock.day == engine.state.clock.day


def test_run_manifest_uses_root_relative_paths_with_relative_run_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    run_dir = Path("runs") / "town" / "relative_demo"
    engine = _engine(tmp_path / "backend")

    paths = engine.save_run(run_dir, run_id="relative_demo", write_step_snapshot=True)
    manifest = load_run_manifest(paths["manifest"])

    assert manifest["latest_snapshot_path"] == "state/latest.json"
    assert manifest["step_snapshot_paths"] == ["state/steps/step-000000.json"]
    resolved = resolve_manifest_paths(run_dir, manifest)
    assert resolved["latest_snapshot_path"] == run_dir / "state" / "latest.json"

    resumed = TownWorldEngine.resume_run(
        run_dir,
        chroma_client=chromadb.PersistentClient(path=str(tmp_path / "backend" / "vector_store")),
    )
    assert resumed.state.clock.minute == engine.state.clock.minute


def test_atomic_latest_write_preserves_prior_snapshot_on_failure(tmp_path: Path, monkeypatch) -> None:
    engine = _engine(tmp_path)
    latest = tmp_path / "state" / "latest.json"
    first = engine.save_runtime_snapshot(latest, run_id="atomic")
    first_text = first.read_text(encoding="utf-8")

    from annie.town import engine as engine_module

    def fail_write(path, payload):
        raise OSError("simulated write failure")

    monkeypatch.setattr(engine_module, "write_json_atomic", fail_write)

    with pytest.raises(OSError, match="simulated"):
        engine.save_runtime_snapshot(latest, run_id="atomic")

    assert latest.read_text(encoding="utf-8") == first_text


def test_pause_resume_matches_continuous_stable_behavior(tmp_path: Path) -> None:
    continuous = _engine(tmp_path / "continuous")
    paused = _engine(tmp_path / "paused")
    for engine in (continuous, paused):
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
            day=1,
        )
        engine.state.conversation_cooldowns["alice|bob"] = 9 * 60
        engine.memory_for("alice").remember(
            "Alice 知道咖啡馆今天有新菜单。",
            category="semantic",
            metadata={"source": "pause_resume_test"},
        )

    continuous_agent = _StatelessScheduleAgent()
    for _ in range(4):
        continuous.step(continuous_agent, ["alice"])

    paused_agent = _StatelessScheduleAgent()
    for _ in range(2):
        paused.step(paused_agent, ["alice"])
    paused.save_run(tmp_path / "paused_run", run_id="pause-resume")

    resumed = TownWorldEngine.resume_run(
        tmp_path / "paused_run",
        chroma_client=chromadb.PersistentClient(path=str(tmp_path / "paused" / "vector_store")),
    )
    resumed_agent = _StatelessScheduleAgent()
    for _ in range(2):
        resumed.step(resumed_agent, ["alice"])

    assert _stable_behavior_signature(resumed, ["alice"]) == _stable_behavior_signature(
        continuous,
        ["alice"],
    )
    assert resumed.memory_for("alice").grep(
        "新菜单",
        category="semantic",
        metadata_filters={"source": "pause_resume_test"},
    )
    context = resumed_agent.contexts[0]
    assert context.extra["town"]["current_schedule"]["intent"] == "买咖啡"
    assert resumed_agent is not paused_agent


def test_replay_validation_uses_stable_shape_not_byte_equality(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    engine.replay_log.append(
        {
            "tick": 1,
            "minute": engine.state.clock.minute,
            "path_specific": str(tmp_path / "first"),
            "snapshot": engine.build_replay_snapshot(["alice"]),
        }
    )
    first = _replay_checkpoint_shape(engine)
    first_bytes = json.dumps(engine.replay_log[0], sort_keys=True, default=str)
    engine.replay_log[-1]["path_specific"] = str(tmp_path / "second")
    second = _replay_checkpoint_shape(engine)
    second_bytes = json.dumps(engine.replay_log[0], sort_keys=True, default=str)

    assert first_bytes != second_bytes
    assert first == second


def _stable_behavior_signature(engine: TownWorldEngine, npc_ids: list[str]) -> dict[str, object]:
    return {
        "clock": {
            "day": engine.state.clock.day,
            "minute": engine.state.clock.minute,
            "stride": engine.state.clock.stride_minutes,
        },
        "locations": {npc_id: engine.state.location_id_for(npc_id) for npc_id in npc_ids},
        "schedules": {
            npc_id: [
                {
                    "start": segment.start_minute,
                    "duration": segment.duration_minutes,
                    "location": segment.location_id,
                    "intent": segment.intent,
                    "day": segment.day,
                }
                for segment in engine.state.schedule_for(npc_id)
            ]
            for npc_id in npc_ids
        },
        "day_plans": {
            npc_id: sorted(engine.state.residents[npc_id].day_plans)
            for npc_id in npc_ids
        },
        "active_actions": {
            npc_id: (
                engine.state.current_action_for(npc_id).action_type,
                engine.state.current_action_for(npc_id).location_id,
                engine.state.current_action_for(npc_id).status,
            )
            if engine.state.current_action_for(npc_id) is not None
            else None
            for npc_id in npc_ids
        },
        "conversation_cooldowns": dict(sorted(engine.state.conversation_cooldowns.items())),
        "loop_guards": list(engine.loop_guard_events),
        "memory_evidence": {
            npc_id: bool(
                engine.memory_for(npc_id).grep(
                    "新菜单",
                    category="semantic",
                    metadata_filters={"source": "pause_resume_test"},
                )
            )
            for npc_id in npc_ids
        },
        "replay_shape": _replay_checkpoint_shape(engine),
    }


def _replay_checkpoint_shape(engine: TownWorldEngine) -> list[dict[str, object]]:
    return [
        {
            "tick": row.get("tick"),
            "minute": row.get("minute"),
            "snapshot_keys": sorted(row.get("snapshot", {}).keys())
            if isinstance(row.get("snapshot"), dict)
            else [],
            "resident_ids": sorted(row.get("snapshot", {}).get("residents", {}))
            if isinstance(row.get("snapshot"), dict)
            else [],
        }
        for row in engine.replay_log
    ]

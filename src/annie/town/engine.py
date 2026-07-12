"""Concrete semantic town world engine."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Literal, Protocol, cast

import chromadb
from chromadb.api import ClientAPI

from annie.npc.core.context import AgentContext
from annie.npc.memory.interface import MemoryInterface
from annie.npc.core.response import ActionRequest, ActionResult, AgentResponse
from annie.npc.core.routes import AgentRoute
from annie.npc.tools.base_tool import ToolDef
from annie.world_engine.base import WorldEngine
from annie.world_engine.history import HistoryStore
from annie.world_engine.memory import DefaultMemoryInterface
from annie.world_engine.tools import PlanTodoTool, render_todo_text
from annie.town.domain import (
    ConversationSession,
    ConversationTurn,
    CurrentAction,
    Location,
    MoveResult,
    ReflectionEvidence,
    ResidentDayPlan,
    ScheduleCompletion,
    ScheduleRevision,
    ScheduleSatisfaction,
    ScheduleSegment,
    SemanticAffordance,
    TownEvent,
    TownObject,
    TownPerceptionPolicy,
    TownState,
)
from annie.town.prompt_policy import (
    render_conversation_policy_hint,
    render_object_selection_hint,
    render_repeat_guard_hint,
    render_schedule_decision_hint,
    render_wait_decision_hint,
    schedule_evidence,
    schedule_progress_summary,
    default_subtasks_for,
)
from annie.town.eventing import NPCRegistry, TownEventBus
from annie.town.persistence import (
    TOWN_RUNTIME_SNAPSHOT_VERSION,
    TownPersistenceError,
    build_run_manifest,
    engine_runtime_from_dict,
    engine_runtime_to_dict,
    event_bus_from_dict,
    event_bus_to_dict,
    load_run_manifest,
    load_snapshot,
    npc_registry_from_dict,
    resolve_manifest_paths,
    town_state_from_snapshot_sections,
    town_state_to_snapshot_sections,
    validate_snapshot,
    write_json_atomic,
)
from annie.town.tools import (
    CompleteCurrentScheduleTool,
    FindAffordanceTargetsTool,
    InspectAffordancesTool,
    InteractWithTool,
    MoveToTool,
    ObserveTool,
    TalkToTool,
    UseAffordanceTool,
    WaitTool,
)

_DEFAULT_TOWN_VECTOR_STORE = Path("./data/town/vector_store")
_DEFAULT_TOWN_HISTORY_DIR = Path("./data/town/history")
MAX_TOWN_HISTORY_TURNS = 20
DEFAULT_MOVE_MINUTES = 5
DEFAULT_FAILED_ACTION_MINUTES = 1
DEFAULT_OBSERVE_MINUTES = 1
DEFAULT_INTERACT_MINUTES = 5
MAX_SPEAK_MINUTES = 5
SPEAK_CHARS_PER_MINUTE = 50
DEFAULT_SPEAK_COOLDOWN_MINUTES = 10
DEFAULT_CHAT_ITER = 4
DEFAULT_CONVERSATION_COOLDOWN_MINUTES = 60
MAX_CONVERSATION_MINUTES = 10
CONVERSATION_CHARS_PER_MINUTE = 240
SIGNIFICANT_EVENT_TYPES = {"urgent", "emergency", "alarm"}
SCHEDULE_REVISION_MINUTES = 15
DEFAULT_REFLECTION_THRESHOLD = 6
DEFAULT_DAY_START_MINUTE = 8 * 60
DEFAULT_DAY_END_MINUTE = 18 * 60
LOOP_GUARD_WINDOW = 6
TOWN_ACTION_TOOL_NAMES = [
    "memory_store",
    "plan_todo",
    "move_to",
    "observe",
    "talk_to",
    "speak_to",
    "start_conversation",
    "interact_with",
    "inspect_affordances",
    "find_affordance_targets",
    "use_affordance",
    "wait",
    "complete_current_schedule",
    "finish_schedule_segment",
]

ACTION_EFFECT_MODELS: dict[str, str] = {
    "move_to": "immediate_effect",
    "move": "immediate_effect",
    "wait": "no_world_effect",
    "talk_to": "immediate_effect",
    "speak_to": "immediate_effect",
    "start_conversation": "immediate_effect",
    "conversation": "immediate_effect",
    "interact_with": "immediate_effect",
    "interact": "immediate_effect",
    "use_affordance": "immediate_effect",
    "complete_current_schedule": "immediate_effect",
    "finish_schedule_segment": "immediate_effect",
    "observe": "no_world_effect",
    "inspect_affordances": "no_world_effect",
    "find_affordance_targets": "no_world_effect",
}
ACTION_OCCUPANCY_MODELS: dict[str, str] = {
    "complete_current_schedule": "instant_free",
    "finish_schedule_segment": "instant_free",
    "observe": "instant_free",
    "inspect_affordances": "instant_free",
    "find_affordance_targets": "instant_free",
}
SCHEDULE_COMPLETION_POLICIES = {
    "first_matching_action",
    "occupy_until_segment_end",
    "min_matching_actions",
    "explicit",
}


class TownAgent(Protocol):
    def run(self, context: AgentContext) -> AgentResponse:
        ...


class TownWorldEngine(WorldEngine):
    """Minimal concrete engine backed by world-owned TownState."""

    def __init__(
        self,
        state: TownState,
        memories: dict[str, MemoryInterface] | None = None,
        *,
        chroma_client: ClientAPI | None = None,
        memory_path: str | Path | None = None,
        history_dir: str | Path | None = None,
        perception_policy: TownPerceptionPolicy | None = None,
    ) -> None:
        self.state = state
        self._memory_path = Path(memory_path) if memory_path else _DEFAULT_TOWN_VECTOR_STORE
        self._client = chroma_client or chromadb.PersistentClient(
            path=str(self._memory_path)
        )
        self._memories = memories or {}
        self._histories: dict[str, HistoryStore] = {}
        self._history_dir = Path(history_dir) if history_dir else _DEFAULT_TOWN_HISTORY_DIR
        self.action_log: list[dict[str, object]] = []
        self.replay_log: list[dict[str, object]] = []
        self.reflection_log: list[dict[str, object]] = []
        self.npc_registry = NPCRegistry.from_state(state)
        self.event_bus = TownEventBus()
        self._inboxes = self.event_bus.inboxes
        self._seen_event_ids = self.event_bus.seen_event_ids
        self._visible_event_count_limit: int | None = None
        self.perception_policy = perception_policy or TownPerceptionPolicy()
        self._active_step_agent: TownAgent | None = None
        self.chat_iter = DEFAULT_CHAT_ITER
        self.conversation_cooldown_minutes = DEFAULT_CONVERSATION_COOLDOWN_MINUTES
        self.speak_cooldown_minutes = DEFAULT_SPEAK_COOLDOWN_MINUTES
        self.reflection_threshold = DEFAULT_REFLECTION_THRESHOLD
        self._speak_cooldowns: dict[tuple[str, str], int] = {}
        self._schedule_revisions: dict[tuple[str, str], ScheduleRevision] = {}
        self._latest_schedule_revision_by_npc: dict[str, ScheduleRevision] = {}
        self.planning_log: list[dict[str, object]] = []
        self.loop_guard_events: list[dict[str, object]] = []
        self.free_action_log: list[dict[str, object]] = []
        self._loop_guard_keys: set[tuple[object, ...]] = set()

    def export_runtime_snapshot(
        self,
        *,
        run_id: str | None = None,
        replay_cursor: dict[str, object] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Build a versioned JSON-compatible snapshot of engine-owned state."""
        snapshot: dict[str, object] = {
            "schema_version": TOWN_RUNTIME_SNAPSHOT_VERSION,
            "run": {
                "run_id": run_id or "",
                "metadata": metadata or {},
                "history_backend": {"path": str(self._history_dir)},
                "memory_backend": {"path": str(self._memory_path)},
            },
            "event_delivery": event_bus_to_dict(self.event_bus),
            "loop_guards": {
                "events": list(self.loop_guard_events),
                "keys": [list(key) for key in sorted(self._loop_guard_keys, key=str)],
            },
            "replay_cursor": {
                "next_tick": len(self.replay_log) + 1,
                "replay_log_length": len(self.replay_log),
                **(replay_cursor or {}),
            },
            "engine": engine_runtime_to_dict(
                perception_policy=self.perception_policy,
                npc_registry=self.npc_registry,
                speak_cooldowns=self._speak_cooldowns,
                schedule_revisions=self._schedule_revisions,
                latest_schedule_revision_by_npc=self._latest_schedule_revision_by_npc,
                planning_log=self.planning_log,
                action_log=self.action_log,
                replay_log=self.replay_log,
                reflection_log=self.reflection_log,
                chat_iter=self.chat_iter,
                conversation_cooldown_minutes=self.conversation_cooldown_minutes,
                speak_cooldown_minutes=self.speak_cooldown_minutes,
                reflection_threshold=self.reflection_threshold,
            ),
        }
        snapshot.update(town_state_to_snapshot_sections(self.state))
        return snapshot

    def save_runtime_snapshot(
        self,
        path: str | Path,
        *,
        run_id: str | None = None,
        replay_cursor: dict[str, object] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> Path:
        """Atomically write the authoritative runtime snapshot."""
        snapshot = self.export_runtime_snapshot(
            run_id=run_id,
            replay_cursor=replay_cursor,
            metadata=metadata,
        )
        return write_json_atomic(path, snapshot)

    @classmethod
    def from_runtime_snapshot(
        cls,
        snapshot: str | Path | dict[str, object],
        *,
        chroma_client: ClientAPI | None = None,
        memory_path: str | Path | None = None,
        history_dir: str | Path | None = None,
        memories: dict[str, MemoryInterface] | None = None,
        validate_backend_paths: bool = False,
    ) -> "TownWorldEngine":
        """Rebuild a runnable town engine from a versioned runtime snapshot."""
        payload = load_snapshot(snapshot) if isinstance(snapshot, str | Path) else validate_snapshot(snapshot)
        run_payload = payload.get("run", {})
        if not isinstance(run_payload, dict):
            raise TownPersistenceError("runtime snapshot run section must be an object")
        if memory_path is None:
            backend = run_payload.get("memory_backend", {})
            if isinstance(backend, dict) and isinstance(backend.get("path"), str):
                memory_path = backend["path"]
        if history_dir is None:
            backend = run_payload.get("history_backend", {})
            if isinstance(backend, dict) and isinstance(backend.get("path"), str):
                history_dir = backend["path"]
        if validate_backend_paths:
            _validate_backend_path(memory_path, "memory_backend")
            _validate_backend_path(history_dir, "history_backend")

        state = town_state_from_snapshot_sections(payload)
        runtime = engine_runtime_from_dict(_snapshot_mapping(payload, "engine"))
        engine = cls(
            state,
            memories=memories,
            chroma_client=chroma_client,
            memory_path=memory_path,
            history_dir=history_dir,
            perception_policy=runtime["perception_policy"],  # type: ignore[arg-type]
        )
        engine.event_bus = event_bus_from_dict(_snapshot_mapping(payload, "event_delivery"))
        engine._inboxes = engine.event_bus.inboxes
        engine._seen_event_ids = engine.event_bus.seen_event_ids
        registry_payload = _snapshot_mapping(_snapshot_mapping(payload, "engine"), "npc_registry")
        engine.npc_registry = npc_registry_from_dict(registry_payload, state)
        engine._speak_cooldowns = runtime["speak_cooldowns"]  # type: ignore[assignment]
        engine._schedule_revisions = runtime["schedule_revisions"]  # type: ignore[assignment]
        engine._latest_schedule_revision_by_npc = runtime["latest_schedule_revision_by_npc"]  # type: ignore[assignment]
        engine.planning_log = runtime["planning_log"]  # type: ignore[assignment]
        engine.action_log = runtime["action_log"]  # type: ignore[assignment]
        engine.reflection_log = runtime["reflection_log"]  # type: ignore[assignment]
        engine.replay_log = runtime["replay_log"]  # type: ignore[assignment]
        engine.chat_iter = int(runtime["chat_iter"])
        engine.conversation_cooldown_minutes = int(runtime["conversation_cooldown_minutes"])
        engine.speak_cooldown_minutes = int(runtime["speak_cooldown_minutes"])
        engine.reflection_threshold = int(runtime["reflection_threshold"])
        loop_guards = _snapshot_mapping(payload, "loop_guards")
        engine.loop_guard_events = list(loop_guards.get("events", []))  # type: ignore[arg-type]
        engine._loop_guard_keys = {
            _freeze_snapshot_key(item)
            for item in loop_guards.get("keys", [])
            if isinstance(item, list)
        }
        return engine

    def save_run(
        self,
        run_dir: str | Path,
        *,
        run_id: str | None = None,
        replay_paths: dict[str, str | Path] | None = None,
        write_step_snapshot: bool = False,
        model_summary: dict[str, object] | None = None,
        validation: dict[str, object] | None = None,
        diagnostics_path: str | Path | None = None,
        validation_path: str | Path | None = None,
        presentation_paths: dict[str, str | Path] | None = None,
    ) -> dict[str, Path]:
        """Save a manifest-backed run directory using ``state/latest.json``."""
        root = Path(run_dir)
        resolved_run_id = run_id or root.name
        latest_path = root / "state" / "latest.json"
        self.save_runtime_snapshot(latest_path, run_id=resolved_run_id)

        step_paths: list[Path] = []
        if write_step_snapshot:
            step_path = root / "state" / "steps" / f"step-{len(self.replay_log):06d}.json"
            self.save_runtime_snapshot(step_path, run_id=resolved_run_id)
            step_paths.append(step_path)

        manifest = build_run_manifest(
            run_id=resolved_run_id,
            run_dir=root,
            latest_snapshot_path=latest_path,
            step_snapshot_paths=step_paths,
            replay_paths=replay_paths or {},
            history_path=self._history_dir,
            vector_store_path=self._memory_path,
            model_summary=model_summary,
            validation=validation,
            diagnostics_path=diagnostics_path,
            validation_path=validation_path,
            presentation_paths=presentation_paths,
        )
        manifest_path = write_json_atomic(root / "manifest.json", manifest)
        return {"manifest": manifest_path, "latest_snapshot": latest_path, **{
            f"step_snapshot_{index}": path for index, path in enumerate(step_paths, start=1)
        }}

    @classmethod
    def resume_run(
        cls,
        run_dir_or_manifest: str | Path,
        *,
        chroma_client: ClientAPI | None = None,
        memories: dict[str, MemoryInterface] | None = None,
    ) -> "TownWorldEngine":
        """Resume a TownWorld run from a run directory or manifest path."""
        input_path = Path(run_dir_or_manifest)
        manifest_path = input_path if input_path.is_file() else input_path / "manifest.json"
        run_dir = manifest_path.parent
        manifest = load_run_manifest(manifest_path)
        resolved = resolve_manifest_paths(run_dir, manifest)
        latest_snapshot = resolved["latest_snapshot_path"]
        history_path = resolved["history_path"]
        vector_store_path = resolved["vector_store_path"]
        if not isinstance(latest_snapshot, Path):
            raise TownPersistenceError("town run manifest does not resolve latest snapshot")
        if not latest_snapshot.exists():
            raise TownPersistenceError(f"missing latest snapshot: {latest_snapshot}")
        _validate_backend_path(history_path, "history_path")
        _validate_backend_path(vector_store_path, "vector_store_path")
        return cls.from_runtime_snapshot(
            latest_snapshot,
            chroma_client=chroma_client,
            memory_path=vector_store_path,
            history_dir=history_path,
            memories=memories,
            validate_backend_paths=True,
        )

    def plan_day_for_resident(
        self,
        npc_id: str,
        schedule: list[ScheduleSegment],
        *,
        day: int | None = None,
        planning_evidence: list[dict[str, object]] | None = None,
        validation: dict[str, object] | None = None,
        repair_invalid: bool = False,
    ) -> list[ScheduleSegment]:
        """Accept a deterministic resident-generated daily schedule."""
        if npc_id not in self.state.residents:
            raise ValueError("unknown_resident")
        schedule_day = self.state.clock.day if day is None else day

        if repair_invalid:
            repair_start = min((segment.start_minute for segment in schedule), default=0)
            repair_end = max((segment.end_minute for segment in schedule), default=24 * 60)
            if repair_start == 0:
                repair_end = max(repair_end, 24 * 60)
            accepted_schedule, validation_result = self._validate_and_repair_schedule(
                npc_id,
                schedule,
                day=schedule_day,
                start_minute=repair_start,
                end_minute=repair_end,
            )
        else:
            self._assert_schedule_valid(npc_id, schedule)
            accepted_schedule = sorted(schedule, key=lambda segment: segment.start_minute)
            for segment in accepted_schedule:
                segment.day = schedule_day
            validation_result = {
                "ok": True,
                "warnings": [],
                "segment_count": len(accepted_schedule),
            }
        if validation is not None:
            validation_result = {**validation_result, **validation}

        self.state.set_schedule(npc_id, accepted_schedule, day=schedule_day)
        resident = self.state.residents[npc_id]
        day_plan = resident.day_plans.setdefault(schedule_day, ResidentDayPlan(day=schedule_day))
        day_plan.planning_evidence = list(planning_evidence or day_plan.planning_evidence)
        day_plan.validation = validation_result
        day_plan.schedule_summary = _schedule_summary(accepted_schedule)
        self._record_planning_checkpoint(
            npc_id,
            day=schedule_day,
            stage="accepted_schedule",
            payload={
                "schedule": [_full_schedule_dict(segment) for segment in accepted_schedule],
                "evidence": list(planning_evidence or []),
                "validation": validation_result,
            },
        )
        return accepted_schedule

    def start_day_for_resident(
        self,
        npc_id: str,
        *,
        day: int | None = None,
        start_minute: int = DEFAULT_DAY_START_MINUTE,
        end_minute: int = DEFAULT_DAY_END_MINUTE,
    ) -> list[ScheduleSegment]:
        """Run the minimal deterministic day-start lifecycle for one resident."""
        if npc_id not in self.state.residents:
            raise ValueError("unknown_resident")
        schedule_day = self.state.clock.day if day is None else day
        self.state.clock.day = schedule_day
        self.state.clock.minute = start_minute
        self.state.clear_current_action(npc_id)
        resident = self.state.residents[npc_id]
        if start_minute == 0:
            self._initialize_resident_day_lifecycle(npc_id, day=schedule_day)
        day_plan = resident.day_plans.setdefault(schedule_day, ResidentDayPlan(day=schedule_day))
        day_plan.started_minute = start_minute
        existing_schedule = [
            segment
            for segment in resident.schedule
            if (schedule_day if segment.day is None else segment.day) == schedule_day
        ]
        if existing_schedule and self._schedule_is_valid(npc_id, existing_schedule):
            resident.schedule_day = schedule_day
            day_plan.validation = {
                **day_plan.validation,
                "ok": True,
                "reused_existing_schedule": True,
                "segment_count": len(existing_schedule),
            }
            day_plan.schedule_summary = _schedule_summary(existing_schedule)
            self._record_planning_checkpoint(
                npc_id,
                day=schedule_day,
                stage="existing_schedule_reused",
                payload={
                    "schedule": [
                        _full_schedule_dict(segment) for segment in existing_schedule
                    ],
                    "validation": day_plan.validation,
                },
            )
            return existing_schedule

        evidence = self.retrieve_planning_evidence(npc_id)
        day_plan.planning_evidence = evidence
        currently = self.update_currently_for_resident(npc_id, evidence)
        wake_up = self.plan_wake_up_for_resident(npc_id, start_minute=start_minute)
        intentions = self.plan_daily_intentions_for_resident(npc_id, evidence)
        candidate = self.plan_schedule_segments_for_resident(
            npc_id,
            intentions,
            start_minute=max(start_minute, wake_up),
            end_minute=end_minute,
        )
        accepted, validation = self._validate_and_repair_schedule(
            npc_id,
            candidate,
            day=schedule_day,
            start_minute=start_minute,
            end_minute=end_minute,
        )
        day_plan.currently = currently
        day_plan.wake_up_minute = wake_up
        day_plan.daily_intentions = intentions
        return self.plan_day_for_resident(
            npc_id,
            accepted,
            day=schedule_day,
            planning_evidence=evidence,
            validation=validation,
            repair_invalid=True,
        )

    def start_day_for_residents(
        self,
        npc_ids: list[str] | None = None,
        *,
        day: int | None = None,
        start_minute: int = DEFAULT_DAY_START_MINUTE,
        end_minute: int = DEFAULT_DAY_END_MINUTE,
    ) -> dict[str, list[ScheduleSegment]]:
        active_npcs = list(npc_ids) if npc_ids is not None else self.state.resident_ids()
        return {
            npc_id: self.start_day_for_resident(
                npc_id,
                day=day,
                start_minute=start_minute,
                end_minute=end_minute,
            )
            for npc_id in active_npcs
        }

    def end_day_for_resident(
        self,
        npc_id: str,
        *,
        day: int | None = None,
    ) -> str:
        """Summarize the resident's day and persist distilled planning memory."""
        if npc_id not in self.state.residents:
            raise ValueError("unknown_resident")
        schedule_day = self.state.clock.day if day is None else day
        self._finalize_due_current_actions([npc_id], at_minute=self.state.clock.minute)
        resident = self.state.residents[npc_id]
        day_plan = resident.day_plans.setdefault(schedule_day, ResidentDayPlan(day=schedule_day))
        schedule = [
            segment
            for segment in resident.schedule
            if (schedule_day if segment.day is None else segment.day) == schedule_day
        ]
        completed = [
            item
            for item in self.state.completed_schedule_segments.get(npc_id, [])
            if (schedule_day if item.day is None else item.day) == schedule_day
        ]
        schedule_evidence = self._day_schedule_evidence(
            npc_id,
            schedule,
            completed,
            day=schedule_day,
        )
        lifecycle_anomalies = self._settle_resident_overnight(
            npc_id,
            schedule,
            schedule_evidence,
            day=schedule_day,
        )
        summary = (
            f"第 {schedule_day} 天：{npc_id} 计划 {len(schedule)} 段，"
            f"完成 {len(completed)} 段，未完成 "
            f"{len([item for item in schedule_evidence if item['status'] != 'completed'])} 段。"
            f"生命周期异常 {len(lifecycle_anomalies)} 项。"
            f"{_schedule_summary(schedule)}"
        )
        day_plan.day_summary = summary
        day_plan.schedule_evidence = schedule_evidence
        day_plan.ended_minute = self.state.clock.minute
        day_plan.lifecycle_anomalies = lifecycle_anomalies
        self.memory_for(npc_id).remember(
            summary,
            category="impression",
            metadata={
                "source": "town_day_summary",
                "day": schedule_day,
                "npc_id": npc_id,
                "completed_count": len(completed),
                "schedule_count": len(schedule),
                "schedule_evidence": json.dumps(
                    schedule_evidence,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "lifecycle_anomalies": json.dumps(
                    lifecycle_anomalies,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
        )
        self._record_planning_checkpoint(
            npc_id,
            day=schedule_day,
            stage="day_end_summary",
            payload={
                "summary": summary,
                "schedule_evidence": schedule_evidence,
                "lifecycle_anomalies": lifecycle_anomalies,
                "resident_lifecycle": self._resident_lifecycle_payload(npc_id),
            },
        )
        return summary

    def end_day_for_residents(
        self,
        npc_ids: list[str] | None = None,
        *,
        day: int | None = None,
    ) -> dict[str, str]:
        active_npcs = list(npc_ids) if npc_ids is not None else self.state.resident_ids()
        return {
            npc_id: self.end_day_for_resident(npc_id, day=day)
            for npc_id in active_npcs
        }

    def _initialize_resident_day_lifecycle(self, npc_id: str, *, day: int) -> None:
        resident = self.state.residents[npc_id]
        baseline = resident.sleep_location_id or resident.home_location_id
        if baseline and baseline in self.state.locations:
            self.state.set_location(npc_id, baseline)
            resident.lifecycle_status = "sleeping"
        else:
            self._record_lifecycle_anomaly(
                npc_id,
                day=day,
                reason="missing_home_or_sleep_location",
                location_id=self.state.location_id_for(npc_id),
            )
        self._record_planning_checkpoint(
            npc_id,
            day=day,
            stage="day_start_lifecycle",
            payload=self._resident_lifecycle_payload(npc_id),
        )

    def _settle_resident_overnight(
        self,
        npc_id: str,
        schedule: list[ScheduleSegment],
        schedule_evidence: list[dict[str, object]],
        *,
        day: int,
    ) -> list[dict[str, object]]:
        resident = self.state.residents[npc_id]
        home = resident.sleep_location_id or resident.home_location_id
        final_location = self.state.location_id_for(npc_id)
        anomalies: list[dict[str, object]] = []
        sleep_segments = [
            segment
            for segment in schedule
            if self._is_sleep_or_rest_segment(npc_id, segment)
        ]
        completed_starts = {
            int(item["segment_start_minute"])
            for item in schedule_evidence
            if item.get("status") == "completed"
        }
        valid_sleep = bool(
            sleep_segments
            and any(segment.start_minute in completed_starts or segment.end_minute >= 24 * 60 for segment in sleep_segments)
        )
        if not home:
            anomalies.append(
                self._record_lifecycle_anomaly(
                    npc_id,
                    day=day,
                    reason="missing_home_or_sleep_location",
                    location_id=final_location,
                )
            )
        elif final_location != home and not valid_sleep:
            anomalies.append(
                self._record_lifecycle_anomaly(
                    npc_id,
                    day=day,
                    reason="ended_away_from_home_without_valid_sleep",
                    location_id=final_location,
                )
            )
        else:
            self.state.set_location(npc_id, home)
            resident.lifecycle_status = "sleeping"
        if not sleep_segments:
            anomalies.append(
                self._record_lifecycle_anomaly(
                    npc_id,
                    day=day,
                    reason="missing_sleep_or_rest_segment",
                    location_id=final_location,
                )
            )
        return [item for item in anomalies if item]

    def _record_lifecycle_anomaly(
        self,
        npc_id: str,
        *,
        day: int,
        reason: str,
        location_id: str | None,
    ) -> dict[str, object]:
        anomaly = {
            "npc_id": npc_id,
            "day": day,
            "minute": self.state.clock.minute,
            "location_id": location_id,
            "reason": reason,
        }
        self._record_planning_checkpoint(
            npc_id,
            day=day,
            stage="lifecycle_anomaly",
            payload=anomaly,
        )
        return anomaly

    def _resident_lifecycle_payload(self, npc_id: str) -> dict[str, object]:
        resident = self.state.residents[npc_id]
        return {
            "npc_id": npc_id,
            "location_id": resident.location_id,
            "home_location_id": resident.home_location_id,
            "sleep_location_id": resident.sleep_location_id,
            "default_wake_window": list(resident.default_wake_window or []),
            "default_sleep_window": list(resident.default_sleep_window or []),
            "lifecycle_status": resident.lifecycle_status,
        }

    def _day_schedule_evidence(
        self,
        npc_id: str,
        schedule: list[ScheduleSegment],
        completed: list[Any],
        *,
        day: int,
    ) -> list[dict[str, object]]:
        completed_by_key = {
            (item.start_minute, item.location_id): item for item in completed
        }
        interrupted_actions = [
            item
            for item in self.action_log
            if item.get("npc_id") == npc_id
            and item.get("lifecycle_state") == "interrupted"
        ]
        revision_logs = [
            item
            for item in self.planning_log
            if item.get("npc_id") == npc_id
            and item.get("day") == day
            and item.get("stage") == "schedule_revision"
        ]
        evidence: list[dict[str, object]] = []
        for segment in schedule:
            key = (segment.start_minute, segment.location_id)
            completion = completed_by_key.get(key)
            flags: list[str] = []
            if _schedule_is_fallback(segment):
                flags.append("fallback")
            if any(_revision_mentions_segment(item, segment) for item in revision_logs):
                flags.append("revised")
            if any(_interruption_overlaps_segment(item, segment) for item in interrupted_actions):
                flags.append("interrupted")

            if completion is not None:
                status = "completed"
                note = completion.note
                completion_type = getattr(completion, "completion_type", "explicit_request")
                if completion_type in {"inferred_action_match", "automatic_action_match"}:
                    flags.append("automatic")
            elif segment.end_minute <= self.state.clock.minute:
                status = "missed"
                note = ""
                flags.append("overdue")
                if self.state.is_schedule_segment_satisfied(npc_id, segment):
                    status = "satisfied_in_progress"
                    flags = [item for item in flags if item != "overdue"]
                    note = "satisfied by finalized action evidence"
            else:
                status = "active" if segment.contains(self.state.clock.minute) else "future_not_run"
                note = ""
                if self.state.is_schedule_segment_satisfied(npc_id, segment):
                    status = "satisfied_in_progress"
                    note = "satisfied by finalized action evidence"

            evidence.append(
                {
                    "npc_id": npc_id,
                    "day": day,
                    "segment_start_minute": segment.start_minute,
                    "segment_end_minute": segment.end_minute,
                    "location_id": segment.location_id,
                    "intent": segment.intent,
                    "status": status,
                    "flags": sorted(set(flags)),
                    "note": note,
                    "completion_type": getattr(completion, "completion_type", "") if completion is not None else "",
                    "matched_action_id": getattr(completion, "matched_action_id", None) if completion is not None else None,
                    "matched_action_type": getattr(completion, "matched_action_type", None) if completion is not None else None,
                    "matching_reason": getattr(completion, "matching_reason", "") if completion is not None else "",
                    "completion_policy": segment.completion_policy,
                    "satisfied": self.state.is_schedule_segment_satisfied(npc_id, segment),
                }
            )
        return evidence

    def retrieve_planning_evidence(self, npc_id: str) -> list[dict[str, object]]:
        memory = self.memory_for(npc_id)
        records = []
        records.extend(memory.grep("", category="impression", k=8))
        records.extend(memory.grep("", category="reflection", k=6))
        records.extend(memory.grep("", category="todo", k=6))
        records.extend(
            memory.recall(
                "小镇日程 计划 反思 对话 关系 未完成事项 跟进",
                categories=["impression", "reflection", "todo"],
                k=6,
            )
        )
        seen: set[tuple[str, str]] = set()
        evidence: list[dict[str, object]] = []
        for record in records:
            key = (record.category, record.content)
            if key in seen:
                continue
            seen.add(key)
            evidence.append(
                {
                    "category": record.category,
                    "content": record.content,
                    "metadata": dict(record.metadata),
                }
            )
            if len(evidence) >= 8:
                break
        resident = self.state.resident_for(npc_id)
        if resident is not None:
            evidence.append(
                {
                    "category": "lifecycle",
                    "content": (
                        f"home={resident.home_location_id or 'unknown'}; "
                        f"sleep={resident.sleep_location_id or 'unknown'}; "
                        f"status={resident.lifecycle_status}; "
                        f"location={resident.location_id}"
                    ),
                    "metadata": {
                        "source": "town_lifecycle_state",
                        **self._resident_lifecycle_payload(npc_id),
                    },
                }
            )
            for day, day_plan in sorted(resident.day_plans.items()):
                if day_plan.lifecycle_anomalies:
                    evidence.append(
                        {
                            "category": "lifecycle",
                            "content": f"第 {day} 天生命周期异常：{day_plan.lifecycle_anomalies}",
                            "metadata": {
                                "source": "town_lifecycle_anomaly",
                                "day": day,
                                "anomalies": day_plan.lifecycle_anomalies,
                            },
                        }
                    )
                unfinished = [
                    item
                    for item in day_plan.schedule_evidence
                    if item.get("status") != "completed"
                ]
                if not unfinished:
                    continue
                evidence.append(
                    {
                        "category": "schedule",
                        "content": f"第 {day} 天有未完成日程证据：{unfinished}",
                        "metadata": {
                            "source": "town_unfinished_schedule",
                            "day": day,
                            "evidence": unfinished,
                        },
                    }
                )
                if len(evidence) >= 8:
                    break
        return evidence

    def relationship_planning_evidence(self, npc_id: str) -> list[dict[str, object]]:
        """Return pairwise conversation evidence that may affect future plans."""
        rows: list[dict[str, object]] = []
        for record in self.memory_for(npc_id).grep(
            "",
            category="impression",
            metadata_filters={"source": "town_conversation"},
            k=6,
        ):
            rows.append(
                {
                    "partner_npc_id": record.metadata.get("partner_npc_id"),
                    "conversation_session_id": record.metadata.get("conversation_session_id"),
                    "topic_or_reason": record.metadata.get("topic_or_reason"),
                    "relationship_pair_key": record.metadata.get("relationship_pair_key"),
                    "relationship_summary": record.metadata.get("relationship_summary"),
                    "unresolved_topics": _split_metadata_list(
                        record.metadata.get("unresolved_topics")
                    ),
                    "follow_up_intentions": _split_metadata_list(
                        record.metadata.get("follow_up_intentions")
                    ),
                    "content": record.content,
                }
            )
        return rows

    def update_currently_for_resident(
        self,
        npc_id: str,
        evidence: list[dict[str, object]] | None = None,
    ) -> str:
        resident = self.state.residents[npc_id]
        location_id = self.state.location_id_for(npc_id) or "unknown"
        evidence_bits = [str(item.get("content", "")) for item in (evidence or [])[:2]]
        suffix = "；参考：" + " / ".join(evidence_bits) if evidence_bits else ""
        resident.scratch.currently = (
            f"{npc_id} 在第 {self.state.clock.day} 天从 {location_id} 开始一天。{suffix}"
        )
        self._record_planning_checkpoint(
            npc_id,
            day=self.state.clock.day,
            stage="currently",
            payload={"currently": resident.scratch.currently, "evidence": evidence or []},
        )
        return resident.scratch.currently

    def plan_wake_up_for_resident(self, npc_id: str, *, start_minute: int) -> int:
        resident = self.state.residents[npc_id]
        if resident.default_wake_window is not None:
            wake_up = max(start_minute, resident.default_wake_window[0])
        else:
            wake_up = start_minute
        if self.state.clock.minute < wake_up:
            resident.lifecycle_status = "sleeping"
        else:
            resident.lifecycle_status = "awake"
        self._record_planning_checkpoint(
            npc_id,
            day=self.state.clock.day,
            stage="wake_up",
            payload={
                "wake_up_minute": wake_up,
                "wake_up_time": _minute_label(wake_up),
                "lifecycle": self._resident_lifecycle_payload(npc_id),
            },
        )
        return wake_up

    def plan_daily_intentions_for_resident(
        self,
        npc_id: str,
        evidence: list[dict[str, object]] | None = None,
    ) -> list[str]:
        fixture = self.state.schedule_for(npc_id)
        intentions = [segment.intent for segment in fixture[:3]]
        if not intentions:
            intentions = ["查看小镇公告", "整理当天事项"]
        influence = _planning_influence_intentions(evidence or [])
        if influence:
            intentions = influence + intentions
        if evidence:
            intentions.append("回顾昨日事项并调整安排")
        self._record_planning_checkpoint(
            npc_id,
            day=self.state.clock.day,
            stage="daily_intentions",
            payload={"intentions": intentions, "influence": influence},
        )
        return intentions

    def plan_schedule_segments_for_resident(
        self,
        npc_id: str,
        intentions: list[str],
        *,
        start_minute: int,
        end_minute: int,
    ) -> list[ScheduleSegment]:
        fixture = self.state.schedule_for(npc_id)
        resident = self.state.residents[npc_id]
        known_locations = [
            segment.location_id
            for segment in fixture
            if segment.location_id in self.state.locations
        ]
        if not known_locations:
            known_locations = [self.state.location_id_for(npc_id) or next(iter(self.state.locations))]
        duration = max(15, min(60, (end_minute - start_minute) // max(1, len(intentions))))
        minute = start_minute
        segments: list[ScheduleSegment] = []
        for index, intent in enumerate(intentions):
            if minute >= end_minute:
                break
            location_id = known_locations[min(index, len(known_locations) - 1)]
            segments.append(
                ScheduleSegment(
                    npc_id=npc_id,
                    start_minute=minute,
                    duration_minutes=min(duration, end_minute - minute),
                    location_id=location_id,
                    intent=intent,
                    subtasks=[],
                    day=self.state.clock.day,
                )
            )
            minute += duration
        if start_minute == 0 and resident.home_location_id:
            wake = (
                resident.default_wake_window[0]
                if resident.default_wake_window is not None
                else min(end_minute, DEFAULT_DAY_START_MINUTE)
            )
            if not any(self._is_sleep_or_rest_segment(npc_id, segment) for segment in segments):
                segments.insert(
                    0,
                    ScheduleSegment(
                        npc_id=npc_id,
                        start_minute=0,
                        duration_minutes=max(1, min(wake, end_minute)),
                        location_id=resident.sleep_location_id or resident.home_location_id,
                        intent="睡觉直到起床",
                        subtasks=["lifecycle:sleep"],
                        day=self.state.clock.day,
                    ),
                )
            if end_minute >= 24 * 60:
                sleep_start = (
                    resident.default_sleep_window[0]
                    if resident.default_sleep_window is not None
                    else 22 * 60
                )
                if not any(segment.start_minute >= sleep_start for segment in segments):
                    segments.append(
                        ScheduleSegment(
                            npc_id=npc_id,
                            start_minute=max(start_minute, min(sleep_start, end_minute - 60)),
                            duration_minutes=max(1, end_minute - max(start_minute, min(sleep_start, end_minute - 60))),
                            location_id=resident.sleep_location_id or resident.home_location_id,
                            intent="回家休息并睡觉",
                            subtasks=["lifecycle:return_home", "lifecycle:sleep"],
                            day=self.state.clock.day,
                        )
                    )
        self._record_planning_checkpoint(
            npc_id,
            day=self.state.clock.day,
            stage="schedule_segments",
            payload={"schedule": [_full_schedule_dict(segment) for segment in segments]},
        )
        return segments

    def build_daily_planning_context(
        self,
        npc_id: str,
        *,
        start_minute: int,
        end_minute: int,
    ) -> AgentContext:
        """Build a tool-free resident planning context for NPCAgent."""
        if npc_id not in self.state.residents:
            raise ValueError("unknown_resident")

        memory = self.memory_for(npc_id)
        planning_evidence = self.retrieve_planning_evidence(npc_id)
        relationship_evidence = self.relationship_planning_evidence(npc_id)
        current_location_id = self.state.location_id_for(npc_id)
        current_location = self.state.locations.get(current_location_id or "")
        resident = self.state.residents[npc_id]
        fixture_schedule = self.state.schedule_for(npc_id)
        location_rows = []
        for location in self.state.locations.values():
            objects = [
                self.state.objects[obj_id]
                for obj_id in location.object_ids
                if obj_id in self.state.objects
            ]
            location_rows.append(
                {
                    "id": location.id,
                    "name": location.name,
                    "description": location.description,
                    "exits": list(location.exits),
                    "exit_travel_minutes": {
                        exit_id: location.exit_travel_minutes.get(exit_id, DEFAULT_MOVE_MINUTES)
                        for exit_id in location.exits
                    },
                    "objects": [
                        {
                            "id": obj.id,
                            "name": obj.name,
                            "description": obj.description,
                            "interactable": obj.interactable,
                        }
                        for obj in objects
                    ],
                    "affordances": [_affordance_dict(item) for item in location.affordances],
                    "object_affordances": {
                        obj.id: [_affordance_dict(item) for item in obj.affordances]
                        for obj in objects
                    },
                }
            )

        planning_payload = {
            "npc_id": npc_id,
            "current_location_id": current_location_id,
            "current_location_name": current_location.name if current_location else None,
            "home_location_id": resident.home_location_id,
            "sleep_location_id": resident.sleep_location_id,
            "lifecycle_status": resident.lifecycle_status,
            "default_wake_window": list(resident.default_wake_window or []),
            "default_sleep_window": list(resident.default_sleep_window or []),
            "planning_window": {
                "start_minute": start_minute,
                "end_minute": end_minute,
                "start_label": _minute_label(start_minute),
                "end_label": _minute_label(end_minute),
            },
            "existing_fixture_schedule": [
                _full_schedule_dict(segment) for segment in fixture_schedule
            ],
            "planning_evidence": planning_evidence,
            "relationship_evidence": relationship_evidence,
            "known_locations": location_rows,
            "output_schema": {
                "schedule": [
                    {
                        "npc_id": npc_id,
                        "start_minute": start_minute,
                        "duration_minutes": 30,
                        "location_id": "town_square",
                        "intent": "查看公告板",
                    }
                ],
                "wake_up_minute": start_minute,
            },
        }
        situation = "\n".join(
            [
                "你正在为 TownWorld resident 生成一天中的语义日程。",
                f"居民 id：{npc_id}",
                f"当前位置：{current_location_id or 'unknown'}",
                f"家/睡眠地点：{resident.home_location_id or 'unknown'} / {resident.sleep_location_id or 'unknown'}",
                f"生命周期状态：{resident.lifecycle_status}",
                f"规划窗口：{_minute_label(start_minute)}-{_minute_label(end_minute)}",
                "当前 fixture schedule：",
                json.dumps(
                    planning_payload["existing_fixture_schedule"],
                    ensure_ascii=False,
                    indent=2,
                ),
                "可用于改变今日计划的记忆、反思、todo：",
                _render_planning_evidence(planning_evidence),
                "可用于改变今日计划的关系/对话证据：",
                _render_relationship_planning_evidence(relationship_evidence),
                "可用地点、出口、物体：",
                json.dumps(location_rows, ensure_ascii=False, indent=2),
                "输出必须是一个 JSON object，格式固定为：",
                json.dumps(planning_payload["output_schema"], ensure_ascii=False),
                "硬性约束：所有日程必须位于规划窗口内，start_minute >= "
                f"{start_minute}，end_minute <= {end_minute}。"
                "如果规划完整 00:00-24:00，一定要包含起床前睡眠和夜间休息/睡眠；"
                "夜间睡眠地点必须是 home_location_id 或 sleep_location_id；"
                "如果睡前人在外面，需要安排可达的回家/返回睡眠地点过渡。"
                f"至少一个日程段必须从 {start_minute} 开始或覆盖 {_minute_label(start_minute)}。"
                "第一段日程必须从 current_location_id 和可达出口出发安排；"
                "如果第一段不在当前位置，必须预留足够 travel minutes。"
                "fixture 只作为 fallback/reference，不要忽略当前地点和移动约束。"
                "如果 fixture 已填满窗口，也要在窗口内提出替代日程，不要安排到窗口之后。",
                "只输出 JSON，不输出 markdown，不调用工具。",
            ]
        )
        return AgentContext(
            npc_id=npc_id,
            input_event="生成 resident daily schedule JSON。",
            tools=[],
            memory=memory,
            route=AgentRoute.STRUCTURED_JSON,
            world_rules=(
                "你只负责提出候选日程。TownWorldEngine 会校验地点、归属、"
                "时间重叠并持久化 accepted schedule。"
                "planning 阶段不得移动 NPC，不得写世界动作，不得调用小镇 action tools。"
                "每个日程项必须属于当前 npc_id，location_id 必须来自 known_locations。"
                "日程项必须包含 npc_id、start_minute、duration_minutes、location_id、intent。"
                "所有日程项必须落在规划窗口内，且不要输出规划窗口之后的安排。"
                "如果 planning_evidence 或 relationship_evidence 包含未解决话题、"
                "跟进意图或重要反思，应在时间允许时把它们转化为具体日程意图。"
            ),
            situation=situation,
            extra={
                "disabled_tools": [
                    "memory_store",
                    "plan_todo",
                    "move_to",
                    "observe",
                    "talk_to",
                    "speak_to",
                    "start_conversation",
                    "interact_with",
                    "wait",
                    "complete_current_schedule",
                    "finish_schedule_segment",
                ],
                "town": {
                    "planning": True,
                    **planning_payload,
                },
            },
        )

    def generate_day_plan_for_resident(
        self,
        npc_id: str,
        agent: TownAgent,
        *,
        start_minute: int,
        end_minute: int,
    ) -> list[ScheduleSegment]:
        """Ask a stateless NPCAgent-compatible backend for a resident daily plan."""
        fallback_schedule = list(self.state.schedule_for(npc_id))
        context = self.build_daily_planning_context(
            npc_id,
            start_minute=start_minute,
            end_minute=end_minute,
        )
        response = agent.run(context)
        schedule = _schedule_from_agent_response(response)
        for segment in schedule:
            if segment.npc_id != npc_id:
                raise ValueError("schedule_npc_mismatch")
            if segment.location_id not in self.state.locations:
                raise ValueError("unknown_schedule_location")
        schedule = _schedule_within_planning_window(
            npc_id=npc_id,
            schedule=schedule,
            fallback_schedule=fallback_schedule,
            start_minute=start_minute,
            end_minute=end_minute,
        )
        self._assert_schedule_valid(npc_id, schedule)
        accepted, validation = self._validate_and_repair_schedule(
            npc_id,
            schedule,
            day=self.state.clock.day,
            start_minute=start_minute,
            end_minute=end_minute,
        )
        planning_evidence = context.extra.get("town", {}).get("planning_evidence", [])
        return self.plan_day_for_resident(
            npc_id,
            accepted,
            planning_evidence=(
                planning_evidence if isinstance(planning_evidence, list) else []
            ),
            validation=validation,
        )

    def reflection_due_for(self, npc_id: str) -> bool:
        resident = self.state.resident_for(npc_id)
        return (
            resident is not None
            and resident.poignancy >= self.reflection_threshold
            and bool(resident.reflection_evidence)
        )

    def build_reflection_context(self, npc_id: str) -> AgentContext:
        resident = self.state.resident_for(npc_id)
        if resident is None:
            raise ValueError("unknown_resident")

        evidence_rows = [_reflection_evidence_dict(item) for item in resident.reflection_evidence]
        evidence_text = _render_reflection_evidence(resident.reflection_evidence)
        situation = "\n".join(
            [
                "你正在为 TownWorld resident 生成 distilled reflection。",
                f"居民 id：{npc_id}",
                f"当前时间：{self.state.clock.label()}",
                f"累计重要性：{resident.poignancy} / {self.reflection_threshold}",
                "证据摘要：",
                evidence_text,
                "请只基于这些小镇证据生成简洁反思，避免复述原始对话逐字内容。",
            ]
        )
        return AgentContext(
            npc_id=npc_id,
            input_event="基于小镇证据生成 distilled reflection。",
            tools=[],
            memory=self.memory_for(npc_id),
            route=AgentRoute.REFLECTION,
            world_rules=(
                "反思阶段不得调用小镇 action tools，不得移动 NPC，不得写世界动作。"
                "输出应是可存入长期记忆的概括性 reflection。"
                "必须过滤系统元信息、工具名、函数名、内部流程和 JSON 字段名。"
                "使用中文输出。"
            ),
            situation=situation,
            extra={
                "disabled_tools": list(TOWN_ACTION_TOOL_NAMES),
                "town": {
                    "reflection": {
                        "poignancy": resident.poignancy,
                        "threshold": self.reflection_threshold,
                        "evidence": evidence_rows,
                    }
                },
            },
        )

    def reflect_for_resident(self, npc_id: str, agent: TownAgent) -> bool:
        resident = self.state.resident_for(npc_id)
        if resident is None:
            raise ValueError("unknown_resident")
        if not self.reflection_due_for(npc_id):
            return False

        response = agent.run(self.build_reflection_context(npc_id))
        reflection = (
            response.reflection.strip()
            or response.dialogue.strip()
            or response.inner_thought.strip()
        )
        if not reflection:
            return False

        evidence = list(resident.reflection_evidence)
        self.memory_for(npc_id).remember(
            reflection,
            category="reflection",
            metadata={
                "source": "town_reflection",
                "clock_minute": self.state.clock.minute,
                "trigger_poignancy": resident.poignancy,
                "evidence_ids": [item.id for item in evidence],
                "evidence_types": sorted({item.evidence_type for item in evidence}),
                "evidence_count": len(evidence),
            },
        )
        self.reflection_log.append(
            {
                "tick": None,
                "npc_id": npc_id,
                "minute": self.state.clock.minute,
                "time": self.state.clock.label(),
                "content": reflection,
                "trigger_poignancy": resident.poignancy,
                "evidence_ids": [item.id for item in evidence],
                "evidence_types": sorted({item.evidence_type for item in evidence}),
                "evidence_count": len(evidence),
            }
        )
        resident.reflection_evidence.clear()
        resident.poignancy = 0
        return True

    def build_replay_snapshot(
        self,
        npc_ids: list[str] | None = None,
        *,
        minute: int | None = None,
        reflection_events: list[dict[str, object]] | None = None,
        finalized_actions: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        """Build a stable structured checkpoint snapshot for replay inspection."""
        snapshot_minute = self.state.clock.minute if minute is None else minute
        active_npcs = list(npc_ids) if npc_ids is not None else self.state.resident_ids()
        return {
            "day": self.state.clock.day,
            "minute": snapshot_minute,
            "time": _minute_label(snapshot_minute),
            "planning_checkpoints": list(self.planning_log),
            "loop_guard_events": list(self.loop_guard_events),
            "finalized_actions": list(finalized_actions or []),
            "residents": {
                npc_id: self._resident_snapshot(npc_id, minute=snapshot_minute)
                for npc_id in active_npcs
                if self.state.resident_for(npc_id) is not None
            },
            "conversation_sessions": [
                self._conversation_session_snapshot(session)
                for session in sorted(
                    self.state.conversation_sessions.values(),
                    key=lambda item: item.id,
                )
            ],
            "reflection_events": list(reflection_events or []),
        }

    def build_context(self, npc_id: str, event: str) -> AgentContext:
        location = self.state.location_for(npc_id)
        if location is None:
            situation = "当前小镇状态：这个 NPC 尚未被放置到小镇中。"
            extra = {
                "disabled_tools": ["memory_store"],
                "town": {"known": False},
            }
        else:
            perception: dict[str, Any] = self.build_perception(npc_id)
            schedule_revision = self._revise_schedule_from_perception(npc_id, perception)
            objects = [
                self.state.objects[obj_id]
                for obj_id in perception["object_ids"]
                if obj_id in self.state.objects
            ]
            occupants = list(perception["visible_npc_ids"])
            schedule = self.state.current_schedule_segment(npc_id)
            if (
                schedule is not None
                and not schedule.subtasks
                and schedule.completion_policy == "explicit"
            ):
                self.decompose_current_schedule_segment(npc_id)
                schedule = self.state.current_schedule_segment(npc_id)
            selected_event_ids = list(perception["visible_event_ids"])
            events_by_id = {event.id: event for event in self._local_event_candidates(npc_id)}
            local_events = [
                events_by_id[event_id]
                for event_id in selected_event_ids
                if event_id in events_by_id
            ]
            pending_events = list(self._inboxes.get(npc_id, []))
            visible_actions = {
                other: self._current_action_dict(other)
                for other in occupants
                if self.state.current_action_for(other) is not None
            }
            active_session = self.state.active_conversation_for(npc_id)
            recent_chats = self._recent_conversation_summaries(npc_id)
            relationship_cues = self.relationship_cues_for(npc_id, occupants)
            own_action = self.state.current_action_for(npc_id)
            schedule_remaining_minutes = (
                max(0, schedule.end_minute - self.state.clock.minute)
                if schedule is not None
                else None
            )
            schedule_progress = self._schedule_progress_summary(npc_id, schedule)
            schedule_completion_hint = self._schedule_completion_hint(
                npc_id,
                schedule,
                schedule_progress,
            )
            schedule_decision_hint = render_schedule_decision_hint(
                schedule=schedule,
                clock_minute=self.state.clock.minute,
                stride_minutes=self.state.clock.stride_minutes,
                progress_summary=schedule_progress,
                evidence=schedule_evidence(
                    npc_id=npc_id,
                    schedule=schedule,
                    action_log=self.action_log,
                ),
                is_complete=(
                    self.state.is_schedule_segment_complete(npc_id, schedule)
                    if schedule is not None
                    else False
                ),
            )
            object_selection_hint = render_object_selection_hint(
                schedule=schedule,
                location=location,
                objects=objects,
            )
            wait_decision_hint = render_wait_decision_hint(
                visible_actions=visible_actions,
                own_action=own_action,
            )
            conversation_policy_hint = render_conversation_policy_hint(
                active_session_id=active_session.id if active_session is not None else None,
                visible_npc_ids=occupants,
                recent_chats=recent_chats,
                relationship_cues=relationship_cues,
            )
            repeat_guard_hint = render_repeat_guard_hint(
                npc_id=npc_id,
                action_log=self.action_log,
            )
            recent_loop_guards = self._recent_loop_guard_events(npc_id)
            if recent_loop_guards:
                repeat_guard_hint += " 最近 guard：" + "; ".join(
                    str(event.get("message", event.get("guard_type", "")))
                    for event in recent_loop_guards[-3:]
                )
                repeat_guard_hint += (
                    " 不要重复同一个失败 intent；先 inspect_affordances 或 "
                    "find_affordance_targets 查询建议目标，再 use_affordance 执行，"
                "如果当前段已无法推进则 complete_current_schedule。"
                )
            target_text = (
                f"{schedule.location_id}，目标：{schedule.intent}"
                if schedule is not None
                else "无"
            )
            situation = "\n".join(
                [
                    f"当前时间：{self.state.clock.label()}",
                    f"全局模拟每 tick 推进 {self.state.clock.stride_minutes} 分钟。",
                    f"当前位置：{location.name} ({location.id})",
                    f"地点描述：{location.description}",
                    f"当前日程目标：{target_text}",
                    "当前日程剩余时间："
                    + (
                        f"{schedule_remaining_minutes} 分钟"
                        if schedule_remaining_minutes is not None
                        else "无"
                    ),
                    "可达出口及移动耗时："
                    + (
                        ", ".join(
                            f"{exit_id}: {location.exit_travel_minutes.get(exit_id, DEFAULT_MOVE_MINUTES)} 分钟"
                            for exit_id in perception["exits"]
                        )
                        if perception["exits"]
                        else "无"
                    ),
                    f"可见 NPC：{', '.join(occupants) if occupants else '无'}",
                    "可见物体："
                    + (
                        ", ".join(
                            f"{obj.name} ({obj.id})：{obj.description}"
                            f"；affordances={_render_affordance_refs(obj.affordances)}"
                            for obj in objects
                        )
                        if objects
                        else "无"
                    ),
                    "当前位置 affordances："
                    + _render_affordance_refs(location.affordances),
                    "本地事件："
                    + (
                        "; ".join(event.summary for event in local_events)
                        if local_events
                        else "无"
                    ),
                    "待处理事件："
                    + (
                        "; ".join(event.summary for event in pending_events)
                        if pending_events
                        else "无"
                    ),
                    "可见 NPC 当前行动："
                    + (
                        "; ".join(
                            f"{other}: {action['action_type']} 从 {action['start_time']} "
                            f"到 {action['end_time']}，耗时 {action['duration_minutes']} 分钟"
                            for other, action in visible_actions.items()
                        )
                        if visible_actions
                        else "无"
                    ),
                    "我的当前行动状态："
                    + (
                        f"{own_action.action_type} 从 {_minute_label(own_action.start_minute)} "
                        f"到 {_minute_label(own_action.end_minute)}，"
                        f"耗时 {own_action.duration_minutes} 分钟，状态={own_action.status}"
                        if own_action is not None
                        else "无"
                    ),
                    "当前会话："
                    + (
                        f"{active_session.id}，参与者={', '.join(active_session.participants)}"
                        if active_session is not None
                        else "无"
                    ),
                    "最近对话："
                    + ("; ".join(recent_chats) if recent_chats else "无"),
                    "关系线索：" + _render_relationship_cues(relationship_cues),
                    "已知但当前不可见地点："
                    + _render_known_locations(perception["known_locations"]),
                    "已知但当前不可见物体："
                    + _render_known_objects(perception["known_objects"]),
                    "当前日程：" + _render_schedule(schedule),
                    "当前日程已完成行动：" + schedule_progress,
                    "日程满足证据：" + schedule_completion_hint,
                    "当前活动决策提示：",
                    "- 当前活动：" + schedule_decision_hint,
                    "- 对象选择：" + object_selection_hint,
                    "- 等待判断：" + wait_decision_hint,
                    "- 对话策略：" + conversation_policy_hint,
                    "- 重复检查：" + repeat_guard_hint,
                ]
            )
            extra = {
                "disabled_tools": ["memory_store"],
                "town": {
                    "known": True,
                    "time": self.state.clock.label(),
                    "location_id": location.id,
                    "exits": list(perception["exits"]),
                    "exit_travel_minutes": {
                        exit_id: location.exit_travel_minutes.get(exit_id, DEFAULT_MOVE_MINUTES)
                        for exit_id in perception["exits"]
                    },
                    "object_ids": [obj.id for obj in objects],
                    "location_affordances": [
                        _affordance_dict(affordance)
                        for affordance in location.affordances
                    ],
                    "object_affordances": {
                        obj.id: [_affordance_dict(affordance) for affordance in obj.affordances]
                        for obj in objects
                    },
                    "visible_npc_ids": occupants,
                    "relationship_cues": relationship_cues,
                    "visible_npc_actions": visible_actions,
                    "visible_event_ids": [event.id for event in local_events],
                    "perception": perception,
                    "schedule_revision": _schedule_revision_dict(schedule_revision),
                    "current_schedule": _schedule_dict(schedule),
                    "current_schedule_remaining_minutes": schedule_remaining_minutes,
                    "current_schedule_progress": schedule_progress,
                    "current_schedule_completion_hint": schedule_completion_hint,
                    "prompt_policy": {
                        "schedule_decision_hint": schedule_decision_hint,
                        "object_selection_hint": object_selection_hint,
                        "wait_decision_hint": wait_decision_hint,
                        "conversation_policy_hint": conversation_policy_hint,
                        "repeat_guard_hint": repeat_guard_hint,
                    },
                    "loop_guard_events": recent_loop_guards,
                    "current_schedule_target_location_id": (
                        schedule.location_id if schedule is not None else None
                    ),
                    "current_action": (
                        self._current_action_dict(npc_id)
                        if self.state.current_action_for(npc_id) is not None
                        else None
                    ),
                    "active_conversation_id": (
                        active_session.id if active_session is not None else None
                    ),
                }
            }

        memory = self.memory_for(npc_id)
        memory_context_query = "\n".join(part for part in [event, situation] if part)
        memory_text = memory.build_context(memory_context_query)
        history_text = self._render_history(npc_id)
        todo_text = render_todo_text(memory)

        return AgentContext(
            npc_id=npc_id,
            input_event=event,
            tools=self.tools_for(npc_id),
            memory=memory,
            route=AgentRoute.ACTION,
            world_rules=(
                "你只能感知当前语义地点中的信息。"
                "小镇世界引擎负责仲裁所有移动和世界状态变化。"
                "你必须通过小镇工具改变世界状态。"
                "日程安排是默认最高优先目标；除非出现 urgent/emergency/alarm 等紧急事件、"
                "明确的直接请求，或你有足够把握不会影响当前日程按时完成，"
                "不要为了顺路、好奇、闲聊或低优先级兴趣偏离当前日程目标。"
                "如果当前日程目标地点可达，应优先移动到目标地点或执行与目标直接相关的行动。"
                "只有当前场景信息不足、需要刷新本地可见状态、刚收到新事件但细节不清，"
                "或工具失败后需要重新确认环境时才使用 observe；"
                "已在 <situation> 中明确给出的地点、出口、可见物体、NPC 和事件，"
                "不要再用 observe 作为行动前的默认步骤。"
                "使用 move_to 沿明确出口移动，"
                "observe 只是查看状态，不代表世界行动完成，也不会推进全局时钟，"
                "不能用它替代移动、交互、说话、等待或完成日程。"
                "使用 wait 表示主动把接下来一段模拟时间用于原地等待，"
                "它不是等待下一个 tick 的流程控制工具。"
                "move_to、wait、talk_to、interact_with、use_affordance 一旦调用，本次行动就结束；"
                "下一次感知必须来自小镇世界引擎的下一次调度。"
                "对话统一使用 talk_to；短回复、采访和闲聊都由世界引擎托管。"
                "使用 interact_with 只与当前位置物体交互，"
                "如果不知道该去哪里或对象支持什么，使用 find_affordance_targets "
                "或 inspect_affordances；如果工具返回 suggested_affordances，"
                "不要重复同一失败 intent，应改用建议的 use_affordance。"
                "除 observe 外，小镇动作工具都会消耗模拟时间，工具返回值会展示动作的开始、"
                "耗时和完成时间。"
                "选择动作前应考虑动作耗时、移动耗时和当前日程剩余时间。"
                "选择动作前先判断当前活动是否已有足够证据，避免重复行动。"
                "普通日程由 TownWorldEngine 根据最终行动证据自动推进。"
                "只有 explicit policy、被阻塞或无法继续时才调用 complete_current_schedule。"
                "日程不是计时打卡；目标达成后不要为了填满剩余时间重复同类交互。"
                "非对话场景中不能只用自然语言描述行动；"
                "如果你正在执行小镇日程，最终必须调用一个具体小镇 action tool 或 wait 结束本次激活。"
                "move_to 可以请求目标地点；如果目标不直达但图上可达，"
                "世界引擎会沿最短路径自动推进到下一跳。"
                "不是所有可见 NPC 都必须聊天；只有值得交流时才使用 talk_to。"
            ),
            situation="\n".join(
                [
                    situation,
                    "相关长期记忆：",
                    memory_text,
                ]
            ),
            history=history_text,
            todo=todo_text,
            extra=extra,
        )

    def handle_response(self, npc_id: str, response: AgentResponse) -> None:
        history = self.history_for(npc_id)
        if response.dialogue:
            location = self.state.location_for(npc_id)
            location_id = location.id if location is not None else "unknown"
            self.state.events.append(
                self._event_for_dialogue(npc_id, location_id, response.dialogue)
            )
            history.append(
                speaker=npc_id,
                content=response.dialogue,
                metadata={
                    "source": "town_dialogue",
                    "location_id": location_id,
                    "clock_minute": self.state.clock.minute,
                },
            )

        memory = self.memory_for(npc_id)
        for update in response.memory_updates:
            metadata = {
                "source": "agent_response",
                "clock_minute": self.state.clock.minute,
                **update.metadata,
            }
            memory.remember(update.content, category=update.type, metadata=metadata)

    def execute_action(self, npc_id: str, action: ActionRequest) -> ActionResult:
        if action.type in {"move", "move_to"}:
            destination = action.payload.get("to", action.payload.get("destination_id"))
            if not isinstance(destination, str) or not destination:
                return self._failed_action(
                    action.type,
                    "missing_destination",
                    "移动需要提供目标地点 id。",
                    {"npc_id": npc_id, "payload": action.payload},
                    action_id=action.action_id,
                )

            routed_destination, route = (
                self._resolve_move_destination(npc_id, destination)
                if action.type == "move_to"
                else (destination, None)
            )
            travel_minutes = self._travel_minutes(npc_id, routed_destination or destination)
            result = self.state.move_npc(npc_id, routed_destination or destination)
            action_result = self._move_result_to_action_result(
                action,
                result,
                travel_minutes=travel_minutes,
                requested_destination_id=destination,
                route=route,
            )
            self._record_action_result(npc_id, action_result)
            return action_result

        if action.type == "wait":
            minutes = action.payload.get("minutes")
            if not isinstance(minutes, int):
                return self._failed_action(
                    action.type,
                    "missing_minutes",
                    "等待需要 payload {'minutes': <int>}。",
                    {"npc_id": npc_id, "payload": action.payload},
                    action_id=action.action_id,
                )
            return self.wait(npc_id, minutes, action_id=action.action_id)

        if action.type in {"complete_current_schedule", "finish_schedule_segment"}:
            note = action.payload.get("note", "")
            return self.complete_current_schedule(
                npc_id,
                str(note),
                action_id=action.action_id,
                action_type=action.type,
            )

        if action.type == "observe":
            return self.observe_action(npc_id, action_id=action.action_id)

        if action.type in {"speak", "speak_to"}:
            target = action.payload.get("target_npc_id", action.payload.get("target"))
            text = action.payload.get("text", action.payload.get("content", ""))
            if not isinstance(target, str) or not target:
                return self._failed_action(
                    action.type,
                    "missing_target_npc_id",
                    "说话需要提供目标 NPC id。",
                    {"npc_id": npc_id, "payload": action.payload},
                    action_id=action.action_id,
                )
            if not isinstance(text, str) or not text.strip():
                return self._failed_action(
                    action.type,
                    "missing_text",
                    "说话需要提供非空文本。",
                    {"npc_id": npc_id, "target_npc_id": target, "payload": action.payload},
                    action_id=action.action_id,
                )
            return self.speak_to(npc_id, target, text, action_id=action.action_id)

        if action.type in {"talk_to", "start_conversation", "conversation"}:
            target = action.payload.get("target_npc_id", action.payload.get("target"))
            topic = action.payload.get("topic_or_reason", action.payload.get("topic", ""))
            if not isinstance(target, str) or not target:
                return self._failed_action(
                    action.type,
                    "missing_target_npc_id",
                    "发起会话需要提供目标 NPC id。",
                    {"npc_id": npc_id, "payload": action.payload},
                    action_id=action.action_id,
                )
            return self.talk_to(
                npc_id,
                target,
                str(topic),
                action_id=action.action_id,
                action_type=action.type,
            )

        if action.type in {"interact", "interact_with"}:
            object_id = action.payload.get("object_id")
            intent = action.payload.get("intent", action.payload.get("text", ""))
            if not isinstance(object_id, str) or not object_id:
                return self._failed_action(
                    action.type,
                    "missing_object_id",
                    "交互需要提供当前位置物体 id。",
                    {"npc_id": npc_id, "payload": action.payload},
                    action_id=action.action_id,
                )
            if not isinstance(intent, str) or not intent.strip():
                return self._failed_action(
                    action.type,
                    "missing_intent",
                    "交互需要提供非空目的描述。",
                    {"npc_id": npc_id, "object_id": object_id, "payload": action.payload},
                    action_id=action.action_id,
                )
            return self.interact_with(npc_id, object_id, intent, action_id=action.action_id)

        if action.type in {"use_affordance", "affordance"}:
            target_id = action.payload.get("target_id", action.payload.get("object_id"))
            affordance_id = action.payload.get("affordance_id")
            note = action.payload.get("note", action.payload.get("intent", ""))
            if not isinstance(target_id, str) or not target_id:
                return self._failed_action(
                    action.type,
                    "missing_target_id",
                    "执行 affordance 需要提供当前位置或可见物体 id。",
                    {"npc_id": npc_id, "payload": action.payload},
                    action_id=action.action_id,
                )
            if not isinstance(affordance_id, str) or not affordance_id:
                return self._failed_action(
                    action.type,
                    "missing_affordance_id",
                    "执行 affordance 需要提供 affordance_id。",
                    {"npc_id": npc_id, "target_id": target_id, "payload": action.payload},
                    action_id=action.action_id,
                )
            return self.use_affordance(
                npc_id,
                target_id,
                affordance_id,
                str(note),
                action_id=action.action_id,
            )

        return self._failed_action(
            action.type,
            "unsupported_action",
            f"暂不支持小镇动作 '{action.type}'。",
            {"npc_id": npc_id, "payload": action.payload},
            action_id=action.action_id,
        )

    def tools_for(self, npc_id: str) -> list[ToolDef]:
        return [
            PlanTodoTool(),
            MoveToTool(lambda destination_id: self.move_to(npc_id, destination_id)),
            ObserveTool(lambda: self.observe_action(npc_id)),
            TalkToTool(
                lambda target_npc_id, topic_or_reason: self.talk_to(
                    npc_id,
                    target_npc_id,
                    topic_or_reason,
                )
            ),
            InteractWithTool(
                lambda object_id, intent: self.interact_with(npc_id, object_id, intent)
            ),
            InspectAffordancesTool(
                lambda target_id: self.inspect_affordances_action(npc_id, target_id)
            ),
            FindAffordanceTargetsTool(
                lambda query, location_id: self.find_affordance_targets_action(
                    npc_id,
                    query,
                    location_id,
                )
            ),
            UseAffordanceTool(
                lambda target_id, affordance_id, note: self.use_affordance(
                    npc_id,
                    target_id,
                    affordance_id,
                    note,
                )
            ),
            WaitTool(lambda minutes: self.wait(npc_id, minutes)),
            CompleteCurrentScheduleTool(
                lambda note: self.complete_current_schedule(npc_id, note)
            ),
        ]

    def move_to(self, npc_id: str, destination_id: str) -> ActionResult:
        return self.execute_action(
            npc_id,
            ActionRequest(type="move_to", payload={"destination_id": destination_id}),
        )

    def observe(self, npc_id: str) -> dict[str, object]:
        location = self.state.location_for(npc_id)
        schedule = self.state.current_schedule_segment(npc_id)
        if location is None:
            return {"known": False, "npc_id": npc_id}
        perception = self.build_perception(npc_id)
        return {
            "known": True,
            "npc_id": npc_id,
            "time": self.state.clock.label(),
            "location": {
                "id": location.id,
                "name": location.name,
                "description": location.description,
                "affordances": [
                    _affordance_dict(affordance)
                    for affordance in location.affordances
                ],
            },
            "exits": list(perception["exits"]),
            "visible_npcs": list(perception["visible_npc_ids"]),
            "objects": [
                {
                    "id": obj.id,
                    "name": obj.name,
                    "description": obj.description,
                    "interactable": obj.interactable,
                    "affordances": [
                        _affordance_dict(affordance)
                        for affordance in obj.affordances
                    ],
                }
                for obj_id in perception["object_ids"]
                if (obj := self.state.objects.get(str(obj_id))) is not None
            ],
            "local_events": [
                {
                    "id": event.id,
                    "minute": event.minute,
                    "actor_id": event.actor_id,
                    "event_type": event.event_type,
                    "summary": event.summary,
                }
                for event in self.visible_events_for(npc_id)
                if event.id in perception["visible_event_ids"]
            ],
            "known_locations": list(perception["known_locations"]),
            "known_objects": list(perception["known_objects"]),
            "perception": perception,
            "current_schedule": _schedule_dict(schedule),
        }

    def observe_action(
        self,
        npc_id: str,
        *,
        action_id: str | None = None,
    ) -> ActionResult:
        minute = self.state.clock.minute
        result = ActionResult(
            action_id=action_id or ActionRequest(type="observe").action_id,
            action_type="observe",
            status="succeeded",
            observation="已观察当前本地小镇状态。",
            facts={
                **self.observe(npc_id),
                "start_minute": minute,
                "duration_minutes": DEFAULT_OBSERVE_MINUTES,
                "end_minute": minute + DEFAULT_OBSERVE_MINUTES,
                "start_time": _minute_label(minute),
                "end_time": _minute_label(minute + DEFAULT_OBSERVE_MINUTES),
            },
        )
        self._record_free_action_result(npc_id, result)
        return result

    def inspect_affordances_action(
        self,
        npc_id: str,
        target_id: str | None = None,
        *,
        action_id: str | None = None,
    ) -> ActionResult:
        location = self.state.location_for(npc_id)
        if location is None:
            minute = self.state.clock.minute
            result = ActionResult(
                action_id=action_id or ActionRequest(type="inspect_affordances").action_id,
                action_type="inspect_affordances",
                status="failed",
                reason="unknown_npc",
                observation=f"{npc_id} 尚未被放置到小镇中。",
                facts={
                    "npc_id": npc_id,
                    "target_id": target_id,
                    "reason": "unknown_npc",
                    "start_minute": minute,
                    "duration_minutes": DEFAULT_OBSERVE_MINUTES,
                    "end_minute": minute + DEFAULT_OBSERVE_MINUTES,
                    "effect_model": "no_world_effect",
                    "occupancy_model": "instant_free",
                    "lifecycle_state": "free",
                    "effect_applied": False,
                },
            )
            self._record_free_action_result(npc_id, result)
            return result
        result = self.inspect_affordances(npc_id, target_id)
        status = "succeeded" if result["ok"] else "failed"
        facts = {
            **result,
            "start_minute": self.state.clock.minute,
            "duration_minutes": DEFAULT_OBSERVE_MINUTES,
            "end_minute": self.state.clock.minute + DEFAULT_OBSERVE_MINUTES,
            "effect_model": "no_world_effect",
            "occupancy_model": "instant_free",
            "lifecycle_state": "free",
            "effect_applied": False,
        }
        action_result = ActionResult(
            action_id=action_id or ActionRequest(type="inspect_affordances").action_id,
            action_type="inspect_affordances",
            status=status,
            observation=(
                "已查看可用 affordance。"
                if result["ok"]
                else str(result.get("message", "无法查看 affordance。"))
            ),
            reason=None if result["ok"] else str(result.get("reason", "unavailable")),
            facts=facts,
        )
        self._record_free_action_result(npc_id, action_result)
        return action_result

    def inspect_affordances(
        self,
        npc_id: str,
        target_id: str | None = None,
    ) -> dict[str, object]:
        location = self.state.location_for(npc_id)
        if location is None:
            return {
                "ok": False,
                "reason": "unknown_npc",
                "message": f"{npc_id} 尚未被放置到小镇中。",
                "available_targets": [],
            }
        available = self._available_affordance_targets(location)
        if target_id is None or not target_id:
            return {
                "ok": True,
                "location_id": location.id,
                "targets": [_public_affordance_target(item) for item in available],
            }
        target = self._affordance_target(location, target_id)
        if target is None:
            return {
                "ok": False,
                "reason": "target_not_visible",
                "message": f"{target_id} 不是当前位置或当前位置可见物体。",
                "location_id": location.id,
                "available_targets": [item["id"] for item in available],
            }
        return {
            "ok": True,
            "location_id": location.id,
            "targets": [_public_affordance_target(target)],
        }

    def find_affordance_targets_action(
        self,
        npc_id: str,
        query: str,
        location_id: str | None = None,
        *,
        action_id: str | None = None,
    ) -> ActionResult:
        result = self.find_affordance_targets(npc_id, query, location_id)
        ok = bool(result.get("ok"))
        minute = self.state.clock.minute
        results = result.get("results", [])
        result_count = len(results) if isinstance(results, list) else 0
        facts = {
            **result,
            "start_minute": minute,
            "duration_minutes": DEFAULT_OBSERVE_MINUTES,
            "end_minute": minute + DEFAULT_OBSERVE_MINUTES,
            "effect_model": "no_world_effect",
            "occupancy_model": "instant_free",
            "lifecycle_state": "free",
            "effect_applied": False,
        }
        action_result = ActionResult(
            action_id=action_id or ActionRequest(type="find_affordance_targets").action_id,
            action_type="find_affordance_targets",
            status="succeeded" if ok else "failed",
            reason=None if ok else str(result.get("reason", "unavailable")),
            observation=(
                f"找到 {result_count} 个 affordance 目标。"
                if ok
                else str(result.get("message", "无法查找 affordance 目标。"))
            ),
            facts=facts,
        )
        self._record_free_action_result(npc_id, action_result)
        return action_result

    def find_affordance_targets(
        self,
        npc_id: str,
        query: str,
        location_id: str | None = None,
        *,
        limit: int = 8,
    ) -> dict[str, object]:
        current_location = self.state.location_for(npc_id)
        if current_location is None:
            return {
                "ok": False,
                "reason": "unknown_npc",
                "message": f"{npc_id} 尚未被放置到小镇中。",
                "query": query,
                "results": [],
            }
        if location_id:
            scoped_location = self.state.locations.get(location_id)
            if scoped_location is None:
                return {
                    "ok": False,
                    "reason": "unknown_location",
                    "message": f"地点 {location_id} 不存在。",
                    "query": query,
                    "results": [],
                }
            locations = [scoped_location]
        else:
            locations = list(self.state.locations.values())

        matches: list[tuple[int, str, dict[str, object]]] = []
        for location in locations:
            self._append_affordance_target_matches(
                matches,
                query=query,
                location=location,
                target=self._location_affordance_target(location),
                current_location_id=current_location.id,
            )
            for obj in self.state.objects_at(location.id):
                self._append_affordance_target_matches(
                    matches,
                    query=query,
                    location=location,
                    target=self._object_affordance_target(obj),
                    current_location_id=current_location.id,
                )
        matches.sort(key=lambda item: (-item[0], item[1]))
        return {
            "ok": True,
            "query": query,
            "location_id": location_id,
            "current_location_id": current_location.id,
            "results": [item[2] for item in matches[:limit]],
        }

    def _append_affordance_target_matches(
        self,
        matches: list[tuple[int, str, dict[str, object]]],
        *,
        query: str,
        location: Location,
        target: dict[str, object],
        current_location_id: str,
    ) -> None:
        raw_affordances = target.get("affordances", [])
        affordances = (
            [
                item
                for item in raw_affordances
                if isinstance(item, SemanticAffordance)
            ]
            if isinstance(raw_affordances, list)
            else []
        )
        scored_affordances = [
            (score, affordance)
            for affordance in affordances
            if (score := _affordance_match_score(query, affordance)) > 0
        ]
        target_score = _text_match_score(
            query,
            " ".join(
                [
                    str(target.get("id", "")),
                    str(target.get("name", "")),
                    str(target.get("description", "")),
                    location.id,
                    location.name,
                ]
            ),
        )
        if not scored_affordances and target_score <= 0:
            return
        best_affordance_score = max((score for score, _ in scored_affordances), default=0)
        score = target_score + best_affordance_score
        if location.id == current_location_id:
            score += 3
            travel_hint = "current_location"
        elif location.id in self.state.locations[current_location_id].exits:
            score += 1
            travel_minutes = self.state.locations[current_location_id].exit_travel_minutes.get(
                location.id,
                DEFAULT_MOVE_MINUTES,
            )
            travel_hint = f"reachable_direct:{travel_minutes}m"
        else:
            travel_minutes = self._shortest_travel_minutes(current_location_id, location.id)
            travel_hint = (
                f"reachable_indirect:{travel_minutes}m"
                if travel_minutes is not None
                else "not_reachable_from_current_location"
            )
        matched_affordances = [
            _affordance_dict(affordance)
            for _, affordance in sorted(scored_affordances, key=lambda item: -item[0])
        ]
        if not matched_affordances and affordances:
            matched_affordances = [_affordance_dict(affordances[0])]
        matches.append(
            (
                score,
                str(target.get("id", "")),
                {
                    **_public_affordance_target(target),
                    "location_id": location.id,
                    "location_name": location.name,
                    "matched_affordances": matched_affordances[:3],
                    "travel_hint": travel_hint,
                },
            )
        )

    def _available_affordance_targets(
        self,
        location: Location,
    ) -> list[dict[str, object]]:
        targets = [self._location_affordance_target(location)]
        for obj in self.state.objects_at(location.id):
            targets.append(self._object_affordance_target(obj))
        return targets

    def _affordance_target(
        self,
        location: Location,
        target_id: str,
    ) -> dict[str, object] | None:
        if target_id == location.id:
            return self._location_affordance_target(location)
        if target_id not in location.object_ids:
            return None
        obj = self.state.objects.get(target_id)
        if obj is None or obj.location_id != location.id:
            return None
        return self._object_affordance_target(obj)

    def _location_affordance_target(self, location: Location) -> dict[str, object]:
        return {
            "id": location.id,
            "kind": "location",
            "name": location.name,
            "description": location.description,
            "affordances": location.affordances,
            "affordance_ids": [item.id for item in location.affordances],
            "affordance_details": [
                _affordance_dict(affordance)
                for affordance in location.affordances
            ],
        }

    def _object_affordance_target(self, obj: TownObject) -> dict[str, object]:
        return {
            "id": obj.id,
            "kind": "object",
            "name": obj.name,
            "description": obj.description,
            "interactable": obj.interactable,
            "affordances": obj.affordances,
            "affordance_ids": [item.id for item in obj.affordances],
            "affordance_details": [
                _affordance_dict(affordance)
                for affordance in obj.affordances
            ],
        }

    def relationship_cues_for(
        self,
        npc_id: str,
        visible_npc_ids: list[str],
    ) -> list[dict[str, object]]:
        cues: list[dict[str, object]] = []
        for partner_id in visible_npc_ids:
            if partner_id == npc_id:
                continue
            cooldown_until = self.state.conversation_cooldowns.get(
                self._conversation_pair_key(npc_id, partner_id),
            )
            active_cooldown = (
                cooldown_until
                if cooldown_until is not None and cooldown_until > self.state.clock.minute
                else None
            )
            cues.append(
                {
                    "partner_npc_id": partner_id,
                    "recent_conversations": self._recent_conversation_summaries(
                        npc_id,
                        partner_npc_id=partner_id,
                    ),
                    "impressions": self._relationship_impressions(npc_id, partner_id),
                    "cooldown_until_minute": active_cooldown,
                    "cooldown_until_time": (
                        _minute_label(active_cooldown)
                        if active_cooldown is not None
                        else None
                    ),
                    "conversation_block_reason": self._conversation_block_reason(
                        npc_id,
                        partner_id,
                    ),
                }
            )
        return cues

    def speak_to(
        self,
        npc_id: str,
        target_npc_id: str,
        text: str,
        *,
        action_id: str | None = None,
    ) -> ActionResult:
        location = self.state.location_for(npc_id)
        target_location = self.state.location_for(target_npc_id)
        if location is None:
            return self._failed_action(
                "speak_to",
                "unknown_npc",
                f"{npc_id} 尚未被放置到小镇中。",
                {"npc_id": npc_id, "target_npc_id": target_npc_id},
                action_id=action_id,
            )
        if target_location is None:
            return self._failed_action(
                "speak_to",
                "unknown_target_npc",
                f"目标 NPC {target_npc_id} 不存在或不在小镇中。",
                {"npc_id": npc_id, "target_npc_id": target_npc_id},
                action_id=action_id,
            )
        if target_location.id != location.id:
            return self._failed_action(
                "speak_to",
                "target_not_visible",
                f"{target_npc_id} 不在当前位置，无法直接说话。",
                {
                    "npc_id": npc_id,
                    "target_npc_id": target_npc_id,
                    "location_id": location.id,
                    "target_location_id": target_location.id,
                },
                action_id=action_id,
            )
        cooldown_until = self._speak_cooldowns.get((npc_id, target_npc_id), 0)
        if cooldown_until > self.state.clock.minute:
            return self._failed_action(
                "speak_to",
                "recent_speak_to_cooldown",
                f"{npc_id} 刚刚已经对 {target_npc_id} 说过话，短时间内不重复发送单句消息。",
                {
                    "npc_id": npc_id,
                    "target_npc_id": target_npc_id,
                    "cooldown_until_minute": cooldown_until,
                    "cooldown_until_time": _minute_label(cooldown_until),
                },
                action_id=action_id,
            )

        start_minute = max(self.state.clock.minute, self._next_available_minute(npc_id))
        event = TownEvent(
            id=f"event_{len(self.state.events) + 1}",
            minute=start_minute,
            location_id=location.id,
            actor_id=npc_id,
            event_type="speech",
            summary=f"{npc_id} 对 {target_npc_id} 说：{text}",
            target_ids=[target_npc_id],
        )
        self.state.events.append(event)
        self.event_bus.publish(event)
        self._speak_cooldowns[(npc_id, target_npc_id)] = (
            start_minute + self.speak_cooldown_minutes
        )
        metadata = {
            "source": "town_speech",
            "location_id": location.id,
            "clock_minute": self.state.clock.minute,
            "target_npc_id": target_npc_id,
        }
        self.history_for(npc_id).append(speaker=npc_id, content=text, metadata=metadata)
        self.history_for(target_npc_id).append(speaker=npc_id, content=text, metadata=metadata)

        result = self._timed_result(
            npc_id,
            action_id=action_id or ActionRequest(type="speak_to").action_id,
            action_type="speak_to",
            status="succeeded",
            observation=f"{npc_id} 已在 {location.id} 对 {target_npc_id} 说话。",
            facts={
                "npc_id": npc_id,
                "target_npc_id": target_npc_id,
                "location_id": location.id,
                "text": text,
                "event_id": event.id,
            },
            duration_minutes=self._speak_minutes(text),
        )
        self._record_action_result(npc_id, result)
        return result

    def start_conversation(
        self,
        npc_id: str,
        target_npc_id: str,
        topic_or_reason: str = "",
        *,
        action_id: str | None = None,
        action_type: str = "start_conversation",
    ) -> ActionResult:
        agent = self._active_step_agent
        if agent is None:
            return self._failed_action(
                action_type,
                "missing_agent",
                "当前没有可用于生成会话的 NPC agent。",
                {"npc_id": npc_id, "target_npc_id": target_npc_id},
                action_id=action_id,
            )

        blocked = self._conversation_block_reason(npc_id, target_npc_id)
        if blocked is not None:
            failed_facts: dict[str, object] = {
                "npc_id": npc_id,
                "target_npc_id": target_npc_id,
                "topic_or_reason": topic_or_reason,
            }
            cooldown_until = self.state.conversation_cooldowns.get(
                self._conversation_pair_key(npc_id, target_npc_id),
            )
            if blocked == "recent_conversation_cooldown" and cooldown_until is not None:
                failed_facts.update(
                    {
                        "cooldown_until_minute": cooldown_until,
                        "cooldown_until_time": _minute_label(cooldown_until),
                    }
                )
            return self._failed_action(
                action_type,
                blocked,
                f"{npc_id} 暂时不能和 {target_npc_id} 发起会话：{blocked}。",
                failed_facts,
                action_id=action_id,
            )

        location = self.state.location_for(npc_id)
        location_id = location.id if location is not None else "unknown"
        start_minute = max(self.state.clock.minute, self._next_available_minute(npc_id))
        session = ConversationSession(
            id=f"conversation_{len(self.state.conversation_sessions) + 1}",
            participants=(npc_id, target_npc_id),
            initiator_id=npc_id,
            location_id=location_id,
            topic=topic_or_reason,
            started_minute=start_minute,
            max_turns=self.chat_iter * 2,
        )
        self.state.conversation_sessions[session.id] = session

        speakers = (npc_id, target_npc_id)
        close_reason = "max_turns"
        for exchange_index in range(self.chat_iter):
            appended = self._append_conversation_turn(
                session,
                agent,
                speakers[0],
                speakers[1],
                closing=False,
            )
            if not appended and exchange_index == 0 and not session.turns:
                appended = self._append_conversation_turn(
                    session,
                    agent,
                    speakers[0],
                    speakers[1],
                    closing=False,
                )
            if not appended:
                return self._fail_empty_conversation(
                    session,
                    action_id=action_id or ActionRequest(type=action_type).action_id,
                    action_type=action_type,
                )
            if self._last_turn_repeats(session):
                close_reason = "repeat_detected"
                break
            if exchange_index > 0 and self._conversation_should_close(session):
                self._append_conversation_turn(
                    session,
                    agent,
                    speakers[1],
                    speakers[0],
                    closing=True,
                )
                close_reason = "natural_close"
                break

            if not self._append_conversation_turn(
                session,
                agent,
                speakers[1],
                speakers[0],
                closing=False,
            ):
                return self._fail_empty_conversation(
                    session,
                    action_id=action_id or ActionRequest(type=action_type).action_id,
                    action_type=action_type,
                )
            if self._last_turn_repeats(session):
                close_reason = "repeat_detected"
                break
            if self._conversation_should_close(session):
                close_reason = "natural_close"
                break
        else:
            close_reason = "max_turns"

        return self._close_conversation(
            session,
            close_reason,
            action_id=action_id or ActionRequest(type=action_type).action_id,
            action_type=action_type,
        )

    def talk_to(
        self,
        npc_id: str,
        target_npc_id: str,
        topic_or_reason: str = "",
        *,
        action_id: str | None = None,
        action_type: str = "talk_to",
    ) -> ActionResult:
        return self.start_conversation(
            npc_id,
            target_npc_id,
            topic_or_reason,
            action_id=action_id,
            action_type=action_type,
        )

    def interact_with(
        self,
        npc_id: str,
        object_id: str,
        intent: str,
        *,
        action_id: str | None = None,
    ) -> ActionResult:
        location = self.state.location_for(npc_id)
        if location is None:
            return self._failed_action(
                "interact_with",
                "unknown_npc",
                f"{npc_id} 尚未被放置到小镇中。",
                {"npc_id": npc_id, "object_id": object_id},
                action_id=action_id,
            )
        obj = self.state.objects.get(object_id)
        if obj is None:
            return self._failed_action(
                "interact_with",
                "unknown_object",
                f"物体 {object_id} 不存在。",
                {"npc_id": npc_id, "object_id": object_id},
                action_id=action_id,
            )
        if obj.location_id != location.id or object_id not in location.object_ids:
            return self._failed_action(
                "interact_with",
                "object_not_visible",
                f"{object_id} 不在当前位置，无法交互。",
                {
                    "npc_id": npc_id,
                    "object_id": object_id,
                    "location_id": location.id,
                    "object_location_id": obj.location_id,
                },
                action_id=action_id,
            )
        if not obj.interactable:
            return self._failed_action(
                "interact_with",
                "object_not_interactable",
                f"{object_id} 当前不可交互。",
                {"npc_id": npc_id, "object_id": object_id, "location_id": location.id},
                action_id=action_id,
            )
        if obj.affordances and not _intent_matches_affordance(intent, obj.affordances):
            return self._failed_action(
                "interact_with",
                "unsupported_affordance",
                f"{object_id} 不支持“{intent}”。",
                {
                    "npc_id": npc_id,
                    "object_id": object_id,
                    "location_id": location.id,
                    "intent": intent,
                    "available_affordances": [
                        _affordance_dict(affordance)
                        for affordance in obj.affordances
                    ],
                    "suggested_affordances": _suggest_affordances(
                        intent,
                        obj.affordances,
                    ),
                },
                action_id=action_id,
            )

        start_minute = max(self.state.clock.minute, self._next_available_minute(npc_id))
        event = TownEvent(
            id=f"event_{len(self.state.events) + 1}",
            minute=start_minute,
            location_id=location.id,
            actor_id=npc_id,
            event_type="interaction",
            summary=f"{npc_id} 与 {obj.name} 交互：{intent}",
        )
        self.state.events.append(event)
        result = self._timed_result(
            npc_id,
            action_id=action_id or ActionRequest(type="interact_with").action_id,
            action_type="interact_with",
            status="succeeded",
            observation=f"{npc_id} 已与 {obj.name} 交互。",
            facts={
                "npc_id": npc_id,
                "object_id": object_id,
                "location_id": location.id,
                "intent": intent,
                "matched_affordances": [
                    _affordance_dict(affordance)
                    for affordance in _matching_affordances(intent, obj.affordances)
                ],
                "event_id": event.id,
            },
            duration_minutes=DEFAULT_INTERACT_MINUTES,
        )
        self._record_action_result(npc_id, result)
        return result

    def use_affordance(
        self,
        npc_id: str,
        target_id: str,
        affordance_id: str,
        note: str = "",
        *,
        action_id: str | None = None,
    ) -> ActionResult:
        location = self.state.location_for(npc_id)
        if location is None:
            return self._failed_action(
                "use_affordance",
                "unknown_npc",
                f"{npc_id} 尚未被放置到小镇中。",
                {"npc_id": npc_id, "target_id": target_id, "affordance_id": affordance_id},
                action_id=action_id,
            )
        target = self._affordance_target(location, target_id)
        if target is None:
            available = self._available_affordance_targets(location)
            return self._failed_action(
                "use_affordance",
                "target_not_visible",
                f"{target_id} 不是当前位置或当前位置可见物体。",
                {
                    "npc_id": npc_id,
                    "target_id": target_id,
                    "affordance_id": affordance_id,
                    "location_id": location.id,
                    "available_targets": [item["id"] for item in available],
                },
                action_id=action_id,
            )
        affordances = cast(list[SemanticAffordance], target["affordances"])
        requested_affordance_id = affordance_id
        normalized_affordance_id = _normalize_match_text(affordance_id)
        affordance = next(
            (
                item
                for item in affordances
                if _normalize_match_text(item.id) == normalized_affordance_id
                or normalized_affordance_id
                in {_normalize_match_text(alias) for alias in item.aliases}
            ),
            None,
        )
        if affordance is None:
            return self._failed_action(
                "use_affordance",
                "unsupported_affordance",
                f"{target_id} 不支持 affordance '{affordance_id}'。",
                {
                    "npc_id": npc_id,
                    "target_id": target_id,
                    "affordance_id": requested_affordance_id,
                    "location_id": location.id,
                    "available_affordances": [
                        _affordance_dict(item) for item in affordances
                    ],
                    "suggested_affordances": _suggest_affordances(
                        requested_affordance_id,
                        affordances,
                    ),
                },
                action_id=action_id,
            )

        start_minute = max(self.state.clock.minute, self._next_available_minute(npc_id))
        target_name = str(target["name"])
        target_kind = str(target["kind"])
        summary_note = note.strip() or affordance.description or affordance.label
        event = TownEvent(
            id=f"event_{len(self.state.events) + 1}",
            minute=start_minute,
            location_id=location.id,
            actor_id=npc_id,
            event_type=affordance.event_type,
            summary=(
                f"{npc_id} 在 {target_name} 使用 {affordance.label}："
                f"{summary_note}"
            ),
        )
        self.state.events.append(event)
        result = self._timed_result(
            npc_id,
            action_id=action_id or ActionRequest(type="use_affordance").action_id,
            action_type="use_affordance",
            status="succeeded",
            observation=f"{npc_id} 已使用 {target_name} 的 {affordance.label}。",
            facts={
                "npc_id": npc_id,
                "target_id": target_id,
                "target_kind": target_kind,
                "affordance_id": affordance.id,
                "requested_affordance_id": requested_affordance_id,
                "affordance_label": affordance.label,
                "affordance_aliases": list(affordance.aliases),
                "event_type": affordance.event_type,
                "location_id": location.id,
                "note": summary_note,
                "event_id": event.id,
            },
            duration_minutes=max(1, affordance.duration_minutes),
        )
        self._record_action_result(npc_id, result)
        return result

    def wait(
        self,
        npc_id: str,
        minutes: int,
        *,
        action_id: str | None = None,
    ) -> ActionResult:
        location = self.state.location_for(npc_id)
        location_id = location.id if location is not None else "unknown"
        result = self._timed_result(
            npc_id,
            action_id=action_id or ActionRequest(type="wait").action_id,
            action_type="wait",
            status="succeeded",
            observation=(
                f"{npc_id} 在 {location_id} 等待 {minutes} 分钟。"
                "全局小镇时钟没有推进。"
            ),
            facts={
                "npc_id": npc_id,
                "location_id": location_id,
                "minutes": minutes,
                "clock_minute": self.state.clock.minute,
            },
            duration_minutes=minutes,
            current_action_status="waiting",
        )
        self._record_action_result(npc_id, result)
        return result

    def interrupt_current_action(
        self,
        npc_id: str,
        reason: str,
        *,
        minute: int | None = None,
    ) -> dict[str, object] | None:
        action = self.state.current_action_for(npc_id)
        if action is None:
            return None
        interrupted_minute = self.state.clock.minute if minute is None else minute
        action.lifecycle_state = "interrupted"
        action.interrupted_reason = reason
        action.finalized_minute = interrupted_minute
        self.state.clear_current_action(npc_id)
        evidence = self._finalized_action_dict(action, at_minute=interrupted_minute)
        evidence["lifecycle_state"] = "interrupted"
        self.action_log.append(
            {
                "day": self.state.clock.day,
                "time": _minute_label(interrupted_minute),
                "minute": interrupted_minute,
                "end_minute": action.end_minute,
                "npc_id": npc_id,
                "action_type": action.action_type,
                "status": action.status,
                "lifecycle_state": "interrupted",
                "effect_model": action.effect_model,
                "occupancy_model": action.occupancy_model,
                "effect_applied": action.effect_applied,
                "failure_reason": action.failure_reason,
                "interrupted_reason": reason,
                "next_available_minute": interrupted_minute,
                "location_id": action.location_id,
                "summary": action.summary,
                "facts": evidence,
            }
        )
        return evidence

    def finish_schedule_segment(
        self,
        npc_id: str,
        note: str = "",
        *,
        action_id: str | None = None,
        action_type: str = "finish_schedule_segment",
    ) -> ActionResult:
        return self.complete_current_schedule(
            npc_id,
            note,
            action_id=action_id,
            action_type=action_type,
        )

    def complete_current_schedule(
        self,
        npc_id: str,
        note: str = "",
        *,
        action_id: str | None = None,
        action_type: str = "complete_current_schedule",
    ) -> ActionResult:
        segment = self.state.current_schedule_segment(npc_id) or self._recoverable_overdue_segment(npc_id)
        if segment is None:
            return self._failed_action(
                action_type,
                "no_current_schedule_segment",
                f"{npc_id} 当前没有可完成的日程段。",
                {"npc_id": npc_id, "clock_minute": self.state.clock.minute},
                action_id=action_id,
            )
        accepted, completion_reason = self._explicit_completion_acceptance_reason(
            npc_id,
            segment,
        )
        if not accepted:
            return self._failed_action(
                action_type,
                completion_reason,
                f"{npc_id} 当前日程段缺少完成证据，不能标记完成。",
                {
                    "npc_id": npc_id,
                    "clock_minute": self.state.clock.minute,
                    "segment_start_minute": segment.start_minute,
                    "location_id": segment.location_id,
                    "current_location_id": self.state.location_id_for(npc_id),
                },
                action_id=action_id,
            )
        completion = self._record_schedule_completion(
            npc_id,
            segment,
            note=note,
            completion_type="explicit_request",
            matching_reason=completion_reason,
        )
        self._record_reflection_evidence(
            npc_id,
            evidence_type="schedule",
            summary=(
                f"完成日程：{_minute_label(segment.start_minute)} "
                f"在 {segment.location_id} {segment.intent}。"
                + (f"备注：{completion.note}" if completion.note else "")
            ),
            poignancy=2,
            metadata={
                "segment_start_minute": segment.start_minute,
                "location_id": segment.location_id,
                "note": completion.note,
            },
        )
        result = self._timed_result(
            npc_id,
            action_id=action_id or ActionRequest(type=action_type).action_id,
            action_type=action_type,
            status="succeeded",
            observation=(
                f"{npc_id} 已完成 {_minute_label(segment.start_minute)} 开始、"
                f"目标地点为 {segment.location_id} 的日程段。"
            ),
            facts={
                "npc_id": npc_id,
                "segment_start_minute": segment.start_minute,
                "location_id": segment.location_id,
                "note": completion.note,
                "completion_type": completion.completion_type,
                "completion_reason": completion_reason,
            },
            duration_minutes=0,
            occupancy_model="instant_free",
        )
        self._record_action_result(npc_id, result)
        return result

    def decompose_current_schedule_segment(self, npc_id: str) -> list[str]:
        """Persist deterministic subtasks for the active segment under town state."""
        segment = self.state.current_schedule_segment(npc_id)
        if segment is None:
            return []
        if not segment.subtasks:
            segment.subtasks = default_subtasks_for(segment) or [
                "到达目标地点",
                "执行与目标直接相关的行动",
                "避免重复已满足行动",
            ]
            self._record_planning_checkpoint(
                npc_id,
                day=self.state.clock.day,
                stage="segment_decomposition",
                payload={
                    "segment": _full_schedule_dict(segment),
                    "subtasks": list(segment.subtasks),
                },
            )
        return list(segment.subtasks)

    def revise_current_schedule_segment(
        self,
        npc_id: str,
        *,
        reason: str,
        subtasks: list[str] | None = None,
    ) -> ScheduleSegment | None:
        """Apply a bounded deterministic revision to the active segment only."""
        segment = self.state.current_schedule_segment(npc_id)
        if segment is None:
            return None
        before = _full_schedule_dict(segment)
        if subtasks is not None:
            segment.subtasks = [str(item) for item in subtasks]
        elif not segment.subtasks:
            segment.subtasks = self.decompose_current_schedule_segment(npc_id)
        if reason and f"revision:{reason}" not in segment.subtasks:
            segment.subtasks.append(f"revision:{reason}")
        self._record_planning_checkpoint(
            npc_id,
            day=self.state.clock.day,
            stage="schedule_revision",
            payload={
                "reason": reason,
                "before": before,
                "after": _full_schedule_dict(segment),
                "completed_evidence": [
                    _schedule_completion_dict(item)
                    for item in self.state.completed_schedule_segments.get(npc_id, [])
                ],
            },
        )
        return segment

    def revise_schedule_for_event(
        self,
        npc_id: str,
        event: TownEvent,
        reason: str = "",
    ) -> list[ScheduleSegment] | None:
        """Insert a deterministic short schedule segment for a significant event."""
        if npc_id not in self.state.residents:
            raise ValueError("unknown_resident")
        if not self._is_significant_event_for(npc_id, event):
            return None
        if event.location_id not in self.state.locations:
            return None

        current = self.state.current_schedule_segment(npc_id)
        if current is not None and current.location_id == event.location_id:
            return None
        revision_key = (npc_id, event.id)
        if revision_key in self._schedule_revisions:
            return None
        if any(
            f"event:{event.id}" in segment.subtasks
            for segment in self.state.schedule_for(npc_id)
        ):
            return None

        insert_start = self.state.clock.minute
        insert_duration = min(
            SCHEDULE_REVISION_MINUTES,
            max(1, self.state.clock.stride_minutes),
        )
        inserted = ScheduleSegment(
            npc_id=npc_id,
            start_minute=insert_start,
            duration_minutes=insert_duration,
            location_id=event.location_id,
            intent=f"处理事件：{event.summary}",
            subtasks=[f"event:{event.id}"],
        )
        revised = self._insert_schedule_segment(npc_id, inserted)
        self.state.set_schedule(npc_id, revised)

        revision = ScheduleRevision(
            npc_id=npc_id,
            event_id=event.id,
            reason=reason or self._significant_event_reason(npc_id, event),
            inserted_segment=inserted,
        )
        self._schedule_revisions[revision_key] = revision
        self._latest_schedule_revision_by_npc[npc_id] = revision
        return revised

    def _insert_schedule_segment(
        self,
        npc_id: str,
        inserted: ScheduleSegment,
    ) -> list[ScheduleSegment]:
        original = sorted(self.state.schedule_for(npc_id), key=lambda segment: segment.start_minute)
        revised: list[ScheduleSegment] = []
        inserted_done = False
        next_free_minute = inserted.start_minute

        for segment in original:
            if not inserted_done and segment.end_minute > inserted.start_minute:
                revised.append(inserted)
                inserted_done = True
                next_free_minute = inserted.end_minute

            if (
                inserted_done
                and segment.end_minute > inserted.start_minute
                and segment.start_minute < next_free_minute
            ):
                shifted_start = max(segment.start_minute, next_free_minute)
                shifted = ScheduleSegment(
                    npc_id=segment.npc_id,
                    start_minute=shifted_start,
                    duration_minutes=segment.duration_minutes,
                    location_id=segment.location_id,
                    intent=segment.intent,
                    subtasks=list(segment.subtasks),
                    completion_tags=list(segment.completion_tags),
                )
                revised.append(shifted)
                next_free_minute = shifted.end_minute
            else:
                revised.append(segment)

        if not inserted_done:
            revised.append(inserted)

        return sorted(revised, key=lambda segment: segment.start_minute)

    def _revise_schedule_from_perception(
        self,
        npc_id: str,
        perception: dict[str, Any],
    ) -> ScheduleRevision | None:
        visible_event_ids = set(perception.get("visible_event_ids", []))
        for event in self.visible_events_for(npc_id):
            if event.id not in visible_event_ids:
                continue
            if not self._is_significant_event_for(npc_id, event):
                continue
            self._record_event_reflection_evidence(npc_id, event)
            revision_key = (npc_id, event.id)
            existing = self._schedule_revisions.get(revision_key)
            if existing is not None:
                self._latest_schedule_revision_by_npc[npc_id] = existing
                return existing
            self.revise_schedule_for_event(
                npc_id,
                event,
                reason=self._significant_event_reason(npc_id, event),
            )
            return self._schedule_revisions.get(revision_key)
        return None

    def visible_events_for(self, npc_id: str) -> list[TownEvent]:
        perception = self.build_perception(npc_id)
        events_by_id = {event.id: event for event in self._local_event_candidates(npc_id)}
        return [
            events_by_id[event_id]
            for event_id in perception["visible_event_ids"]
            if event_id in events_by_id
        ]

    def build_perception(self, npc_id: str) -> dict[str, Any]:
        location = self.state.location_for(npc_id)
        if location is None:
            return {
                "known": False,
                "npc_id": npc_id,
                "location_id": None,
                "exits": [],
                "visible_npc_ids": [],
                "object_ids": [],
                "visible_event_ids": [],
                "known_locations": [],
                "known_objects": [],
                "limits": self._perception_limits_dict(),
            }

        schedule = self.state.current_schedule_segment(npc_id)
        policy = self.perception_policy
        event_candidates = self._local_event_candidates(npc_id)
        selected_events = self._select_events(
            npc_id,
            event_candidates,
            schedule,
            limit=policy.max_events,
        )
        selected_objects = self._select_objects(
            self.state.objects_at(location.id),
            schedule,
            limit=policy.max_objects,
        )
        selected_npc_ids = self._select_visible_npcs(
            npc_id,
            [other for other in location.occupant_ids if other != npc_id],
            schedule,
            limit=policy.max_npcs,
        )
        selected_exits = self._select_exits(location, schedule, limit=policy.max_exits)
        known_locations = self._known_location_rows(
            npc_id,
            current_location_id=location.id,
            visible_exit_ids=selected_exits,
            limit=policy.max_known_locations,
        )
        known_objects = self._known_object_rows(
            npc_id,
            visible_object_ids=[obj.id for obj in selected_objects],
            limit=policy.max_known_objects,
        )
        return {
            "known": True,
            "npc_id": npc_id,
            "location_id": location.id,
            "limits": self._perception_limits_dict(),
            "exits": selected_exits,
            "visible_npc_ids": selected_npc_ids,
            "object_ids": [obj.id for obj in selected_objects],
            "visible_event_ids": [event.id for event in selected_events],
            "events": [_event_dict(event) for event in selected_events],
            "objects": [_object_dict(obj) for obj in selected_objects],
            "visible_npcs": selected_npc_ids,
            "known_locations": known_locations,
            "known_objects": known_objects,
        }

    def _local_event_candidates(self, npc_id: str) -> list[TownEvent]:
        location = self.state.location_for(npc_id)
        if location is None:
            return []
        events = self.state.events
        if self._visible_event_count_limit is not None:
            events = events[: self._visible_event_count_limit]
        return [
            event
            for event in events
            if event.visible and event.location_id == location.id
        ]

    def _select_events(
        self,
        npc_id: str,
        events: list[TownEvent],
        schedule: ScheduleSegment | None,
        *,
        limit: int,
    ) -> list[TownEvent]:
        return sorted(events, key=lambda event: self._event_attention_key(npc_id, event, schedule))[
            :limit
        ]

    def _event_attention_key(
        self,
        npc_id: str,
        event: TownEvent,
        schedule: ScheduleSegment | None,
    ) -> tuple[int, int, int, str]:
        if npc_id in event.target_ids:
            priority = 0
        elif event.event_type in {"urgent", "emergency", "alarm"}:
            priority = 1
        elif _event_matches_schedule(event, schedule):
            priority = 2
        else:
            priority = 3
        return (priority, -event.minute, self.state.events.index(event), event.id)

    def _select_objects(
        self,
        objects: list[TownObject],
        schedule: ScheduleSegment | None,
        *,
        limit: int,
    ) -> list[TownObject]:
        return sorted(
            objects,
            key=lambda obj: (
                0 if _object_matches_schedule(obj, schedule) else 1,
                obj.id,
            ),
        )[:limit]

    def _select_visible_npcs(
        self,
        npc_id: str,
        visible_npc_ids: list[str],
        schedule: ScheduleSegment | None,
        *,
        limit: int,
    ) -> list[str]:
        return sorted(
            visible_npc_ids,
            key=lambda other: (
                0 if self._has_pending_event_from_or_for(npc_id, other) else 1,
                0 if self.state.current_action_for(other) is not None else 1,
                0 if self._npc_schedule_matches_location(other, schedule) else 1,
                other,
            ),
        )[:limit]

    def _select_exits(
        self,
        location: Location,
        schedule: ScheduleSegment | None,
        *,
        limit: int,
    ) -> list[str]:
        exit_order = {exit_id: index for index, exit_id in enumerate(location.exits)}
        return sorted(
            location.exits,
            key=lambda exit_id: (
                0 if schedule is not None and exit_id == schedule.location_id else 1,
                exit_order[exit_id],
            ),
        )[:limit]

    def _known_location_rows(
        self,
        npc_id: str,
        *,
        current_location_id: str,
        visible_exit_ids: list[str],
        limit: int,
    ) -> list[dict[str, object]]:
        resident = self.state.resident_for(npc_id)
        if resident is None:
            return []
        invisible_ids = [
            location_id
            for location_id in resident.spatial_memory.known_location_ids
            if location_id != current_location_id and location_id not in visible_exit_ids
        ]
        rows: list[dict[str, object]] = []
        for location_id in sorted(dict.fromkeys(invisible_ids)):
            location = self.state.locations.get(location_id)
            if location is None:
                continue
            rows.append(
                {
                    "id": location.id,
                    "name": location.name,
                    "description": location.description,
                    "exits": list(location.exits),
                    "affordances": [
                        _affordance_dict(affordance)
                        for affordance in location.affordances
                    ],
                }
            )
            if len(rows) >= limit:
                break
        return rows

    def _known_object_rows(
        self,
        npc_id: str,
        *,
        visible_object_ids: list[str],
        limit: int,
    ) -> list[dict[str, object]]:
        resident = self.state.resident_for(npc_id)
        if resident is None:
            return []
        visible = set(visible_object_ids)
        rows: list[dict[str, object]] = []
        for object_id in sorted(dict.fromkeys(resident.spatial_memory.known_object_ids)):
            if object_id in visible:
                continue
            obj = self.state.objects.get(object_id)
            if obj is None:
                continue
            rows.append(
                {
                    "id": obj.id,
                    "name": obj.name,
                    "location_id": obj.location_id,
                    "description": obj.description,
                    "interactable": obj.interactable,
                    "affordances": [
                        _affordance_dict(affordance)
                        for affordance in obj.affordances
                    ],
                }
            )
            if len(rows) >= limit:
                break
        return rows

    def _has_pending_event_from_or_for(self, npc_id: str, other_npc_id: str) -> bool:
        return any(
            event.actor_id == other_npc_id or other_npc_id in event.target_ids
            for event in self._inboxes.get(npc_id, [])
        )

    def _npc_schedule_matches_location(
        self,
        npc_id: str,
        schedule: ScheduleSegment | None,
    ) -> bool:
        if schedule is None:
            return False
        other_schedule = self.state.current_schedule_segment(npc_id)
        return (
            other_schedule is not None
            and other_schedule.location_id == schedule.location_id
        )

    def _perception_limits_dict(self) -> dict[str, int]:
        return {
            "events": self.perception_policy.max_events,
            "objects": self.perception_policy.max_objects,
            "npcs": self.perception_policy.max_npcs,
            "exits": self.perception_policy.max_exits,
            "known_locations": self.perception_policy.max_known_locations,
            "known_objects": self.perception_policy.max_known_objects,
        }

    def _record_event_reflection_evidence(self, npc_id: str, event: TownEvent) -> None:
        self._record_reflection_evidence(
            npc_id,
            evidence_type="event",
            summary=f"重要事件：{event.summary}",
            poignancy=_event_poignancy(npc_id, event),
            clock_minute=event.minute,
            metadata={
                "event_id": event.id,
                "event_type": event.event_type,
                "location_id": event.location_id,
            },
        )

    def _record_reflection_evidence(
        self,
        npc_id: str,
        *,
        evidence_type: str,
        summary: str,
        poignancy: int,
        metadata: dict[str, object],
        clock_minute: int | None = None,
    ) -> ReflectionEvidence | None:
        resident = self.state.resident_for(npc_id)
        if resident is None:
            return None
        if _has_duplicate_reflection_evidence(
            resident.reflection_evidence,
            evidence_type=evidence_type,
            metadata=metadata,
        ):
            return None
        evidence = ReflectionEvidence(
            id=f"{npc_id}_{evidence_type}_{len(resident.reflection_evidence) + 1}",
            evidence_type=evidence_type,
            summary=summary,
            poignancy=poignancy,
            clock_minute=self.state.clock.minute if clock_minute is None else clock_minute,
            metadata=metadata,
        )
        resident.reflection_evidence.append(evidence)
        resident.poignancy += poignancy
        return evidence

    def _finalize_due_current_actions(
        self,
        npc_ids: list[str],
        *,
        at_minute: int,
    ) -> list[dict[str, object]]:
        finalized: list[dict[str, object]] = []
        for npc_id in npc_ids:
            action = self.state.current_action_for(npc_id)
            if action is None or action.end_minute > at_minute:
                continue
            action.lifecycle_state = "finalized"
            action.finalized_minute = at_minute
            self.state.clear_current_action(npc_id)
            finalized_action = self._finalized_action_dict(action, at_minute=at_minute)
            completion = self._infer_schedule_completion_from_finalized_action(
                npc_id,
                finalized_action,
                at_minute=at_minute,
            )
            if completion is not None:
                finalized_action["schedule_completion"] = _schedule_completion_dict(completion)
            finalized.append(finalized_action)
        return finalized

    def _finalized_action_dict(
        self,
        action: CurrentAction,
        *,
        at_minute: int,
    ) -> dict[str, object]:
        return {
            "npc_id": action.npc_id,
            "action_type": action.action_type,
            "location_id": action.location_id,
            "start_minute": action.start_minute,
            "duration_minutes": action.duration_minutes,
            "end_minute": action.end_minute,
            "finalized_minute": at_minute,
            "status": action.metadata.get("result_status", action.status),
            "submitted_status": action.status,
            "lifecycle_state": action.lifecycle_state,
            "effect_model": action.effect_model,
            "occupancy_model": action.occupancy_model,
            "effect_applied": action.effect_applied,
            "failure_reason": action.failure_reason,
            "interrupted_reason": action.interrupted_reason,
            "summary": action.summary,
            "action_id": action.metadata.get("action_id"),
            "facts": dict(action.metadata.get("facts", {}))
            if isinstance(action.metadata.get("facts"), dict)
            else {},
        }

    def _current_action_lifecycle_snapshot(
        self,
        npc_ids: list[str],
    ) -> dict[str, dict[str, object]]:
        snapshot: dict[str, dict[str, object]] = {}
        for npc_id in npc_ids:
            action = self.state.current_action_for(npc_id)
            if action is None:
                snapshot[npc_id] = {"lifecycle_state": "idle"}
                continue
            snapshot[npc_id] = {
                "action_type": action.action_type,
                "start_minute": action.start_minute,
                "duration_minutes": action.duration_minutes,
                "end_minute": action.end_minute,
                "status": action.status,
                "lifecycle_state": action.lifecycle_state,
                "effect_model": action.effect_model,
                "occupancy_model": action.occupancy_model,
                "effect_applied": action.effect_applied,
                "failure_reason": action.failure_reason,
                "interrupted_reason": action.interrupted_reason,
            }
        return snapshot

    def schedule_segment_state(
        self,
        npc_id: str,
        segment: ScheduleSegment,
        *,
        minute: int | None = None,
        day_end_reached: bool = False,
    ) -> dict[str, object]:
        check_minute = self.state.clock.minute if minute is None else minute
        completed = self.state.is_schedule_segment_complete(npc_id, segment)
        flags: set[str] = set()
        if _schedule_is_fallback(segment):
            flags.add("fallback")
        if self._segment_has_revision_evidence(npc_id, segment):
            flags.add("revised")
        if self._segment_has_drift_evidence(npc_id, segment):
            flags.add("drifted")
        if self._segment_has_interruption_evidence(npc_id, segment):
            flags.add("interrupted")

        if completed:
            base_status = "completed"
        elif self.state.is_schedule_segment_satisfied(npc_id, segment):
            if segment.completion_policy == "occupy_until_segment_end" and check_minute < segment.end_minute:
                base_status = "satisfied_in_progress"
            else:
                base_status = "active" if segment.contains(check_minute) else "pending"
        elif day_end_reached and segment.end_minute <= check_minute:
            base_status = "missed"
            if check_minute >= segment.end_minute:
                flags.add("overdue")
        elif segment.start_minute <= check_minute < segment.end_minute:
            base_status = "active"
        elif check_minute >= segment.end_minute:
            base_status = "pending"
            flags.add("overdue")
        else:
            base_status = "pending"

        return {
            "npc_id": npc_id,
            "day": self.state.clock.day if segment.day is None else segment.day,
            "segment_start_minute": segment.start_minute,
            "segment_end_minute": segment.end_minute,
            "location_id": segment.location_id,
            "intent": segment.intent,
            "base_status": base_status,
            "flags": sorted(flags),
            "completed": completed,
            "satisfied": self.state.is_schedule_segment_satisfied(npc_id, segment),
            "active": base_status == "active",
            "satisfied_in_progress": base_status == "satisfied_in_progress",
            "overdue": "overdue" in flags,
            "missed": base_status == "missed",
            "fallback": "fallback" in flags,
            "revised": "revised" in flags,
            "drifted": "drifted" in flags,
            "interrupted": "interrupted" in flags,
        }

    def _record_due_schedule_evidence(
        self,
        npc_ids: list[str],
        *,
        at_minute: int,
    ) -> list[dict[str, object]]:
        evidence: list[dict[str, object]] = []
        for npc_id in npc_ids:
            for segment in self.state.schedule_for(npc_id):
                if segment.end_minute > at_minute:
                    continue
                satisfaction = self.state.schedule_segment_satisfaction(npc_id, segment)
                if (
                    satisfaction is not None
                    and not self.state.is_schedule_segment_complete(npc_id, segment)
                    and segment.completion_policy == "occupy_until_segment_end"
                ):
                    completion = self._record_schedule_completion(
                        npc_id,
                        segment,
                        note="automatic completion after satisfied sustained segment reached end minute",
                        completion_type="automatic_action_match",
                        matched_action_id=satisfaction.matched_action_id,
                        matched_action_type=satisfaction.matched_action_type,
                        matching_reason=satisfaction.matching_reason,
                        completion_policy=segment.completion_policy,
                        action_end_minute=satisfaction.action_end_minute,
                        completion_reason="occupy_until_segment_end:segment_end_reached",
                    )
                    state = self.schedule_segment_state(npc_id, segment, minute=at_minute)
                    self._record_planning_checkpoint(
                        npc_id,
                        day=int(state["day"]),
                        stage="schedule_completion_automatic",
                        payload={
                            "completion": _schedule_completion_dict(completion),
                            "segment": _full_schedule_dict(segment),
                            "satisfaction": _schedule_satisfaction_dict(satisfaction),
                            "reason": "occupy_until_segment_end:segment_end_reached",
                        },
                    )
                    evidence.append(state)
                    continue
                state = self.schedule_segment_state(npc_id, segment, minute=at_minute)
                if not state["overdue"] or state["completed"]:
                    continue
                if self._has_schedule_evidence(
                    npc_id,
                    "schedule_overdue",
                    segment,
                    day=int(state["day"]),
                ):
                    continue
                self._record_planning_checkpoint(
                    npc_id,
                    day=int(state["day"]),
                    stage="schedule_overdue",
                    payload={
                        "segment": _full_schedule_dict(segment),
                        "state": state,
                        "current_location_id": self.state.location_id_for(npc_id),
                    },
                )
                evidence.append(state)
        return evidence

    def step(  # type: ignore[override]
        self,
        agent: TownAgent,
        npc_ids: list[str] | None = None,
    ) -> list[dict[str, object]]:
        self.npc_registry.sync_from_state(self.state)
        active_npcs = self.npc_registry.active_ids(npc_ids)
        tick = len(self.replay_log) + 1
        tick_start_minute = self.state.clock.minute
        finalized_actions = self._finalize_due_current_actions(
            active_npcs,
            at_minute=tick_start_minute,
        )
        overdue_schedule_evidence = self._record_due_schedule_evidence(
            active_npcs,
            at_minute=tick_start_minute,
        )
        finalized_by_npc = {
            str(item["npc_id"]): item
            for item in finalized_actions
            if isinstance(item.get("npc_id"), str)
        }
        input_order = {npc_id: index for index, npc_id in enumerate(active_npcs)}
        next_available = {
            npc_id: self._next_available_minute(npc_id, at_minute=tick_start_minute)
            for npc_id in active_npcs
        }
        ready_npcs = [
            npc_id
            for npc_id in active_npcs
            if next_available[npc_id] <= tick_start_minute
        ]
        ready_npcs.sort(
            key=lambda npc_id: (
                int(finalized_by_npc.get(npc_id, {}).get("end_minute", next_available[npc_id])),
                input_order[npc_id],
            )
        )
        visible_event_limit = len(self.state.events)
        inbox_snapshot = {npc_id: self.event_bus.drain(npc_id) for npc_id in ready_npcs}

        records: list[dict[str, object]] = []
        self._visible_event_count_limit = visible_event_limit
        previous_agent = self._active_step_agent
        self._active_step_agent = agent
        try:
            for npc_id in ready_npcs:
                if self._next_available_minute(npc_id, at_minute=tick_start_minute) > tick_start_minute:
                    continue
                event = self._activation_event(npc_id, inbox_snapshot.get(npc_id, []))
                if event is None:
                    continue
                before_actions = len(self.action_log)
                context = self.build_context(npc_id, event)
                response = agent.run(context)
                action_results = [status.model_dump() for status in response.tool_statuses]
                self.handle_response(npc_id, response)
                records.append(
                    {
                        "tick": tick,
                        "time": self.state.clock.label(),
                        "minute": tick_start_minute,
                        "npc_id": npc_id,
                        "input_event": event,
                        "dialogue": response.dialogue,
                        "action_results": action_results,
                        "logged_actions": self.action_log[before_actions:],
                    }
                )
        finally:
            self._visible_event_count_limit = None
            self._active_step_agent = previous_agent

        ran_npc_ids = [str(record["npc_id"]) for record in records]
        skipped_npc_ids = [
            npc_id
            for npc_id in active_npcs
            if npc_id not in {str(record["npc_id"]) for record in records}
        ]
        skipped_reasons = {
            npc_id: self._skip_reason(
                npc_id,
                at_minute=tick_start_minute,
                next_available=next_available.get(npc_id, tick_start_minute),
            )
            for npc_id in skipped_npc_ids
        }
        self.replay_log.append(
            {
                "tick": tick,
                "time": _minute_label(tick_start_minute),
                "minute": tick_start_minute,
                "ran_npc_ids": ran_npc_ids,
                "skipped_npc_ids": skipped_npc_ids,
                "skipped_reasons": skipped_reasons,
                "next_available_minutes": next_available,
                "finalized_actions": finalized_actions,
                "schedule_evidence": overdue_schedule_evidence,
                "current_action_lifecycle": self._current_action_lifecycle_snapshot(active_npcs),
                "records": records,
                "snapshot": self.build_replay_snapshot(
                    active_npcs,
                    minute=tick_start_minute,
                    finalized_actions=finalized_actions,
                ),
            }
        )
        self.state.clock.minute += self.state.clock.stride_minutes
        return records

    def write_replay_artifacts(self, output_dir: str | Path) -> dict[str, Path]:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        actions_path = output / "town_replay.jsonl"
        timeline_path = output / "town_timeline.txt"
        checkpoints_path = output / "town_checkpoints.jsonl"
        reflections_path = output / "town_reflections.jsonl"

        with actions_path.open("w", encoding="utf-8") as f:
            for item in self.action_log:
                f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")

        with checkpoints_path.open("w", encoding="utf-8") as f:
            for item in self.replay_log:
                f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")

        with reflections_path.open("w", encoding="utf-8") as f:
            for item in self.reflection_log:
                f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")

        with timeline_path.open("w", encoding="utf-8") as f:
            for item in self.planning_log:
                f.write(
                    f"[{item.get('time')}] {item.get('npc_id')} planning "
                    f"{item.get('stage')} day={item.get('day')}\n"
                )
            for item in self.loop_guard_events:
                f.write(
                    f"[{item.get('time')}] {item.get('npc_id')} loop_guard "
                    f"{item.get('guard_type')}: {item.get('message')}\n"
                )
            for item in self.action_log:
                f.write(
                    f"[{item.get('time')}] {item.get('npc_id')} "
                    f"{item.get('action_type')} {item.get('status')} "
                    f"@ {item.get('location_id')}: {item.get('summary')}\n"
                )

        return {
            "actions": actions_path,
            "timeline": timeline_path,
            "checkpoints": checkpoints_path,
            "reflections": reflections_path,
        }

    def _append_conversation_turn(
        self,
        session: ConversationSession,
        agent: TownAgent,
        speaker_id: str,
        listener_id: str,
        *,
        closing: bool,
    ) -> bool:
        event = self._conversation_input_event(
            session,
            speaker_id=speaker_id,
            listener_id=listener_id,
            closing=closing,
        )
        context = self.build_context(speaker_id, event)
        context.tools = []
        context.route = AgentRoute.DIALOGUE
        context.world_rules = (
            "你正在参与一段由 TownWorldEngine 托管的 NPC-NPC 会话。"
            "本阶段可以用记忆工具确认关系和背景，但不得移动 NPC，不得写世界动作，不得描述工具调用。"
            "只输出对对方说的 1 到 3 句中文台词。"
            "如果对话已经自然结束，只做一句自然收尾，不要继续推进移动、交互或日程动作。"
            "不要提到 start_conversation、conversation_session、tool、input_event 等内部实现词。"
        )
        context.extra.setdefault("town", {})["conversation_session_id"] = session.id
        context.extra["town"]["conversation_partner_id"] = listener_id
        context.extra["town"]["conversation_closing_turn"] = closing
        context.extra["town"]["relationship_cues"] = self.relationship_cues_for(
            speaker_id,
            [listener_id],
        )
        response = agent.run(context)
        text = response.dialogue.strip()
        if not text:
            text = response.inner_thought.strip()
        if not text:
            return False
        text = _clean_conversation_text(_strip_speaker_prefix(text, speaker_id))
        if not text:
            return False
        session.turns.append(
            ConversationTurn(
                speaker_id=speaker_id,
                listener_id=listener_id,
                text=text,
                minute=max(self.state.clock.minute, self._next_available_minute(speaker_id)),
            )
        )
        return True

    def _close_conversation(
        self,
        session: ConversationSession,
        close_reason: str,
        *,
        action_id: str,
        action_type: str = "start_conversation",
    ) -> ActionResult:
        session.status = "closed"
        session.close_reason = close_reason
        duration_minutes = self._conversation_duration_minutes(session)
        session.ended_minute = session.started_minute + duration_minutes
        cooldown_until = session.ended_minute + self.conversation_cooldown_minutes
        self.state.conversation_cooldowns[self._conversation_pair_key(*session.participants)] = (
            cooldown_until
        )

        transcript = self._conversation_transcript(session)
        summary = self._conversation_summary(session)
        event = TownEvent(
            id=f"event_{len(self.state.events) + 1}",
            minute=session.started_minute,
            location_id=session.location_id,
            actor_id=session.initiator_id,
            event_type="conversation",
            summary=summary,
            visible=False,
            target_ids=[p for p in session.participants if p != session.initiator_id],
        )
        self.state.events.append(event)

        for participant in session.participants:
            partner = next(p for p in session.participants if p != participant)
            self._append_conversation_history(participant, session, transcript)
            self.memory_for(participant).remember(
                self._participant_conversation_impression(participant, partner, session),
                category="impression",
                metadata={
                    "source": "town_conversation",
                    "conversation_session_id": session.id,
                    "relationship_pair_key": self._conversation_pair_key(*session.participants),
                    "relationship_participants": ",".join(session.participants),
                    "relationship_summary": self._relationship_summary(
                        participant,
                        partner,
                        session,
                    ),
                    "partner_npc_id": partner,
                    "location_id": session.location_id,
                    "clock_minute": session.started_minute,
                    "close_reason": close_reason,
                    "topic_or_reason": session.topic,
                    "unresolved_topics": ",".join(
                        self._conversation_unresolved_topics(session)
                    ),
                    "follow_up_intentions": ",".join(
                        self._conversation_follow_up_intentions(participant, partner, session)
                    ),
                },
            )
            for index, follow_up in enumerate(
                self._conversation_follow_up_intentions(participant, partner, session),
                start=1,
            ):
                self.memory_for(participant).remember(
                    follow_up,
                    category="todo",
                    metadata={
                        "source": "town_conversation_followup",
                        "status": "open",
                        "todo_id": f"{session.id}_{participant}_followup_{index}",
                        "conversation_session_id": session.id,
                        "partner_npc_id": partner,
                        "relationship_pair_key": self._conversation_pair_key(
                            *session.participants
                        ),
                        "topic_or_reason": session.topic,
                        "created_at": f"day-{self.state.clock.day}:{session.started_minute}",
                    },
                )
            self._record_reflection_evidence(
                participant,
                evidence_type="conversation",
                summary=self._participant_conversation_impression(
                    participant,
                    partner,
                    session,
                ),
                poignancy=3,
                clock_minute=session.started_minute,
                metadata={
                    "conversation_session_id": session.id,
                    "relationship_pair_key": self._conversation_pair_key(*session.participants),
                    "relationship_summary": self._relationship_summary(
                        participant,
                        partner,
                        session,
                    ),
                    "partner_npc_id": partner,
                    "location_id": session.location_id,
                    "close_reason": close_reason,
                    "topic_or_reason": session.topic,
                    "unresolved_topics": ",".join(
                        self._conversation_unresolved_topics(session)
                    ),
                    "follow_up_intentions": ",".join(
                        self._conversation_follow_up_intentions(participant, partner, session)
                    ),
                },
            )
            self.state.set_current_action(
                participant,
                CurrentAction(
                    npc_id=participant,
                    action_type="conversation",
                    location_id=session.location_id,
                    start_minute=session.started_minute,
                    duration_minutes=duration_minutes,
                    status="conversation",
                    summary=summary,
                    lifecycle_state="in_progress",
                    effect_model="immediate_effect",
                    occupancy_model="duration_occupied",
                    effect_applied=True,
                    metadata={"conversation_session_id": session.id},
                ),
            )

        result = ActionResult(
            action_id=action_id,
            action_type=action_type,
            status="succeeded",
            observation=summary,
            facts={
                "conversation_session_id": session.id,
                "participants": list(session.participants),
                "location_id": session.location_id,
                "topic_or_reason": session.topic,
                "turn_count": len(session.turns),
                "close_reason": close_reason,
                "transcript": [
                    {
                        "speaker_id": turn.speaker_id,
                        "listener_id": turn.listener_id,
                        "text": turn.text,
                        "minute": turn.minute,
                    }
                    for turn in session.turns
                ],
                "start_minute": session.started_minute,
                "duration_minutes": duration_minutes,
                "end_minute": session.ended_minute,
                "start_time": _minute_label(session.started_minute),
                "end_time": _minute_label(session.ended_minute),
                "cooldown_until_minute": cooldown_until,
                "lifecycle_state": "in_progress",
                "effect_model": "immediate_effect",
                "occupancy_model": "duration_occupied",
                "effect_applied": True,
            },
        )
        self._record_action_result(session.initiator_id, result)
        return result

    def _fail_empty_conversation(
        self,
        session: ConversationSession,
        *,
        action_id: str,
        action_type: str,
    ) -> ActionResult:
        session.status = "closed"
        session.close_reason = "empty_conversation"
        session.ended_minute = session.started_minute
        result = ActionResult(
            action_id=action_id,
            action_type=action_type,
            status="failed",
            reason="empty_conversation",
            observation=(
                f"{session.initiator_id} 和 "
                f"{next(p for p in session.participants if p != session.initiator_id)} "
                "没有形成有效对话。"
            ),
            facts={
                "conversation_session_id": session.id,
                "participants": list(session.participants),
                "location_id": session.location_id,
                "topic_or_reason": session.topic,
                "turn_count": len(session.turns),
                "close_reason": "empty_conversation",
                "transcript": [
                    {
                        "speaker_id": turn.speaker_id,
                        "listener_id": turn.listener_id,
                        "text": turn.text,
                        "minute": turn.minute,
                    }
                    for turn in session.turns
                ],
                "start_minute": session.started_minute,
                "duration_minutes": DEFAULT_FAILED_ACTION_MINUTES,
                "end_minute": session.started_minute + DEFAULT_FAILED_ACTION_MINUTES,
                "start_time": _minute_label(session.started_minute),
                "end_time": _minute_label(session.started_minute + DEFAULT_FAILED_ACTION_MINUTES),
                "lifecycle_state": "failed",
                "effect_model": "immediate_effect",
                "occupancy_model": "duration_occupied",
                "effect_applied": False,
            },
        )
        self._record_current_action(
            session.initiator_id,
            result,
            start_minute=session.started_minute,
            duration_minutes=DEFAULT_FAILED_ACTION_MINUTES,
            effect_model="immediate_effect",
            occupancy_model="duration_occupied",
        )
        self._record_action_result(session.initiator_id, result)
        return result

    def _conversation_block_reason(self, npc_id: str, target_npc_id: str) -> str | None:
        location = self.state.location_for(npc_id)
        target_location = self.state.location_for(target_npc_id)
        if location is None:
            return "unknown_npc"
        if target_location is None:
            return "unknown_target_npc"
        if location.id != target_location.id:
            return "target_not_visible"
        for participant in (npc_id, target_npc_id):
            active = self.state.active_conversation_for(participant)
            if active is not None:
                return "already_in_conversation"
            action = self.state.current_action_for(participant)
            if (
                action is not None
                and action.action_type == "conversation"
                and action.end_minute > self.state.clock.minute
            ):
                return "already_in_conversation"
            if action is not None and action.end_minute > self.state.clock.minute:
                return "participant_busy"
            if action is not None and action.action_type == "sleep":
                return "participant_sleeping"
        cooldown_until = self.state.conversation_cooldowns.get(
            self._conversation_pair_key(npc_id, target_npc_id),
            0,
        )
        if cooldown_until > self.state.clock.minute:
            return "recent_conversation_cooldown"
        return None

    def _conversation_input_event(
        self,
        session: ConversationSession,
        *,
        speaker_id: str,
        listener_id: str,
        closing: bool,
    ) -> str:
        transcript = self._conversation_transcript(session) or "（对话尚未开始）"
        if closing:
            instruction = "请用一句自然的收尾回应结束这段对话，不要提出新的问题。"
        else:
            instruction = "请以角色身份对对方说 1-3 句话。"
        return "\n".join(
            [
                f"你正在与 {listener_id} 进行小镇会话 {session.id}。",
                f"话题/原因：{session.topic or '自然交流'}",
                "当前对话记录：",
                transcript,
                instruction,
            ]
        )

    def _conversation_should_close(self, session: ConversationSession) -> bool:
        if not session.turns:
            return False
        text = session.turns[-1].text.strip()
        if _looks_like_open_question(text):
            return False
        close_markers = (
            "再见",
            "回头见",
            "待会",
            "下次",
            "先这样",
            "先到这里",
            "我先去",
            "我得走",
            "我该去",
            "谢谢你",
            "谢谢你的",
        )
        return any(marker in text for marker in close_markers)

    def _last_turn_repeats(self, session: ConversationSession) -> bool:
        if len(session.turns) < 3:
            return False
        last = session.turns[-1]
        last_text = _normalize_dialogue(last.text)
        if not last_text:
            return False
        for turn in session.turns[:-1]:
            if turn.speaker_id == last.speaker_id and _normalize_dialogue(turn.text) == last_text:
                return True
        return False

    def _append_conversation_history(
        self,
        npc_id: str,
        session: ConversationSession,
        transcript: str,
    ) -> None:
        partner = next(p for p in session.participants if p != npc_id)
        self.history_for(npc_id).append(
            speaker="town_conversation",
            content=transcript,
            metadata={
                "source": "town_conversation",
                "conversation_session_id": session.id,
                "partner_npc_id": partner,
                "location_id": session.location_id,
                "clock_minute": session.started_minute,
                "close_reason": session.close_reason,
            },
        )

    def _conversation_transcript(self, session: ConversationSession) -> str:
        return "\n".join(f"{turn.speaker_id}: {turn.text}" for turn in session.turns)

    def _conversation_summary(self, session: ConversationSession) -> str:
        participants = " 和 ".join(session.participants)
        topic = f"，话题：{session.topic}" if session.topic else ""
        return (
            f"{participants} 在 {session.location_id} 进行了一段对话"
            f"{topic}，共 {len(session.turns)} 句，结束原因：{session.close_reason or 'unknown'}。"
        )

    def _participant_conversation_impression(
        self,
        npc_id: str,
        partner_id: str,
        session: ConversationSession,
    ) -> str:
        own_lines = [
            _clean_conversation_text(turn.text)
            for turn in session.turns
            if turn.speaker_id == npc_id
        ]
        partner_lines = [
            _clean_conversation_text(turn.text)
            for turn in session.turns
            if turn.speaker_id == partner_id
        ]
        own_lines = [line for line in own_lines if line]
        partner_lines = [line for line in partner_lines if line]
        own_text = "；".join(own_lines[-2:]) if own_lines else "没有说太多"
        partner_text = "；".join(partner_lines[-2:]) if partner_lines else "没有回应太多"
        return (
            f"我和 {partner_id} 在 {session.location_id} 聊过"
            f"{('关于' + session.topic) if session.topic else '一会儿'}。"
            f"我提到：{own_text}。{partner_id} 提到：{partner_text}。"
        )

    def _relationship_summary(
        self,
        npc_id: str,
        partner_id: str,
        session: ConversationSession,
    ) -> str:
        unresolved = self._conversation_unresolved_topics(session)
        followups = self._conversation_follow_up_intentions(npc_id, partner_id, session)
        parts = [
            f"{npc_id} 与 {partner_id} 最近在 {session.location_id} 围绕"
            f"“{session.topic or '日常交流'}”有过对话"
        ]
        if unresolved:
            parts.append("未解决：" + "；".join(unresolved))
        if followups:
            parts.append("后续意图：" + "；".join(followups))
        return "。".join(parts) + "。"

    def _conversation_unresolved_topics(self, session: ConversationSession) -> list[str]:
        topics: list[str] = []
        if session.close_reason in {"max_turns", "repeat_detected", "empty_conversation"}:
            topics.append(session.topic or "继续完成上次未收束的对话")
        question_lines = [
            turn.text
            for turn in session.turns
            if _looks_like_open_question(turn.text)
        ]
        if question_lines:
            topics.append(_compact_topic(question_lines[-1]))
        return _dedupe_strings(topics)[:3]

    def _conversation_follow_up_intentions(
        self,
        npc_id: str,
        partner_id: str,
        session: ConversationSession,
    ) -> list[str]:
        intentions: list[str] = []
        unresolved = self._conversation_unresolved_topics(session)
        if unresolved:
            intentions.append(f"跟进与 {partner_id} 的话题：{unresolved[0]}")
        if session.topic:
            topic = _compact_topic(session.topic)
            if any(marker in session.topic for marker in ("推荐", "约", "帮", "需要", "确认")):
                intentions.append(f"安排时间处理与 {partner_id} 的{topic}")
        return _dedupe_strings(intentions)[:3]

    def _conversation_duration_minutes(self, session: ConversationSession) -> int:
        total_chars = sum(len(turn.text) for turn in session.turns)
        return max(
            1,
            min(MAX_CONVERSATION_MINUTES, math.ceil(total_chars / CONVERSATION_CHARS_PER_MINUTE)),
        )

    def _conversation_pair_key(self, npc_a: str, npc_b: str) -> str:
        return "|".join(sorted((npc_a, npc_b)))

    def _recent_conversation_summaries(
        self,
        npc_id: str,
        *,
        partner_npc_id: str | None = None,
    ) -> list[str]:
        recent: list[str] = []
        for session in self.state.conversation_sessions.values():
            if npc_id not in session.participants or session.status != "closed":
                continue
            if session.ended_minute is None:
                continue
            partner = next(p for p in session.participants if p != npc_id)
            if partner_npc_id is not None and partner != partner_npc_id:
                continue
            recent.append(
                f"{partner}: {_minute_label(session.started_minute)} "
                f"{session.topic or '日常对话'}，结束={session.close_reason or 'unknown'}"
            )
        return recent[-3:]

    def _relationship_impressions(self, npc_id: str, partner_npc_id: str) -> list[str]:
        return [
            record.content
            for record in self.memory_for(npc_id).grep(
                "",
                category="impression",
                metadata_filters={
                    "source": "town_conversation",
                    "partner_npc_id": partner_npc_id,
                },
                k=3,
            )
        ][-3:]

    def _current_action_dict(self, npc_id: str) -> dict[str, object]:
        action = self.state.current_action_for(npc_id)
        if action is None:
            raise KeyError(npc_id)
        return {
            "action_type": action.action_type,
            "location_id": action.location_id,
            "start_minute": action.start_minute,
            "duration_minutes": action.duration_minutes,
            "end_minute": action.end_minute,
            "start_time": _minute_label(action.start_minute),
            "end_time": _minute_label(action.end_minute),
            "status": action.status,
            "lifecycle_state": action.lifecycle_state,
            "effect_model": action.effect_model,
            "occupancy_model": action.occupancy_model,
            "effect_applied": action.effect_applied,
            "failure_reason": action.failure_reason,
            "interrupted_reason": action.interrupted_reason,
            "finalized_minute": action.finalized_minute,
            "summary": action.summary,
        }

    def _resident_snapshot(self, npc_id: str, *, minute: int) -> dict[str, object]:
        resident = self.state.resident_for(npc_id)
        if resident is None:
            raise KeyError(npc_id)
        current_action = (
            self._current_action_dict(npc_id)
            if self.state.current_action_for(npc_id) is not None
            else None
        )
        current_schedule = self.state.current_schedule_segment(npc_id, minute=minute)
        day_plan = resident.day_plans.get(self.state.clock.day)
        return {
            "location_id": self.state.location_id_for(npc_id),
            "schedule_day": resident.schedule_day,
            "currently": resident.scratch.currently,
            "day_plan": _resident_day_plan_dict(day_plan),
            "current_action": current_action,
            "current_schedule": _schedule_dict(current_schedule),
            "schedule": [
                {
                    **_full_schedule_dict(segment),
                    "completed": self.state.is_schedule_segment_complete(npc_id, segment),
                    "state": self.schedule_segment_state(npc_id, segment, minute=minute),
                }
                for segment in self.state.schedule_for(npc_id)
            ],
            "completed_schedule_segments": [
                {
                    "day": item.day,
                    "start_minute": item.start_minute,
                    "location_id": item.location_id,
                    "note": item.note,
                    "completion_type": item.completion_type,
                    "matched_action_id": item.matched_action_id,
                    "matched_action_type": item.matched_action_type,
                    "matching_reason": item.matching_reason,
                }
                for item in self.state.completed_schedule_segments.get(npc_id, [])
            ],
            "satisfied_schedule_segments": [
                _schedule_satisfaction_dict(item)
                for item in self.state.satisfied_schedule_segments.get(npc_id, [])
            ],
            "schedule_completed": (
                self.state.is_schedule_segment_complete(npc_id, current_schedule)
                if current_schedule is not None
                else False
            ),
            "poignancy": resident.poignancy,
            "reflection_due": self.reflection_due_for(npc_id),
            "reflection_evidence_count": len(resident.reflection_evidence),
        }

    def _conversation_session_snapshot(
        self,
        session: ConversationSession,
    ) -> dict[str, object]:
        return {
            "id": session.id,
            "participants": list(session.participants),
            "status": session.status,
            "location_id": session.location_id,
            "topic_or_reason": session.topic,
            "turn_count": len(session.turns),
            "started_minute": session.started_minute,
            "ended_minute": session.ended_minute,
            "close_reason": session.close_reason,
        }

    def _schedule_progress_summary(
        self,
        npc_id: str,
        schedule: ScheduleSegment | None,
    ) -> str:
        return schedule_progress_summary(
            npc_id=npc_id,
            schedule=schedule,
            action_log=self.action_log,
        )

    def _schedule_completion_hint(
        self,
        npc_id: str,
        schedule: ScheduleSegment | None,
        progress_summary: str,
    ) -> str:
        if schedule is None:
            return "当前没有日程段；根据本地事件选择具体行动或等待。"
        if self.state.is_schedule_segment_complete(npc_id, schedule):
            return "当前日程段已经完成；除非有待处理直接事件，不需要继续行动。"
        if schedule.completion_policy == "explicit":
            return "当前日程段使用 explicit policy；证据充分、被阻塞或无法继续时可调用 complete_current_schedule。"
        if self.state.is_schedule_segment_satisfied(npc_id, schedule):
            return "当前日程段已有最终行动满足证据；避免重复同类行动，等待引擎按策略推进。"

        successful_actions: list[dict[str, object]] = []
        for item in self.action_log:
            minute = item.get("minute")
            if (
                item.get("npc_id") == npc_id
                and item.get("status") == "succeeded"
                and isinstance(minute, int)
                and schedule.start_minute <= minute < schedule.end_minute
                and item.get("action_type") not in {"observe"}
            ):
                successful_actions.append(item)
        action_count = len(successful_actions)
        remaining = max(0, schedule.end_minute - self.state.clock.minute)
        intent = schedule.intent
        if action_count == 0:
            return (
                "先选择与当前日程最相关的对象或出口行动；"
                "不要只输出叙述或只观察。"
            )
        if any(word in intent for word in ("准备", "整理")) and action_count >= 3:
            return (
                f"你已经为“{intent}”完成多次相关行动。"
                "如果柜台/书车/相关对象已经处理到位，不要继续重复同类交互。"
            )
        if any(word in intent for word in ("吃", "买", "取", "送")) and action_count >= 1:
            return (
                f"你已经执行过与“{intent}”直接相关的行动。"
                "如果物品已取得、交易已完成或需求已满足，不要继续重复同类交互。"
            )
        if remaining <= self.state.clock.stride_minutes:
            return "当前日程即将结束；选择最直接的具体行动或短暂等待引擎推进。"
        return (
            progress_summary
            + "。继续行动前检查语义是否重复；普通日程由最终行动证据自动推进。"
        )

    def _validate_and_repair_schedule(
        self,
        npc_id: str,
        schedule: list[ScheduleSegment],
        *,
        day: int,
        start_minute: int,
        end_minute: int,
    ) -> tuple[list[ScheduleSegment], dict[str, object]]:
        warnings: list[str] = []
        repaired: list[ScheduleSegment] = []
        fallback_location = self.state.location_id_for(npc_id) or next(iter(self.state.locations))
        next_start = start_minute
        for raw in sorted(schedule, key=lambda segment: segment.start_minute):
            if raw.npc_id != npc_id:
                warnings.append("schedule_npc_mismatch")
                continue
            location_id = raw.location_id
            if location_id not in self.state.locations:
                warnings.append("unknown_schedule_location")
                location_id = fallback_location
            duration = max(1, int(raw.duration_minutes))
            segment_start = max(start_minute, int(raw.start_minute), next_start)
            if segment_start >= end_minute:
                warnings.append("schedule_segment_out_of_bounds")
                continue
            if segment_start != raw.start_minute:
                warnings.append("overlap_or_bounds_repaired")
            duration = min(duration, end_minute - segment_start)
            repaired.append(
                ScheduleSegment(
                    npc_id=npc_id,
                    start_minute=segment_start,
                    duration_minutes=duration,
                    location_id=location_id,
                    intent=raw.intent or "处理当天事项",
                    subtasks=list(raw.subtasks),
                    completion_tags=list(raw.completion_tags),
                    day=day,
                )
            )
            next_start = segment_start + duration

        if not repaired:
            warnings.append("deterministic_fallback_schedule")
            repaired.append(
                ScheduleSegment(
                    npc_id=npc_id,
                    start_minute=start_minute,
                    duration_minutes=max(1, min(60, end_minute - start_minute)),
                    location_id=fallback_location,
                    intent="整理当天事项",
                    day=day,
                )
            )
        repaired = self._repair_first_segment_reachability(
            npc_id,
            repaired,
            warnings=warnings,
            day=day,
            start_minute=start_minute,
            end_minute=end_minute,
            fallback_location=fallback_location,
        )
        if start_minute == 0 and end_minute >= 24 * 60:
            repaired = self._repair_full_day_lifecycle_schedule(
                npc_id,
                repaired,
                warnings=warnings,
                day=day,
                start_minute=start_minute,
                end_minute=end_minute,
            )
        return repaired, {
            "ok": not warnings,
            "warnings": warnings,
            "segment_count": len(repaired),
        }

    def _repair_full_day_lifecycle_schedule(
        self,
        npc_id: str,
        schedule: list[ScheduleSegment],
        *,
        warnings: list[str],
        day: int,
        start_minute: int,
        end_minute: int,
    ) -> list[ScheduleSegment]:
        resident = self.state.residents[npc_id]
        sleep_location = resident.sleep_location_id or resident.home_location_id
        if not sleep_location or sleep_location not in self.state.locations:
            warnings.append("missing_home_or_sleep_location")
            return schedule
        repaired = sorted(schedule, key=lambda item: item.start_minute)
        if not any(self._is_sleep_or_rest_segment(npc_id, segment) for segment in repaired):
            warnings.append("missing_sleep_segment_repaired")
            sleep_start = (
                resident.default_sleep_window[0]
                if resident.default_sleep_window is not None
                else max(start_minute, end_minute - 120)
            )
            repaired.append(
                ScheduleSegment(
                    npc_id=npc_id,
                    start_minute=max(start_minute, min(sleep_start, end_minute - 60)),
                    duration_minutes=max(1, end_minute - max(start_minute, min(sleep_start, end_minute - 60))),
                    location_id=sleep_location,
                    intent="回家休息并睡觉",
                    subtasks=["lifecycle:sleep", "repair:missing_sleep"],
                    day=day,
                )
            )
        repaired = sorted(repaired, key=lambda item: item.start_minute)
        first = repaired[0]
        wake = (
            resident.default_wake_window[0]
            if resident.default_wake_window is not None
            else DEFAULT_DAY_START_MINUTE
        )
        if first.start_minute > start_minute:
            warnings.append("pre_wake_sleep_segment_repaired")
            repaired.insert(
                0,
                ScheduleSegment(
                    npc_id=npc_id,
                    start_minute=start_minute,
                    duration_minutes=max(1, min(first.start_minute, wake) - start_minute),
                    location_id=sleep_location,
                    intent="睡觉直到起床",
                    subtasks=["lifecycle:sleep", "repair:pre_wake_sleep"],
                    day=day,
                ),
            )
        final_sleep = max(
            (segment for segment in repaired if self._is_sleep_or_rest_segment(npc_id, segment)),
            key=lambda item: item.start_minute,
        )
        before_sleep = [
            segment for segment in repaired if segment.end_minute <= final_sleep.start_minute
        ]
        previous_location = before_sleep[-1].location_id if before_sleep else sleep_location
        if previous_location != sleep_location:
            travel = self._shortest_travel_minutes(previous_location, sleep_location)
            if travel is None:
                warnings.append("return_home_unreachable")
            elif final_sleep.start_minute < end_minute and final_sleep.start_minute - travel >= start_minute:
                return_start = final_sleep.start_minute - travel
                if not any(
                    segment.location_id == sleep_location
                    and segment.end_minute <= final_sleep.start_minute
                    and segment.start_minute >= return_start
                    for segment in repaired
                ):
                    warnings.append("return_home_segment_repaired")
                    repaired.append(
                        ScheduleSegment(
                            npc_id=npc_id,
                            start_minute=return_start,
                            duration_minutes=max(1, travel),
                            location_id=sleep_location,
                            intent="返回家中准备睡觉",
                            subtasks=["lifecycle:return_home", "repair:return_home"],
                            day=day,
                        )
                    )
        return self._normalize_repaired_schedule(npc_id, repaired, day=day, start_minute=start_minute, end_minute=end_minute)

    def _normalize_repaired_schedule(
        self,
        npc_id: str,
        schedule: list[ScheduleSegment],
        *,
        day: int,
        start_minute: int,
        end_minute: int,
    ) -> list[ScheduleSegment]:
        normalized: list[ScheduleSegment] = []
        next_start = start_minute
        for raw in sorted(schedule, key=lambda item: item.start_minute):
            segment_start = max(start_minute, raw.start_minute, next_start)
            if segment_start >= end_minute:
                continue
            duration = max(1, min(raw.duration_minutes, end_minute - segment_start))
            normalized.append(
                ScheduleSegment(
                    npc_id=npc_id,
                    start_minute=segment_start,
                    duration_minutes=duration,
                    location_id=raw.location_id,
                    intent=raw.intent,
                    subtasks=list(raw.subtasks),
                    completion_tags=list(raw.completion_tags),
                    day=day,
                )
            )
            next_start = segment_start + duration
        return normalized

    def _is_sleep_or_rest_segment(self, npc_id: str, segment: ScheduleSegment) -> bool:
        resident = self.state.residents[npc_id]
        lifecycle_location = segment.location_id in {
            resident.home_location_id,
            resident.sleep_location_id,
        }
        text = f"{segment.intent} {' '.join(segment.subtasks)}".lower()
        return lifecycle_location and any(
            token in text for token in ("sleep", "rest", "睡", "休息", "入睡")
        )

    def _repair_first_segment_reachability(
        self,
        npc_id: str,
        schedule: list[ScheduleSegment],
        *,
        warnings: list[str],
        day: int,
        start_minute: int,
        end_minute: int,
        fallback_location: str,
    ) -> list[ScheduleSegment]:
        if not schedule:
            return schedule
        current_location_id = self.state.location_id_for(npc_id) or fallback_location
        first = schedule[0]
        if current_location_id == first.location_id:
            return schedule
        travel_minutes = self._shortest_travel_minutes(current_location_id, first.location_id)
        if travel_minutes is None:
            warnings.append("first_segment_unreachable_repaired")
            return [
                ScheduleSegment(
                    npc_id=npc_id,
                    start_minute=start_minute,
                    duration_minutes=max(1, min(first.duration_minutes, end_minute - start_minute)),
                    location_id=current_location_id,
                    intent=f"从当前位置过渡：{first.intent}",
                    subtasks=list(first.subtasks),
                    completion_tags=list(first.completion_tags),
                    day=day,
                ),
                *[
                    segment
                    for segment in schedule[1:]
                    if segment.start_minute < end_minute
                ],
            ]
        earliest_arrival = start_minute + travel_minutes
        if first.start_minute >= earliest_arrival:
            return schedule
        warnings.append("first_segment_requires_travel_repair")
        if earliest_arrival >= end_minute:
            warnings.append("deterministic_fallback_schedule")
            return [
                ScheduleSegment(
                    npc_id=npc_id,
                    start_minute=start_minute,
                    duration_minutes=max(1, end_minute - start_minute),
                    location_id=current_location_id,
                    intent="整理当前位置事项",
                    day=day,
                )
            ]

        shifted: list[ScheduleSegment] = []
        next_start = earliest_arrival
        for raw in schedule:
            segment_start = max(raw.start_minute, next_start)
            if segment_start >= end_minute:
                warnings.append("schedule_segment_out_of_bounds")
                continue
            duration = min(raw.duration_minutes, end_minute - segment_start)
            shifted.append(
                ScheduleSegment(
                    npc_id=npc_id,
                    start_minute=segment_start,
                    duration_minutes=max(1, duration),
                    location_id=raw.location_id,
                    intent=raw.intent,
                    subtasks=list(raw.subtasks),
                    completion_tags=list(raw.completion_tags),
                    day=day,
                )
            )
            next_start = segment_start + duration
        return shifted or [
            ScheduleSegment(
                npc_id=npc_id,
                start_minute=start_minute,
                duration_minutes=max(1, end_minute - start_minute),
                location_id=current_location_id,
                intent="整理当前位置事项",
                day=day,
            )
        ]

    def _shortest_travel_minutes(self, origin_id: str, destination_id: str) -> int | None:
        if origin_id == destination_id:
            return 0
        if origin_id not in self.state.locations or destination_id not in self.state.locations:
            return None
        frontier: list[tuple[int, str]] = [(0, origin_id)]
        best: dict[str, int] = {origin_id: 0}
        while frontier:
            frontier.sort(key=lambda item: item[0])
            travel_so_far, location_id = frontier.pop(0)
            if location_id == destination_id:
                return travel_so_far
            location = self.state.locations.get(location_id)
            if location is None:
                continue
            for exit_id in location.exits:
                if exit_id not in self.state.locations:
                    continue
                next_travel = travel_so_far + location.exit_travel_minutes.get(
                    exit_id,
                    DEFAULT_MOVE_MINUTES,
                )
                if next_travel < best.get(exit_id, 10**9):
                    best[exit_id] = next_travel
                    frontier.append((next_travel, exit_id))
        return None

    def _shortest_route(self, origin_id: str, destination_id: str) -> list[str] | None:
        if origin_id == destination_id:
            return [origin_id]
        if origin_id not in self.state.locations or destination_id not in self.state.locations:
            return None
        frontier: list[tuple[int, str, list[str]]] = [(0, origin_id, [origin_id])]
        best: dict[str, int] = {origin_id: 0}
        while frontier:
            frontier.sort(key=lambda item: (item[0], item[1]))
            travel_so_far, location_id, route = frontier.pop(0)
            if location_id == destination_id:
                return route
            location = self.state.locations.get(location_id)
            if location is None:
                continue
            for exit_id in location.exits:
                if exit_id not in self.state.locations:
                    continue
                next_travel = travel_so_far + location.exit_travel_minutes.get(
                    exit_id,
                    DEFAULT_MOVE_MINUTES,
                )
                if next_travel < best.get(exit_id, 10**9):
                    best[exit_id] = next_travel
                    frontier.append((next_travel, exit_id, [*route, exit_id]))
        return None

    def _resolve_move_destination(
        self,
        npc_id: str,
        requested_destination_id: str,
    ) -> tuple[str | None, list[str] | None]:
        location = self.state.location_for(npc_id)
        if location is None or requested_destination_id not in self.state.locations:
            return requested_destination_id, None
        if requested_destination_id in location.exits or requested_destination_id == location.id:
            return requested_destination_id, [location.id, requested_destination_id]
        route = self._shortest_route(location.id, requested_destination_id)
        if route is None or len(route) < 2:
            return requested_destination_id, route
        return route[1], route

    def _assert_schedule_valid(
        self,
        npc_id: str,
        schedule: list[ScheduleSegment],
    ) -> None:
        previous: ScheduleSegment | None = None
        for segment in sorted(schedule, key=lambda item: item.start_minute):
            if segment.npc_id != npc_id:
                raise ValueError("schedule_npc_mismatch")
            if segment.location_id not in self.state.locations:
                raise ValueError("unknown_schedule_location")
            if segment.duration_minutes <= 0:
                raise ValueError("invalid_schedule_plan")
            if previous is not None and previous.end_minute > segment.start_minute:
                raise ValueError("overlapping_schedule_segments")
            previous = segment

    def _schedule_is_valid(
        self,
        npc_id: str,
        schedule: list[ScheduleSegment],
    ) -> bool:
        try:
            self._assert_schedule_valid(npc_id, schedule)
        except ValueError:
            return False
        return True

    def _recoverable_overdue_segment(self, npc_id: str) -> ScheduleSegment | None:
        overdue = [
            segment
            for segment in self.state.schedule_for(npc_id)
            if segment.end_minute <= self.state.clock.minute
            and not self.state.is_schedule_segment_complete(npc_id, segment)
        ]
        if not overdue:
            return None
        return max(overdue, key=lambda segment: segment.end_minute)

    def _segment_has_revision_evidence(
        self,
        npc_id: str,
        segment: ScheduleSegment,
    ) -> bool:
        return any(
            item.get("npc_id") == npc_id
            and item.get("stage") == "schedule_revision"
            and _revision_mentions_segment(item, segment)
            for item in self.planning_log
        )

    def _segment_has_drift_evidence(
        self,
        npc_id: str,
        segment: ScheduleSegment,
    ) -> bool:
        return any(
            item.get("npc_id") == npc_id
            and item.get("guard_type") == "schedule_drift"
            and item.get("details", {}).get("segment_start_minute")
            == segment.start_minute
            for item in self.loop_guard_events
            if isinstance(item.get("details"), dict)
        )

    def _segment_has_interruption_evidence(
        self,
        npc_id: str,
        segment: ScheduleSegment,
    ) -> bool:
        return any(
            item.get("npc_id") == npc_id
            and item.get("lifecycle_state") == "interrupted"
            and _interruption_overlaps_segment(item, segment)
            for item in self.action_log
        )

    def _has_schedule_evidence(
        self,
        npc_id: str,
        stage: str,
        segment: ScheduleSegment,
        *,
        day: int,
    ) -> bool:
        return any(
            item.get("npc_id") == npc_id
            and item.get("day") == day
            and item.get("stage") == stage
            and isinstance(item.get("segment"), dict)
            and item["segment"].get("start_minute") == segment.start_minute
            and item["segment"].get("location_id") == segment.location_id
            for item in self.planning_log
        )

    def _record_planning_checkpoint(
        self,
        npc_id: str,
        *,
        day: int,
        stage: str,
        payload: dict[str, object],
    ) -> None:
        self.planning_log.append(
            {
                "day": day,
                "minute": self.state.clock.minute,
                "time": self.state.clock.label(),
                "npc_id": npc_id,
                "stage": stage,
                **payload,
            }
        )

    def _detect_loop_guards(self, npc_id: str) -> None:
        recent = [
            item
            for item in self.action_log
            if item.get("npc_id") == npc_id and item.get("day") == self.state.clock.day
        ][-LOOP_GUARD_WINDOW:]
        if len(recent) >= 3:
            last_three = recent[-3:]
            failed = [item for item in last_three if item.get("status") == "failed"]
            if len(failed) == 3:
                action_type = str(failed[-1].get("action_type"))
                reasons: set[str] = set()
                for item in failed:
                    facts = item.get("facts")
                    if isinstance(facts, dict) and facts.get("reason"):
                        reasons.add(str(facts["reason"]))
                    else:
                        reasons.add(str(item.get("status")))
                targets = {_loop_guard_target(item) for item in failed}
                if action_type in {"move_to", "move", "interact_with", "interact"} and len(targets) == 1:
                    self._record_loop_guard_event(
                        npc_id,
                        "repeated_failed_action",
                        f"连续失败的 {action_type}: {next(iter(targets))}",
                        {"action_type": action_type, "reasons": sorted(reasons), "target": next(iter(targets))},
                    )
            action_types = [str(item.get("action_type")) for item in last_three]
            if len(set(action_types)) == 1 and action_types[-1] in {"wait", "speak_to", "start_conversation", "talk_to"}:
                self._record_loop_guard_event(
                    npc_id,
                    "repeated_low_value_action",
                    f"连续执行 {action_types[-1]}，需要检查是否空转。",
                    {"action_type": action_types[-1]},
                )

        schedule = self.state.current_schedule_segment(npc_id)
        location_id = self.state.location_id_for(npc_id)
        if (
            schedule is not None
            and location_id is not None
            and location_id != schedule.location_id
            and self.state.clock.minute - schedule.start_minute >= self.state.clock.stride_minutes * 3
            and not self._schedule_drift_exempt(npc_id, schedule)
        ):
            blacklist_evidence = self._schedule_drift_blacklist_evidence(
                npc_id,
                schedule,
                location_id,
            )
            self._record_loop_guard_event(
                npc_id,
                "schedule_drift",
                f"{npc_id} 长时间停留在 {location_id}，偏离日程目标 {schedule.location_id}。",
                {
                    "location_id": location_id,
                    "schedule_location_id": schedule.location_id,
                    "segment_start_minute": schedule.start_minute,
                    "blacklist_evidence": blacklist_evidence,
                },
            )

    def _schedule_drift_blacklist_evidence(
        self,
        npc_id: str,
        schedule: ScheduleSegment,
        location_id: str,
    ) -> list[dict[str, object]]:
        evidence: list[dict[str, object]] = []
        action = self.state.current_action_for(npc_id)
        if action is None:
            evidence.append(
                {
                    "kind": "no_current_action_away_from_goal",
                    "location_id": location_id,
                    "minutes_away": self.state.clock.minute - schedule.start_minute,
                }
            )
        elif action.action_type == "wait" and action.location_id != schedule.location_id:
            evidence.append(
                {
                    "kind": "wait_away_from_goal",
                    "location_id": action.location_id,
                    "action_start_minute": action.start_minute,
                    "action_end_minute": action.end_minute,
                }
            )

        recent_actions = [
            item
            for item in self.action_log
            if item.get("npc_id") == npc_id and item.get("day") == self.state.clock.day
        ][-LOOP_GUARD_WINDOW:]
        away_actions = [
            item
            for item in recent_actions
            if item.get("location_id") not in {None, schedule.location_id}
        ]
        if len(away_actions) >= 2:
            evidence.append(
                {
                    "kind": "repeated_non_schedule_locations",
                    "count": len(away_actions),
                    "location_ids": sorted(
                        {
                            str(item.get("location_id"))
                            for item in away_actions
                            if item.get("location_id") is not None
                        }
                    ),
                }
            )

        wait_away = [
            item
            for item in away_actions
            if item.get("action_type") == "wait" and item.get("status") == "succeeded"
        ]
        if len(wait_away) >= 2:
            evidence.append({"kind": "repeated_wait_away_from_goal", "count": len(wait_away)})

        failed_moves = [
            item
            for item in away_actions
            if item.get("action_type") in {"move_to", "move"}
            and item.get("status") == "failed"
            and self._action_destination(item) != schedule.location_id
        ]
        if failed_moves:
            evidence.append(
                {
                    "kind": "failed_moves_not_approaching_goal",
                    "count": len(failed_moves),
                    "destinations": sorted(
                        {
                            str(destination)
                            for item in failed_moves
                            if (destination := self._action_destination(item)) is not None
                        }
                    ),
                }
            )

        free_away = [
            item
            for item in self.free_action_log
            if item.get("npc_id") == npc_id
            and item.get("day") == self.state.clock.day
            and item.get("location_id") != schedule.location_id
            and item.get("action_type") in {"observe", "inspect_affordances"}
        ][-LOOP_GUARD_WINDOW:]
        if len(free_away) >= 2:
            evidence.append(
                {
                    "kind": "repeated_free_observation_away_from_goal",
                    "count": len(free_away),
                    "action_types": [
                        str(item.get("action_type"))
                        for item in free_away
                    ],
                }
            )
        return evidence

    def _action_destination(self, action_row: dict[str, object]) -> str | None:
        facts = action_row.get("facts")
        if not isinstance(facts, dict):
            return None
        destination = facts.get("destination_id", facts.get("to"))
        return str(destination) if isinstance(destination, str) and destination else None

    def _schedule_drift_exempt(
        self,
        npc_id: str,
        schedule: ScheduleSegment,
    ) -> bool:
        action = self.state.current_action_for(npc_id)
        if action is not None and action.end_minute > self.state.clock.minute:
            facts = action.metadata.get("facts")
            if isinstance(facts, dict) and facts.get("to") == schedule.location_id:
                return True
            if action.location_id == schedule.location_id:
                return True
        if self.state.active_conversation_for(npc_id) is not None:
            return True
        if self._inboxes.get(npc_id):
            return True
        if any(self._is_significant_event_for(npc_id, event) for event in self.visible_events_for(npc_id)):
            return True
        revision = self._latest_schedule_revision_by_npc.get(npc_id)
        if (
            revision is not None
            and self.state.clock.minute - revision.inserted_segment.start_minute
            < self.state.clock.stride_minutes
        ):
            return True
        return False

    def _record_loop_guard_event(
        self,
        npc_id: str,
        guard_type: str,
        message: str,
        details: dict[str, object],
    ) -> None:
        key = (
            self.state.clock.day,
            npc_id,
            guard_type,
            tuple(sorted((str(k), str(v)) for k, v in details.items())),
        )
        if key in self._loop_guard_keys:
            return
        self._loop_guard_keys.add(key)
        self.loop_guard_events.append(
            {
                "day": self.state.clock.day,
                "minute": self.state.clock.minute,
                "time": self.state.clock.label(),
                "npc_id": npc_id,
                "guard_type": guard_type,
                "message": message,
                "details": details,
            }
        )

    def _recent_loop_guard_events(self, npc_id: str) -> list[dict[str, object]]:
        return [
            event
            for event in self.loop_guard_events
            if event.get("npc_id") == npc_id and event.get("day") == self.state.clock.day
        ][-5:]

    def memory_for(self, npc_id: str) -> MemoryInterface:
        if npc_id not in self._memories:
            self._memories[npc_id] = DefaultMemoryInterface(
                npc_id,
                chroma_client=self._client,
            )
        return self._memories[npc_id]

    def history_for(self, npc_id: str) -> HistoryStore:
        if npc_id not in self._histories:
            self._histories[npc_id] = HistoryStore(
                npc_id,
                self._history_dir / f"{npc_id}.jsonl",
            )
        return self._histories[npc_id]

    def ingest_external(
        self,
        npc_id: str,
        speaker: str,
        content: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        """Record inbound speech or event text into one NPC's JSONL history."""
        location = self.state.location_for(npc_id)
        base_metadata: dict[str, object] = {
            "source": "town_external",
            "location_id": location.id if location is not None else "unknown",
            "clock_minute": self.state.clock.minute,
        }
        base_metadata.update(metadata or {})
        self.history_for(npc_id).append(
            speaker=speaker,
            content=content,
            metadata=base_metadata,
        )

    def _next_available_minute(self, npc_id: str, *, at_minute: int | None = None) -> int:
        action = self.state.current_action_for(npc_id)
        if action is None:
            check_minute = self.state.clock.minute if at_minute is None else at_minute
            segment = self.state.current_schedule_segment(npc_id, minute=check_minute)
            if (
                segment is not None
                and segment.completion_policy == "occupy_until_segment_end"
                and self.state.is_schedule_segment_satisfied(npc_id, segment)
                and not self.state.is_schedule_segment_complete(npc_id, segment)
                and check_minute < segment.end_minute
            ):
                return segment.end_minute
            return check_minute
        return action.end_minute

    def _skip_reason(
        self,
        npc_id: str,
        *,
        at_minute: int,
        next_available: int,
    ) -> str:
        if next_available > at_minute:
            return "action_in_progress"
        segment = self.state.current_schedule_segment(npc_id, at_minute)
        if segment is None:
            return "inactive_schedule_window"
        if self.state.is_schedule_segment_complete(npc_id, segment):
            return "completed_schedule"
        return "no_visible_event"

    def _timed_result(
        self,
        npc_id: str,
        *,
        action_id: str,
        action_type: str,
        status: Literal["succeeded", "failed", "partial", "deferred"],
        observation: str,
        facts: dict[str, object],
        duration_minutes: int,
        reason: str | None = None,
        current_action_status: str | None = None,
        effect_model: str | None = None,
        occupancy_model: str | None = None,
    ) -> ActionResult:
        start_minute = max(self.state.clock.minute, self._next_available_minute(npc_id))
        end_minute = start_minute + duration_minutes
        resolved_effect_model = effect_model or ACTION_EFFECT_MODELS.get(
            action_type, "immediate_effect"
        )
        resolved_occupancy_model = occupancy_model or ACTION_OCCUPANCY_MODELS.get(
            action_type, "duration_occupied"
        )
        timed_facts = {
            **facts,
            "start_minute": start_minute,
            "duration_minutes": duration_minutes,
            "end_minute": end_minute,
            "start_time": _minute_label(start_minute),
            "end_time": _minute_label(end_minute),
            "effect_model": resolved_effect_model,
            "occupancy_model": resolved_occupancy_model,
            "lifecycle_state": (
                "free"
                if resolved_occupancy_model == "instant_free"
                else ("failed" if status == "failed" else "in_progress")
            ),
            "effect_applied": resolved_effect_model == "immediate_effect"
            and status != "failed",
        }
        result = ActionResult(
            action_id=action_id,
            action_type=action_type,
            status=status,
            reason=reason,
            observation=observation,
            facts=timed_facts,
        )
        if resolved_occupancy_model == "duration_occupied":
            self._record_current_action(
                npc_id,
                result,
                start_minute=start_minute,
                duration_minutes=duration_minutes,
                current_action_status=current_action_status,
                effect_model=resolved_effect_model,
                occupancy_model=resolved_occupancy_model,
            )
        return result

    def _record_current_action(
        self,
        npc_id: str,
        result: ActionResult,
        *,
        start_minute: int,
        duration_minutes: int,
        current_action_status: str | None = None,
        effect_model: str,
        occupancy_model: str,
    ) -> None:
        location = self.state.location_for(npc_id)
        self.state.set_current_action(
            npc_id,
            CurrentAction(
                npc_id=npc_id,
                action_type=result.action_type,
                location_id=location.id if location is not None else "unknown",
                start_minute=start_minute,
                duration_minutes=duration_minutes,
                status=current_action_status or result.status,
                summary=result.observation,
                lifecycle_state="failed" if result.status == "failed" else "in_progress",
                effect_model=effect_model,
                occupancy_model=occupancy_model,
                effect_applied=effect_model == "immediate_effect" and result.status != "failed",
                failure_reason=result.reason if result.status == "failed" else None,
                metadata={
                    "action_id": result.action_id,
                    "result_status": result.status,
                    "facts": dict(result.facts),
                },
            ),
        )

    def _travel_minutes(self, npc_id: str, destination_id: str) -> int:
        location = self.state.location_for(npc_id)
        if location is None:
            return DEFAULT_FAILED_ACTION_MINUTES
        return location.exit_travel_minutes.get(destination_id, DEFAULT_MOVE_MINUTES)

    def _speak_minutes(self, text: str) -> int:
        return max(1, min(MAX_SPEAK_MINUTES, math.ceil(len(text) / SPEAK_CHARS_PER_MINUTE)))

    def _move_result_to_action_result(
        self,
        action: ActionRequest,
        result: MoveResult,
        *,
        travel_minutes: int,
        requested_destination_id: str | None = None,
        route: list[str] | None = None,
    ) -> ActionResult:
        requested = requested_destination_id or result.to_location_id
        auto_routed = bool(
            result.ok
            and requested is not None
            and result.to_location_id is not None
            and requested != result.to_location_id
        )
        facts = {
            "npc_id": result.npc_id,
            "from": result.from_location_id,
            "to": result.to_location_id,
            "requested_destination_id": requested,
            "actual_destination_id": result.to_location_id,
            "route": route or [],
            "auto_routed": auto_routed,
            "reachable": result.reachable,
        }
        if result.ok:
            return self._timed_result(
                result.npc_id,
                action_id=action.action_id,
                action_type=action.type,
                status="succeeded",
                observation=(
                    f"{result.npc_id} 已从 {result.from_location_id} "
                    f"移动到 {result.to_location_id}。"
                ),
                facts=facts,
                duration_minutes=result.travel_minutes or travel_minutes,
            )
        return self._timed_result(
            result.npc_id,
            action_id=action.action_id,
            action_type=action.type,
            status="failed",
            reason=result.reason,
            observation=(
                f"{result.npc_id} 无法从 {result.from_location_id} "
                f"移动到 {result.to_location_id}。"
            ),
            facts=facts,
            duration_minutes=DEFAULT_FAILED_ACTION_MINUTES,
        )

    def _activation_event(
        self,
        npc_id: str,
        pending_events: list[TownEvent],
    ) -> str | None:
        if pending_events:
            self.event_bus.mark_seen(npc_id, (event.id for event in pending_events))
            return "待处理小镇事件：" + "; ".join(event.summary for event in pending_events)

        significant_events = self.event_bus.unseen_visible_events(
            npc_id,
            self.visible_events_for(npc_id),
            should_activate=lambda event: self._is_significant_event_for(npc_id, event),
        )
        if significant_events:
            for event in significant_events:
                self.revise_schedule_for_event(
                    npc_id,
                    event,
                    reason=self._significant_event_reason(npc_id, event),
                )
            self.event_bus.mark_seen(npc_id, (event.id for event in significant_events))
            return (
                "你注意到重要本地事件："
                + "; ".join(event.summary for event in significant_events)
            )

        segment = self.state.current_schedule_segment(npc_id)
        if segment is not None and not self.state.is_schedule_segment_complete(npc_id, segment):
            return (
                f"当前日程段：{_minute_label(segment.start_minute)}-"
                f"{_minute_label(segment.end_minute)}，目标地点={segment.location_id}，"
                f"目标={segment.intent}。"
            )
        local_events = self.event_bus.unseen_visible_events(
            npc_id,
            self.visible_events_for(npc_id),
            should_activate=lambda event: self._should_activate_for_local_event(
                npc_id,
                event,
            ),
        )
        if local_events:
            self.event_bus.mark_seen(npc_id, (event.id for event in local_events))
            return (
                "你注意到本地事件："
                + "; ".join(event.summary for event in local_events)
            )
        return None

    def _should_activate_for_local_event(self, npc_id: str, event: TownEvent) -> bool:
        if self._is_significant_event_for(npc_id, event):
            return True
        return self._has_active_or_pending_schedule(npc_id)

    def _is_significant_event_for(self, npc_id: str, event: TownEvent) -> bool:
        return npc_id in event.target_ids or event.event_type in SIGNIFICANT_EVENT_TYPES

    def _significant_event_reason(self, npc_id: str, event: TownEvent) -> str:
        if npc_id in event.target_ids:
            return "targeted_event"
        if event.event_type in SIGNIFICANT_EVENT_TYPES:
            return f"{event.event_type}_event"
        return "significant_event"

    def _has_active_or_pending_schedule(self, npc_id: str) -> bool:
        segment = self.state.current_schedule_segment(npc_id)
        return (
            segment is not None
            and not self.state.is_schedule_segment_complete(npc_id, segment)
        )

    def _failed_action(
        self,
        action_type: str,
        reason: str,
        observation: str,
        facts: dict[str, object],
        *,
        action_id: str | None = None,
    ) -> ActionResult:
        result = self._timed_result(
            str(facts.get("npc_id", "unknown")),
            action_id=action_id or ActionRequest(type=action_type).action_id,
            action_type=action_type,
            status="failed",
            reason=reason,
            observation=observation,
            facts={**facts, "reason": reason},
            duration_minutes=DEFAULT_FAILED_ACTION_MINUTES,
        )
        self._record_action_result(str(facts.get("npc_id", "unknown")), result)
        return result

    def _record_action_result(self, npc_id: str, result: ActionResult) -> None:
        location = self.state.location_for(npc_id)
        minute = result.facts.get("start_minute", self.state.clock.minute)
        self.action_log.append(
            {
                "day": self.state.clock.day,
                "time": _minute_label(minute) if isinstance(minute, int) else self.state.clock.label(),
                "minute": minute,
                "end_minute": result.facts.get("end_minute"),
                "npc_id": npc_id,
                "action_type": result.action_type,
                "status": result.status,
                "lifecycle_state": result.facts.get("lifecycle_state"),
                "effect_model": result.facts.get("effect_model"),
                "occupancy_model": result.facts.get("occupancy_model"),
                "effect_applied": result.facts.get("effect_applied"),
                "failure_reason": result.reason,
                "next_available_minute": self._next_available_minute(npc_id),
                "location_id": location.id if location is not None else None,
                "summary": result.observation,
                "facts": result.facts,
            }
        )
        self._detect_loop_guards(npc_id)

    def _infer_schedule_completion_from_action(self, npc_id: str, result: ActionResult) -> ScheduleCompletion | None:
        finalized_action = {
            "npc_id": npc_id,
            "action_id": result.action_id,
            "action_type": result.action_type,
            "status": result.status,
            "start_minute": result.facts.get("start_minute", self.state.clock.minute),
            "end_minute": result.facts.get("end_minute"),
            "location_id": result.facts.get("location_id") or self.state.location_id_for(npc_id),
            "facts": dict(result.facts),
        }
        return self._infer_schedule_completion_from_finalized_action(
            npc_id,
            finalized_action,
            at_minute=self.state.clock.minute,
        )

    def _infer_schedule_completion_from_finalized_action(
        self,
        npc_id: str,
        finalized_action: dict[str, object],
        *,
        at_minute: int,
    ) -> ScheduleCompletion | None:
        result = _FinalizedActionView(finalized_action)
        if result.status != "succeeded" or result.action_type in {
            "complete_current_schedule",
            "finish_schedule_segment",
            "observe",
        }:
            return None
        action_minute = result.facts.get("start_minute", self.state.clock.minute)
        if not isinstance(action_minute, int):
            action_minute = self.state.clock.minute
        action_end_minute = result.facts.get("end_minute", finalized_action.get("end_minute"))
        if not isinstance(action_end_minute, int):
            action_end_minute = action_minute
        if at_minute < action_end_minute:
            return None
        candidates = [
            segment
            for segment in self.state.schedule_for(npc_id)
            if (self.state.clock.day if segment.day is None else segment.day) == self.state.clock.day
            and not self.state.is_schedule_segment_complete(npc_id, segment)
            and segment.completion_policy != "explicit"
            and segment.start_minute <= action_minute < segment.end_minute
        ]
        if not candidates:
            return None
        match: tuple[ScheduleSegment, str] | None = None
        for segment in sorted(candidates, key=lambda item: abs(item.start_minute - action_minute)):
            reason = self._action_completion_reason(npc_id, segment, result)
            if reason:
                match = (segment, reason)
                break
        if match is None:
            return None
        segment, reason = match
        satisfaction = self._record_schedule_satisfaction(
            npc_id,
            segment,
            matched_action_id=result.action_id,
            matched_action_type=result.action_type,
            matching_reason=reason,
            action_end_minute=action_end_minute,
        )
        policy = _normalize_schedule_completion_policy(segment.completion_policy)
        if policy == "occupy_until_segment_end" and at_minute < segment.end_minute:
            self._record_planning_checkpoint(
                npc_id,
                day=self.state.clock.day,
                stage="schedule_satisfied_in_progress",
                payload={
                    "satisfaction": _schedule_satisfaction_dict(satisfaction),
                    "segment": _full_schedule_dict(segment),
                    "action_id": result.action_id,
                    "action_type": result.action_type,
                    "reason": reason,
                },
            )
            return None
        if policy == "min_matching_actions" and satisfaction.match_count < segment.min_matching_actions:
            self._record_planning_checkpoint(
                npc_id,
                day=self.state.clock.day,
                stage="schedule_satisfied_in_progress",
                payload={
                    "satisfaction": _schedule_satisfaction_dict(satisfaction),
                    "segment": _full_schedule_dict(segment),
                    "required_count": segment.min_matching_actions,
                    "reason": reason,
                },
            )
            return None
        completion = self._record_schedule_completion(
            npc_id,
            segment,
            note=f"inferred from {result.action_type}: {reason}",
            completion_type="automatic_action_match",
            matched_action_id=result.action_id,
            matched_action_type=result.action_type,
            matching_reason=reason,
            action_end_minute=action_end_minute,
            completion_policy=policy,
            completion_reason=f"{policy}:{reason}",
        )
        self._record_planning_checkpoint(
            npc_id,
            day=self.state.clock.day,
            stage="schedule_completion_automatic",
            payload={
                "completion": _schedule_completion_dict(completion),
                "segment": _full_schedule_dict(segment),
                "action_id": result.action_id,
                "action_type": result.action_type,
                "action_end_minute": action_end_minute,
                "reason": reason,
            },
        )
        return completion

    def _record_schedule_completion(
        self,
        npc_id: str,
        segment: ScheduleSegment,
        *,
        note: str,
        completion_type: str,
        matched_action_id: str | None = None,
        matched_action_type: str | None = None,
        matching_reason: str = "",
        completion_policy: str | None = None,
        action_end_minute: int | None = None,
        completion_reason: str = "",
    ) -> ScheduleCompletion:
        normalized_type = _normalize_completion_type(completion_type)
        normalized_policy = _normalize_schedule_completion_policy(
            completion_policy or segment.completion_policy
        )
        existing = self.state.completed_schedule_segments.setdefault(npc_id, [])
        for item in existing:
            item_day = self.state.clock.day if item.day is None else item.day
            segment_day = self.state.clock.day if segment.day is None else segment.day
            if item.start_minute == segment.start_minute and item_day == segment_day:
                item.note = note or item.note
                item.day = segment_day
                item.completion_type = normalized_type
                item.matched_action_id = matched_action_id or item.matched_action_id
                item.matched_action_type = matched_action_type or item.matched_action_type
                item.matching_reason = matching_reason or item.matching_reason
                item.completion_policy = normalized_policy
                item.action_end_minute = action_end_minute or item.action_end_minute
                item.completion_reason = completion_reason or item.completion_reason
                return item
        completion = ScheduleCompletion(
            npc_id=npc_id,
            start_minute=segment.start_minute,
            location_id=segment.location_id,
            note=note,
            day=self.state.clock.day if segment.day is None else segment.day,
            completion_type=normalized_type,
            matched_action_id=matched_action_id,
            matched_action_type=matched_action_type,
            matching_reason=matching_reason,
            completion_policy=normalized_policy,
            action_end_minute=action_end_minute,
            completion_reason=completion_reason or matching_reason,
        )
        existing.append(completion)
        return completion

    def _record_schedule_satisfaction(
        self,
        npc_id: str,
        segment: ScheduleSegment,
        *,
        matched_action_id: str | None,
        matched_action_type: str | None,
        matching_reason: str,
        action_end_minute: int | None,
    ) -> ScheduleSatisfaction:
        segment_day = self.state.clock.day if segment.day is None else segment.day
        normalized_policy = _normalize_schedule_completion_policy(segment.completion_policy)
        existing = self.state.satisfied_schedule_segments.setdefault(npc_id, [])
        for item in existing:
            item_day = self.state.clock.day if item.day is None else item.day
            if item.start_minute == segment.start_minute and item_day == segment_day:
                if matched_action_id and matched_action_id != item.matched_action_id:
                    item.match_count += 1
                item.completion_policy = normalized_policy
                item.matched_action_id = matched_action_id or item.matched_action_id
                item.matched_action_type = matched_action_type or item.matched_action_type
                item.matching_reason = matching_reason or item.matching_reason
                item.action_end_minute = action_end_minute or item.action_end_minute
                return item
        satisfaction = ScheduleSatisfaction(
            npc_id=npc_id,
            start_minute=segment.start_minute,
            location_id=segment.location_id,
            day=segment_day,
            completion_policy=normalized_policy,
            matched_action_id=matched_action_id,
            matched_action_type=matched_action_type,
            matching_reason=matching_reason,
            action_end_minute=action_end_minute,
            match_count=1,
        )
        existing.append(satisfaction)
        return satisfaction

    def _explicit_completion_acceptance_reason(
        self,
        npc_id: str,
        segment: ScheduleSegment,
    ) -> tuple[bool, str]:
        if self.state.location_id_for(npc_id) == segment.location_id:
            return True, "at_segment_location"
        for action in reversed(self.action_log[-8:]):
            if action.get("npc_id") != npc_id or action.get("status") != "succeeded":
                continue
            facts = action.get("facts", {})
            if not isinstance(facts, dict):
                continue
            if facts.get("location_id") == segment.location_id:
                return True, "recent_successful_action_at_segment_location"
            if facts.get("to") == segment.location_id or facts.get("actual_destination_id") == segment.location_id:
                return True, "recent_successful_move_to_segment_location"
        return False, "insufficient_completion_evidence"

    def _action_completion_reason(
        self,
        npc_id: str,
        segment: ScheduleSegment,
        result: ActionResult,
    ) -> str:
        facts = result.facts
        if result.action_type == "move_to" and facts.get("to") == segment.location_id:
            if _movement_intent(segment.intent):
                return "movement_reached_segment_location"
        action_location = facts.get("location_id") or self.state.location_id_for(npc_id)
        if action_location != segment.location_id:
            return ""
        if result.action_type in {"speak_to", "start_conversation", "talk_to"}:
            if facts.get("close_reason") in {"empty_turn", "empty_conversation"}:
                return ""
            haystack_parts = [
                str(facts.get("target_npc_id", "")),
                str(facts.get("text", "")),
                str(facts.get("topic_or_reason", "")),
                str(facts.get("close_reason", "")),
            ]
            transcript = facts.get("transcript", [])
            if isinstance(transcript, list):
                for turn in transcript:
                    if isinstance(turn, dict):
                        haystack_parts.extend(
                            [
                                str(turn.get("speaker_id", "")),
                                str(turn.get("listener_id", "")),
                                str(turn.get("text", "")),
                            ]
                        )
            if segment.duration_minutes <= self.state.clock.stride_minutes * 2 and (
                self._action_terms_match_segment(segment, haystack_parts)
                or facts.get("close_reason") in {"natural_close", "max_turns"}
                or result.action_type == "speak_to"
            ):
                return "short_event_or_conversation_segment_satisfied"
        if result.action_type in {"interact_with", "use_affordance"}:
            haystack_parts = [
                str(facts.get("intent", "")),
                str(facts.get("object_id", "")),
                str(facts.get("target_id", "")),
                str(facts.get("affordance_id", "")),
                str(facts.get("affordance_label", "")),
                str(facts.get("event_type", "")),
                str(facts.get("note", "")),
            ]
            aliases = facts.get("affordance_aliases", [])
            if isinstance(aliases, list):
                haystack_parts.extend(str(item) for item in aliases)
            matched_affordances = facts.get("matched_affordances", [])
            if isinstance(matched_affordances, list):
                for item in matched_affordances:
                    if isinstance(item, dict):
                        haystack_parts.extend(
                            [
                                str(item.get("id", "")),
                                str(item.get("label", "")),
                                str(item.get("description", "")),
                                str(item.get("event_type", "")),
                                " ".join(str(alias) for alias in item.get("aliases", []))
                                if isinstance(item.get("aliases"), list)
                                else "",
                            ]
                        )
            if self._action_terms_match_segment(segment, haystack_parts):
                return "affordance_or_target_matched_segment_intent"
        if self._is_sleep_or_rest_segment(npc_id, segment) and result.action_type in {"wait", "use_affordance"}:
            return "rest_or_sleep_action_at_lifecycle_location"
        return ""

    def _action_terms_match_segment(
        self,
        segment: ScheduleSegment,
        haystack_parts: list[str],
    ) -> bool:
        haystack = " ".join(haystack_parts).lower()
        needles = [segment.intent, *segment.subtasks, *segment.completion_tags]
        tokens = [
            token
            for needle in needles
            for token in _semantic_tokens(needle)
        ]
        return any(token and token in haystack for token in tokens)

    def _record_free_action_result(self, npc_id: str, result: ActionResult) -> None:
        location = self.state.location_for(npc_id)
        minute = result.facts.get("start_minute", self.state.clock.minute)
        self.free_action_log.append(
            {
                "day": self.state.clock.day,
                "time": _minute_label(minute) if isinstance(minute, int) else self.state.clock.label(),
                "minute": minute,
                "npc_id": npc_id,
                "action_type": result.action_type,
                "status": result.status,
                "reason": result.reason,
                "location_id": location.id if location is not None else None,
                "facts": result.facts,
            }
        )
        self._detect_loop_guards(npc_id)

    def _event_for_dialogue(self, npc_id: str, location_id: str, dialogue: str) -> TownEvent:
        return TownEvent(
            id=f"event_{len(self.state.events) + 1}",
            minute=self.state.clock.minute,
            location_id=location_id,
            actor_id=npc_id,
            event_type="dialogue",
            summary=dialogue,
        )

    def _render_history(self, npc_id: str) -> str:
        history_path = self._history_dir / f"{npc_id}.jsonl"
        if npc_id not in self._histories and not history_path.exists():
            return ""
        entries = self.history_for(npc_id).read_last(MAX_TOWN_HISTORY_TURNS)
        if not entries:
            return ""
        return "\n".join(f"[{entry.speaker}] {entry.content}" for entry in entries)


def _render_schedule(schedule: ScheduleSegment | None) -> str:
    if schedule is None:
        return "无"
    return (
        f"{_minute_label(schedule.start_minute)}-{_minute_label(schedule.end_minute)} "
        f"地点 {schedule.location_id}：{schedule.intent}"
    )


def _render_relationship_cues(cues: list[dict[str, object]]) -> str:
    if not cues:
        return "无"
    rows: list[str] = []
    for cue in cues:
        partner = str(cue.get("partner_npc_id", "unknown"))
        parts: list[str] = []
        recent = cue.get("recent_conversations")
        if isinstance(recent, list) and recent:
            parts.append("近期对话 " + " / ".join(str(item) for item in recent[:2]))
        impressions = cue.get("impressions")
        if isinstance(impressions, list) and impressions:
            parts.append("印象 " + " / ".join(str(item) for item in impressions[:2]))
        cooldown_time = cue.get("cooldown_until_time")
        if isinstance(cooldown_time, str) and cooldown_time:
            parts.append(f"会话冷却至 {cooldown_time}")
        block_reason = cue.get("conversation_block_reason")
        if isinstance(block_reason, str) and block_reason:
            parts.append(f"当前阻止原因 {block_reason}")
        rows.append(f"{partner}：" + ("；".join(parts) if parts else "暂无"))
    return "；".join(rows)


def _render_planning_evidence(evidence: list[dict[str, object]]) -> str:
    if not evidence:
        return "无"
    rows: list[str] = []
    for item in evidence[:8]:
        metadata = item.get("metadata")
        source = ""
        partner = ""
        if isinstance(metadata, dict):
            source = str(metadata.get("source") or "")
            partner_id = metadata.get("partner_npc_id")
            partner = f", partner={partner_id}" if partner_id else ""
        rows.append(
            f"- [{item.get('category', 'memory')}; source={source}{partner}] "
            f"{item.get('content', '')}"
        )
    return "\n".join(rows)


def _render_relationship_planning_evidence(evidence: list[dict[str, object]]) -> str:
    if not evidence:
        return "无"
    rows: list[str] = []
    for item in evidence[:6]:
        parts = [
            f"partner={item.get('partner_npc_id')}",
            f"topic={item.get('topic_or_reason') or '日常交流'}",
        ]
        unresolved = item.get("unresolved_topics")
        if isinstance(unresolved, list) and unresolved:
            parts.append("unresolved=" + " / ".join(str(value) for value in unresolved[:2]))
        followups = item.get("follow_up_intentions")
        if isinstance(followups, list) and followups:
            parts.append("follow_up=" + " / ".join(str(value) for value in followups[:2]))
        summary = item.get("relationship_summary") or item.get("content", "")
        rows.append("- " + "；".join(parts) + f"；summary={summary}")
    return "\n".join(rows)


def _render_reflection_evidence(evidence: list[ReflectionEvidence]) -> str:
    if not evidence:
        return "无"
    return "\n".join(
        (
            f"- {item.id} [{item.evidence_type}, poignancy={item.poignancy}, "
            f"time={_minute_label(item.clock_minute)}] {item.summary}"
        )
        for item in evidence
    )


def _reflection_evidence_dict(evidence: ReflectionEvidence) -> dict[str, object]:
    return {
        "id": evidence.id,
        "evidence_type": evidence.evidence_type,
        "summary": evidence.summary,
        "poignancy": evidence.poignancy,
        "clock_minute": evidence.clock_minute,
        "metadata": dict(evidence.metadata),
    }


def _has_duplicate_reflection_evidence(
    evidence: list[ReflectionEvidence],
    *,
    evidence_type: str,
    metadata: dict[str, object],
) -> bool:
    dedupe_keys = {
        "event": ("event_id",),
        "conversation": ("conversation_session_id", "partner_npc_id"),
        "schedule": ("segment_start_minute", "location_id"),
    }
    keys = dedupe_keys.get(evidence_type, ())
    if not keys:
        return False
    return any(
        item.evidence_type == evidence_type
        and all(item.metadata.get(key) == metadata.get(key) for key in keys)
        for item in evidence
    )


def _event_poignancy(npc_id: str, event: TownEvent) -> int:
    if event.event_type in SIGNIFICANT_EVENT_TYPES:
        return 5
    if npc_id in event.target_ids:
        return 4
    return 2


def _minute_label(minute: int) -> str:
    hours, minutes = divmod(minute, 60)
    return f"{hours:02d}:{minutes:02d}"


def _strip_speaker_prefix(text: str, speaker_id: str) -> str:
    stripped = text.strip()
    for prefix in (f"{speaker_id}:", f"{speaker_id}："):
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip()
    return stripped


_INTERNAL_CONVERSATION_MARKERS = (
    "conversation is ongoing via",
    "start_conversation",
    "conversation_session",
    "tool_call",
    "tool calls",
    "function call",
    "input_event",
    "available_tools",
    "available_skills",
    "<world_rules>",
    "<situation>",
    "<input_event>",
)


def _clean_conversation_text(text: str) -> str:
    """Drop internal orchestration phrases before persisting dialogue memory."""
    kept: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if any(marker in lowered for marker in _INTERNAL_CONVERSATION_MARKERS):
            continue
        kept.append(line)
    return " ".join(kept).strip()


def _normalize_dialogue(text: str) -> str:
    return "".join(ch for ch in text.lower().strip() if ch.isalnum())


def _looks_like_open_question(text: str) -> bool:
    stripped = text.strip()
    if stripped.endswith(("?", "？")):
        return True
    question_markers = ("吗", "呢", "什么", "怎么", "为什么", "能否", "可以", "要不要")
    return any(marker in stripped[-12:] for marker in question_markers)


def _compact_topic(text: str, *, max_chars: int = 36) -> str:
    compact = " ".join(_clean_conversation_text(text).split())
    if not compact:
        compact = "未命名话题"
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars].rstrip() + "..."


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def _split_metadata_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _planning_influence_intentions(evidence: list[dict[str, object]]) -> list[str]:
    prioritized: list[tuple[int, str]] = []
    for item in evidence:
        category = str(item.get("category", ""))
        content = str(item.get("content", ""))
        metadata = item.get("metadata")
        source = ""
        partner = ""
        followups: list[str] = []
        if isinstance(metadata, dict):
            source = str(metadata.get("source") or "")
            partner = str(metadata.get("partner_npc_id") or "")
            followups = _split_metadata_list(metadata.get("follow_up_intentions"))
        if source == "town_conversation_followup":
            prioritized.append((0, content))
        elif followups:
            prioritized.extend((1, followup) for followup in followups)
        elif source == "town_reflection" or category == "reflection":
            prioritized.append((2, "根据近期反思调整今天的优先事项"))
        elif source == "town_conversation" and partner:
            prioritized.append((3, f"考虑是否需要跟进与 {partner} 的交流"))
    intentions = [item for _, item in sorted(prioritized, key=lambda pair: pair[0])]
    return _dedupe_strings(intentions)[:2]


def _schedule_dict(schedule: ScheduleSegment | None) -> dict[str, object] | None:
    if schedule is None:
        return None
    return {
        "npc_id": schedule.npc_id,
        "day": schedule.day,
        "start_minute": schedule.start_minute,
        "end_minute": schedule.end_minute,
        "location_id": schedule.location_id,
        "intent": schedule.intent,
        "subtasks": list(schedule.subtasks),
        "completion_tags": list(schedule.completion_tags),
        "completion_policy": schedule.completion_policy,
        "min_matching_actions": schedule.min_matching_actions,
        "allow_explicit_override": schedule.allow_explicit_override,
    }


def _schedule_revision_dict(revision: ScheduleRevision | None) -> dict[str, object]:
    if revision is None:
        return {"revised": False}
    return {
        "revised": True,
        "npc_id": revision.npc_id,
        "event_id": revision.event_id,
        "reason": revision.reason,
        "inserted_segment": _schedule_dict(revision.inserted_segment),
    }


def _event_dict(event: TownEvent) -> dict[str, object]:
    return {
        "id": event.id,
        "minute": event.minute,
        "location_id": event.location_id,
        "actor_id": event.actor_id,
        "event_type": event.event_type,
        "summary": event.summary,
        "target_ids": list(event.target_ids),
    }


def _object_dict(obj: TownObject) -> dict[str, object]:
    return {
        "id": obj.id,
        "name": obj.name,
        "location_id": obj.location_id,
        "description": obj.description,
        "interactable": obj.interactable,
        "affordances": [
            _affordance_dict(affordance)
            for affordance in obj.affordances
        ],
    }


def _affordance_dict(affordance: SemanticAffordance) -> dict[str, object]:
    return {
        "id": affordance.id,
        "label": affordance.label,
        "description": affordance.description,
        "duration_minutes": affordance.duration_minutes,
        "aliases": list(affordance.aliases),
        "event_type": affordance.event_type,
    }


def _public_affordance_target(target: dict[str, object]) -> dict[str, object]:
    affordances = target.get("affordances")
    details: list[dict[str, object]] = []
    if isinstance(affordances, list):
        details = [
            _affordance_dict(item)
            for item in affordances
            if isinstance(item, SemanticAffordance)
        ]
    return {
        key: value
        for key, value in {
            "id": target.get("id"),
            "kind": target.get("kind"),
            "name": target.get("name"),
            "description": target.get("description"),
            "interactable": target.get("interactable"),
            "affordance_ids": target.get("affordance_ids", []),
            "affordances": details,
        }.items()
        if value is not None
    }


def _event_matches_schedule(
    event: TownEvent,
    schedule: ScheduleSegment | None,
) -> bool:
    if schedule is None:
        return False
    haystack = f"{event.event_type} {event.summary} {event.location_id}".lower()
    return (
        schedule.location_id == event.location_id
        or schedule.location_id.lower() in haystack
        or any(token and token in haystack for token in _semantic_tokens(schedule.intent))
    )


def _object_matches_schedule(
    obj: TownObject,
    schedule: ScheduleSegment | None,
) -> bool:
    if schedule is None:
        return False
    affordances = " ".join(
        f"{item.id} {item.label} {item.description} {' '.join(item.aliases)}"
        for item in obj.affordances
    )
    haystack = f"{obj.id} {obj.name} {obj.description} {obj.location_id} {affordances}".lower()
    return any(token and token in haystack for token in _semantic_tokens(schedule.intent))


def _normalize_match_text(text: str) -> str:
    return " ".join(str(text).lower().strip().split())


def _text_match_score(query: str, text: str) -> int:
    normalized_query = _normalize_match_text(query)
    normalized_text = _normalize_match_text(text)
    if not normalized_query or not normalized_text:
        return 0
    score = 0
    if normalized_query == normalized_text:
        score += 20
    elif normalized_query in normalized_text:
        score += 12
    query_tokens = set(_semantic_tokens(normalized_query))
    text_tokens = set(_semantic_tokens(normalized_text))
    overlap = query_tokens & text_tokens
    score += len(overlap) * 4
    return score


def _affordance_match_score(query: str, affordance: SemanticAffordance) -> int:
    return _text_match_score(
        query,
        " ".join(
            [
                affordance.id,
                affordance.label,
                affordance.description,
                affordance.event_type,
                *affordance.aliases,
            ]
        ),
    )


def _matching_affordances(
    intent: str,
    affordances: list[SemanticAffordance],
) -> list[SemanticAffordance]:
    normalized_intent = _normalize_match_text(intent)
    matches: list[SemanticAffordance] = []
    for affordance in affordances:
        terms = [
            affordance.id,
            affordance.label,
            affordance.description,
            affordance.event_type,
            *affordance.aliases,
        ]
        normalized_terms = [_normalize_match_text(term) for term in terms if term]
        if (
            _affordance_match_score(intent, affordance) > 0
            or normalized_intent in normalized_terms
            or any(term and term in normalized_intent for term in normalized_terms)
        ):
            matches.append(affordance)
    return matches


def _suggest_affordances(
    intent: str,
    affordances: list[SemanticAffordance],
    *,
    limit: int = 3,
) -> list[dict[str, object]]:
    scored = [
        (score, affordance)
        for affordance in affordances
        if (score := _affordance_match_score(intent, affordance)) > 0
    ]
    if not scored:
        scored = [(0, affordance) for affordance in affordances]
    return [
        _affordance_dict(affordance)
        for _, affordance in sorted(scored, key=lambda item: (-item[0], item[1].id))[:limit]
    ]


def _intent_matches_affordance(
    intent: str,
    affordances: list[SemanticAffordance],
) -> bool:
    return bool(_matching_affordances(intent, affordances))


def _render_affordance_refs(affordances: list[SemanticAffordance]) -> str:
    if not affordances:
        return "无"
    return ", ".join(f"{item.label}({item.id})" for item in affordances)


def _semantic_tokens(text: str) -> list[str]:
    separators = " ，,。.;；:/\\()（）[]【】"
    normalized = text.lower()
    for sep in separators:
        normalized = normalized.replace(sep, " ")
    words = [word for word in normalized.split() if len(word) >= 2]
    if not words and text:
        words = [text.lower()]
    return words


def _render_known_locations(rows: object) -> str:
    if not isinstance(rows, list) or not rows:
        return "无"
    rendered: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        rendered.append(
            f"{row.get('name', '未知地点')} ({row.get('id', 'unknown')})："
            f"{row.get('description', '')}；affordances="
            f"{_render_affordance_row_refs(row.get('affordances'))}"
        )
    return "; ".join(rendered) if rendered else "无"


def _render_known_objects(rows: object) -> str:
    if not isinstance(rows, list) or not rows:
        return "无"
    rendered: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        affordance = "可交互" if row.get("interactable") else "不可交互"
        rendered.append(
            f"{row.get('name', '未知物体')} ({row.get('id', 'unknown')})，"
            f"地点={row.get('location_id', 'unknown')}，{affordance}："
            f"{row.get('description', '')}；affordances="
            f"{_render_affordance_row_refs(row.get('affordances'))}"
        )
    return "; ".join(rendered) if rendered else "无"


def _render_affordance_row_refs(value: object) -> str:
    if not isinstance(value, list) or not value:
        return "无"
    rendered: list[str] = []
    for item in value:
        if isinstance(item, dict):
            rendered.append(f"{item.get('label', item.get('id', 'unknown'))}({item.get('id', 'unknown')})")
    return ", ".join(rendered) if rendered else "无"


def _full_schedule_dict(segment: ScheduleSegment) -> dict[str, object]:
    return {
        "npc_id": segment.npc_id,
        "day": segment.day,
        "start_minute": segment.start_minute,
        "duration_minutes": segment.duration_minutes,
        "end_minute": segment.end_minute,
        "location_id": segment.location_id,
        "intent": segment.intent,
        "subtasks": list(segment.subtasks),
        "completion_tags": list(segment.completion_tags),
        "completion_policy": segment.completion_policy,
        "min_matching_actions": segment.min_matching_actions,
        "allow_explicit_override": segment.allow_explicit_override,
    }


def _schedule_completion_dict(completion) -> dict[str, object]:
    return {
        "npc_id": completion.npc_id,
        "day": completion.day,
        "start_minute": completion.start_minute,
        "location_id": completion.location_id,
        "note": completion.note,
        "completion_type": getattr(completion, "completion_type", "explicit_request"),
        "matched_action_id": getattr(completion, "matched_action_id", None),
        "matched_action_type": getattr(completion, "matched_action_type", None),
        "matching_reason": getattr(completion, "matching_reason", ""),
        "completion_policy": getattr(completion, "completion_policy", "first_matching_action"),
        "action_end_minute": getattr(completion, "action_end_minute", None),
        "completion_reason": getattr(completion, "completion_reason", ""),
    }


def _schedule_satisfaction_dict(satisfaction: ScheduleSatisfaction) -> dict[str, object]:
    return {
        "npc_id": satisfaction.npc_id,
        "day": satisfaction.day,
        "start_minute": satisfaction.start_minute,
        "location_id": satisfaction.location_id,
        "completion_policy": satisfaction.completion_policy,
        "matched_action_id": satisfaction.matched_action_id,
        "matched_action_type": satisfaction.matched_action_type,
        "matching_reason": satisfaction.matching_reason,
        "action_end_minute": satisfaction.action_end_minute,
        "match_count": satisfaction.match_count,
    }


def _resident_day_plan_dict(day_plan: ResidentDayPlan | None) -> dict[str, object] | None:
    if day_plan is None:
        return None
    return {
        "day": day_plan.day,
        "currently": day_plan.currently,
        "wake_up_minute": day_plan.wake_up_minute,
        "daily_intentions": list(day_plan.daily_intentions),
        "planning_evidence": list(day_plan.planning_evidence),
        "validation": dict(day_plan.validation),
        "schedule_summary": day_plan.schedule_summary,
        "day_summary": day_plan.day_summary,
        "schedule_evidence": list(day_plan.schedule_evidence),
        "started_minute": day_plan.started_minute,
        "ended_minute": day_plan.ended_minute,
        "lifecycle_anomalies": list(day_plan.lifecycle_anomalies),
    }


def _movement_intent(intent: str) -> bool:
    tokens = _semantic_tokens(intent)
    movement_terms = {"去", "到", "前往", "返回", "回家", "移动", "travel", "go", "move", "return"}
    return any(term in intent.lower() for term in movement_terms) or any(
        token in movement_terms for token in tokens
    )


class _FinalizedActionView:
    def __init__(self, payload: dict[str, object]) -> None:
        self.action_id = str(payload.get("action_id") or "")
        self.action_type = str(payload.get("action_type") or "")
        self.status = str(payload.get("status") or "")
        facts = payload.get("facts", {})
        self.facts = facts if isinstance(facts, dict) else {}
        if "location_id" not in self.facts and payload.get("location_id") is not None:
            self.facts = {**self.facts, "location_id": payload.get("location_id")}


def _normalize_schedule_completion_policy(value: str) -> str:
    if value in SCHEDULE_COMPLETION_POLICIES:
        return value
    return "first_matching_action"


def _schedule_is_fallback(segment: ScheduleSegment) -> bool:
    return any(str(item).startswith("fallback") for item in segment.subtasks)


def _revision_mentions_segment(
    revision_log: dict[str, object],
    segment: ScheduleSegment,
) -> bool:
    for key in ("before", "after"):
        payload = revision_log.get(key)
        if not isinstance(payload, dict):
            continue
        if (
            payload.get("start_minute") == segment.start_minute
            and payload.get("location_id") == segment.location_id
        ):
            return True
    return False


def _interruption_overlaps_segment(
    action_log: dict[str, object],
    segment: ScheduleSegment,
) -> bool:
    minute = action_log.get("minute")
    return isinstance(minute, int) and segment.start_minute <= minute < segment.end_minute


def _schedule_summary(schedule: list[ScheduleSegment]) -> str:
    if not schedule:
        return "无日程"
    return "；".join(
        f"{_minute_label(segment.start_minute)}-{_minute_label(segment.end_minute)} "
        f"{segment.location_id} {segment.intent}"
        for segment in schedule
    )


def _loop_guard_target(item: dict[str, object]) -> str:
    facts = item.get("facts")
    if not isinstance(facts, dict):
        return ""
    for key in ("to", "object_id", "target_npc_id", "location_id"):
        value = facts.get(key)
        if value:
            return str(value)
    return ""


def _snapshot_mapping(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise TownPersistenceError(f"runtime snapshot section must be an object: {key}")
    return value


def _validate_backend_path(path: str | Path | object | None, label: str) -> None:
    if path is None:
        raise TownPersistenceError(f"missing backend reference: {label}")
    backend_path = Path(path)
    if backend_path.exists():
        if not backend_path.is_dir():
            raise TownPersistenceError(f"incompatible backend reference {label}: {backend_path}")
        return
    backend_path.mkdir(parents=True, exist_ok=True)


def _freeze_snapshot_key(value: object) -> tuple[object, ...]:
    if not isinstance(value, list):
        return (value,)
    return tuple(_freeze_snapshot_key(item) if isinstance(item, list) else item for item in value)


def _normalize_completion_type(value: str) -> str:
    aliases = {
        "explicit": "explicit_request",
        "inferred": "inferred_action_match",
        "automatic": "automatic_action_match",
        "auto": "automatic_action_match",
        "explicit_request": "explicit_request",
        "inferred_action_match": "inferred_action_match",
        "automatic_action_match": "automatic_action_match",
        "repair": "repair",
        "day_finalize_missed": "day_finalize_missed",
    }
    return aliases.get(value, "explicit_request")


def _schedule_from_agent_response(response: AgentResponse) -> list[ScheduleSegment]:
    text = (
        response.structured_output.strip()
        or response.dialogue.strip()
        or response.inner_thought.strip()
        or response.reflection.strip()
    )
    payload = _parse_schedule_plan_json(text)
    schedule_items = payload.get("schedule")
    if "schedule" not in payload:
        raise ValueError("missing_schedule")
    if not isinstance(schedule_items, list):
        raise ValueError("invalid_schedule_plan")

    segments: list[ScheduleSegment] = []
    for item in schedule_items:
        if not isinstance(item, dict):
            raise ValueError("invalid_schedule_plan")
        try:
            npc_id = str(item["npc_id"])
            start_minute = int(item["start_minute"])
            duration_minutes = int(item["duration_minutes"])
            location_id = str(item["location_id"])
            intent = str(item["intent"])
            subtasks_raw = item.get("subtasks", [])
            completion_tags_raw = item.get("completion_tags", [])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid_schedule_plan") from exc
        if not isinstance(subtasks_raw, list) or not isinstance(completion_tags_raw, list):
            raise ValueError("invalid_schedule_plan")
        segments.append(
            ScheduleSegment(
                npc_id=npc_id,
                start_minute=start_minute,
                duration_minutes=duration_minutes,
                location_id=location_id,
                intent=intent,
                subtasks=[str(subtask) for subtask in subtasks_raw],
                completion_tags=[str(tag) for tag in completion_tags_raw],
            )
        )
    return segments


def _schedule_within_planning_window(
    *,
    npc_id: str,
    schedule: list[ScheduleSegment],
    fallback_schedule: list[ScheduleSegment],
    start_minute: int,
    end_minute: int,
) -> list[ScheduleSegment]:
    in_window = [
        segment
        for segment in schedule
        if (
            segment.npc_id == npc_id
            and start_minute <= segment.start_minute
            and segment.end_minute <= end_minute
        )
    ]
    if any(segment.start_minute <= start_minute < segment.end_minute for segment in in_window):
        return in_window

    fallback = [
        segment
        for segment in fallback_schedule
        if (
            segment.npc_id == npc_id
            and start_minute <= segment.start_minute
            and segment.end_minute <= end_minute
        )
    ]
    if fallback:
        return fallback
    return in_window


def _parse_schedule_plan_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    if not stripped.startswith("{"):
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            stripped = stripped[start : end + 1]
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_schedule_plan") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid_schedule_plan")
    return payload

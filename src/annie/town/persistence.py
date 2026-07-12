"""Versioned runtime persistence for the semantic town engine."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from annie.town.domain import (
    ConversationSession,
    ConversationTurn,
    CurrentAction,
    Location,
    ReflectionEvidence,
    ResidentDayPlan,
    ResidentPersona,
    ResidentScratch,
    ResidentSpatialMemory,
    ScheduleCompletion,
    ScheduleSatisfaction,
    ScheduleRevision,
    ScheduleSegment,
    SemanticAffordance,
    TownClock,
    TownEvent,
    TownObject,
    TownPerceptionPolicy,
    TownResidentState,
    TownState,
)
from annie.town.eventing import NPCRecord, NPCRegistry, TownEventBus

TOWN_RUNTIME_SNAPSHOT_VERSION = 1
TOWN_RUN_MANIFEST_VERSION = 1

SNAPSHOT_REQUIRED_SECTIONS = (
    "schema_version",
    "run",
    "clock",
    "semantic_world",
    "residents",
    "schedules",
    "current_actions",
    "conversations",
    "event_delivery",
    "loop_guards",
    "replay_cursor",
    "engine",
)


class TownPersistenceError(ValueError):
    """Raised when a TownWorld persistence artifact cannot be loaded."""


def town_state_to_snapshot_sections(state: TownState) -> dict[str, object]:
    """Serialize TownState-owned data into JSON-compatible snapshot sections."""
    return {
        "clock": _dataclass_dict(state.clock),
        "semantic_world": {
            "locations": {
                location_id: _location_dict(location)
                for location_id, location in sorted(state.locations.items())
            },
            "objects": {
                object_id: _object_dict(obj)
                for object_id, obj in sorted(state.objects.items())
            },
            "events": [_event_dict(event) for event in state.events],
            "npc_locations": dict(sorted(state.npc_locations.items())),
            "completed_schedule_segments": {
                npc_id: [_dataclass_dict(item) for item in items]
                for npc_id, items in sorted(state.completed_schedule_segments.items())
            },
            "satisfied_schedule_segments": {
                npc_id: [_dataclass_dict(item) for item in items]
                for npc_id, items in sorted(state.satisfied_schedule_segments.items())
            },
        },
        "residents": {
            npc_id: _resident_dict(resident)
            for npc_id, resident in sorted(state.residents.items())
        },
        "schedules": {
            npc_id: [_schedule_segment_dict(segment) for segment in schedule]
            for npc_id, schedule in sorted(state.schedules.items())
        },
        "current_actions": {
            npc_id: _current_action_dict(action)
            for npc_id, action in sorted(state.current_actions.items())
        },
        "conversations": {
            "sessions": {
                session_id: _conversation_session_dict(session)
                for session_id, session in sorted(state.conversation_sessions.items())
            },
            "cooldowns": dict(sorted(state.conversation_cooldowns.items())),
        },
    }


def town_state_from_snapshot_sections(snapshot: dict[str, object]) -> TownState:
    """Deserialize a TownState from validated version-1 snapshot sections."""
    semantic_world = _required_mapping(snapshot, "semantic_world")
    residents_payload = _required_mapping(snapshot, "residents")
    conversations = _required_mapping(snapshot, "conversations")

    state = TownState(
        clock=_town_clock(_required_mapping(snapshot, "clock")),
        locations={
            location_id: _location(payload)
            for location_id, payload in _mapping_items(
                _required_mapping(semantic_world, "locations"),
                "semantic_world.locations",
            ).items()
        },
        objects={
            object_id: _object(payload)
            for object_id, payload in _mapping_items(
                _required_mapping(semantic_world, "objects"),
                "semantic_world.objects",
            ).items()
        },
        events=[
            _event(payload)
            for payload in _required_list(semantic_world, "events")
        ],
        schedules={
            npc_id: [_schedule_segment(item) for item in _as_list(payload, f"schedules.{npc_id}")]
            for npc_id, payload in _mapping_items(_required_mapping(snapshot, "schedules"), "schedules").items()
        },
        current_actions={
            npc_id: _current_action(payload)
            for npc_id, payload in _mapping_items(
                _required_mapping(snapshot, "current_actions"),
                "current_actions",
            ).items()
        },
        conversation_sessions={
            session_id: _conversation_session(payload)
            for session_id, payload in _mapping_items(
                _required_mapping(conversations, "sessions"),
                "conversations.sessions",
            ).items()
        },
        conversation_cooldowns={
            str(pair): int(until)
            for pair, until in _required_mapping(conversations, "cooldowns").items()
        },
        completed_schedule_segments={
            npc_id: [_schedule_completion(item) for item in _as_list(payload, f"completed.{npc_id}")]
            for npc_id, payload in _mapping_items(
                _required_mapping(semantic_world, "completed_schedule_segments"),
                "semantic_world.completed_schedule_segments",
            ).items()
        },
        satisfied_schedule_segments={
            npc_id: [_schedule_satisfaction(item) for item in _as_list(payload, f"satisfied.{npc_id}")]
            for npc_id, payload in _mapping_items(
                _as_mapping(semantic_world.get("satisfied_schedule_segments", {}), "semantic_world.satisfied_schedule_segments"),
                "semantic_world.satisfied_schedule_segments",
            ).items()
        },
        npc_locations={
            str(npc_id): str(location_id)
            for npc_id, location_id in _required_mapping(semantic_world, "npc_locations").items()
        },
        residents={
            npc_id: _resident(payload)
            for npc_id, payload in _mapping_items(residents_payload, "residents").items()
        },
    )
    state.sync_occupants()
    return state


def validate_snapshot(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise TownPersistenceError("runtime snapshot must be a JSON object")
    for section in SNAPSHOT_REQUIRED_SECTIONS:
        if section not in payload:
            raise TownPersistenceError(f"runtime snapshot missing required section: {section}")
    version = payload["schema_version"]
    if version != TOWN_RUNTIME_SNAPSHOT_VERSION:
        raise TownPersistenceError(f"unsupported TownWorld runtime snapshot version: {version}")
    return payload


def load_snapshot(path: str | Path) -> dict[str, object]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return validate_snapshot(json.load(handle))


def write_json_atomic(path: str | Path, payload: object) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=str(destination.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, destination)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise
    return destination


def build_run_manifest(
    *,
    run_id: str,
    run_dir: str | Path,
    latest_snapshot_path: str | Path,
    step_snapshot_paths: list[str | Path] | None = None,
    replay_paths: dict[str, str | Path] | None = None,
    history_path: str | Path | None = None,
    vector_store_path: str | Path | None = None,
    model_summary: dict[str, object] | None = None,
    validation: dict[str, object] | None = None,
    diagnostics_path: str | Path | None = None,
    validation_path: str | Path | None = None,
    presentation_paths: dict[str, str | Path] | None = None,
    external_paths: dict[str, str | Path] | None = None,
) -> dict[str, object]:
    root = Path(run_dir)
    return {
        "manifest_version": TOWN_RUN_MANIFEST_VERSION,
        "run_id": run_id,
        "latest_snapshot_path": _manifest_path(root, latest_snapshot_path, external_paths),
        "step_snapshot_paths": [
            _manifest_path(root, path, external_paths)
            for path in step_snapshot_paths or []
        ],
        "replay_paths": {
            name: _manifest_path(root, path, external_paths)
            for name, path in sorted((replay_paths or {}).items())
        },
        "history_path": _manifest_path(root, history_path, external_paths)
        if history_path is not None
        else None,
        "vector_store_path": _manifest_path(root, vector_store_path, external_paths)
        if vector_store_path is not None
        else None,
        "model_summary": model_summary or {},
        "validation": validation or {},
        "diagnostics_path": _manifest_path(root, diagnostics_path, external_paths)
        if diagnostics_path is not None
        else None,
        "validation_path": _manifest_path(root, validation_path, external_paths)
        if validation_path is not None
        else None,
        "presentation_paths": {
            name: _manifest_path(root, path, external_paths)
            for name, path in sorted((presentation_paths or {}).items())
        },
    }


def load_run_manifest(path: str | Path) -> dict[str, object]:
    manifest_path = Path(path)
    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict):
        raise TownPersistenceError("town run manifest must be a JSON object")
    version = manifest.get("manifest_version")
    if version != TOWN_RUN_MANIFEST_VERSION:
        raise TownPersistenceError(f"unsupported TownWorld run manifest version: {version}")
    for key in ("run_id", "latest_snapshot_path"):
        if key not in manifest:
            raise TownPersistenceError(f"town run manifest missing required field: {key}")
    return manifest


def resolve_manifest_path(run_dir: str | Path, value: object) -> Path | None:
    if value is None:
        return None
    root = Path(run_dir)
    if isinstance(value, str):
        return root / value
    if isinstance(value, dict):
        if value.get("external") is True:
            path = value.get("path")
            if not isinstance(path, str):
                raise TownPersistenceError("external manifest path must include string path")
            return Path(path)
        path = value.get("path")
        if isinstance(path, str):
            return root / path
    raise TownPersistenceError(f"invalid manifest path reference: {value!r}")


def resolve_manifest_paths(run_dir: str | Path, manifest: dict[str, object]) -> dict[str, object]:
    replay_payload = manifest.get("replay_paths", {})
    if not isinstance(replay_payload, dict):
        raise TownPersistenceError("town run manifest replay_paths must be an object")
    return {
        "latest_snapshot_path": resolve_manifest_path(run_dir, manifest["latest_snapshot_path"]),
        "step_snapshot_paths": [
            resolve_manifest_path(run_dir, item)
            for item in _as_list(manifest.get("step_snapshot_paths", []), "step_snapshot_paths")
        ],
        "replay_paths": {
            str(name): resolve_manifest_path(run_dir, value)
            for name, value in replay_payload.items()
        },
        "history_path": resolve_manifest_path(run_dir, manifest.get("history_path")),
        "vector_store_path": resolve_manifest_path(run_dir, manifest.get("vector_store_path")),
        "diagnostics_path": resolve_manifest_path(run_dir, manifest.get("diagnostics_path")),
        "validation_path": resolve_manifest_path(run_dir, manifest.get("validation_path")),
        "presentation_paths": {
            str(name): resolve_manifest_path(run_dir, value)
            for name, value in _as_mapping(
                manifest.get("presentation_paths", {}),
                "presentation_paths",
            ).items()
        },
    }


def event_bus_to_dict(event_bus: TownEventBus) -> dict[str, object]:
    return {
        "inboxes": {
            npc_id: [_event_dict(event) for event in events]
            for npc_id, events in sorted(event_bus.inboxes.items())
        },
        "seen_event_ids": {
            npc_id: sorted(event_ids)
            for npc_id, event_ids in sorted(event_bus.seen_event_ids.items())
        },
    }


def event_bus_from_dict(payload: dict[str, object]) -> TownEventBus:
    bus = TownEventBus()
    bus.inboxes = {
        npc_id: [_event(item) for item in _as_list(events, f"event_delivery.inboxes.{npc_id}")]
        for npc_id, events in _mapping_items(_required_mapping(payload, "inboxes"), "event_delivery.inboxes").items()
    }
    bus.seen_event_ids = {
        npc_id: {str(event_id) for event_id in _as_list(event_ids, f"event_delivery.seen.{npc_id}")}
        for npc_id, event_ids in _mapping_items(
            _required_mapping(payload, "seen_event_ids"),
            "event_delivery.seen_event_ids",
        ).items()
    }
    return bus


def npc_registry_to_dict(registry: NPCRegistry) -> dict[str, object]:
    records = getattr(registry, "_records", {})
    return {
        npc_id: _dataclass_dict(record)
        for npc_id, record in sorted(records.items())
    }


def npc_registry_from_dict(payload: dict[str, object], state: TownState) -> NPCRegistry:
    records = [
        NPCRecord(
            npc_id=str(record["npc_id"]),
            location_id=record.get("location_id") if record.get("location_id") is not None else None,
            active=bool(record.get("active", True)),
        )
        for _, record in _mapping_items(payload, "engine.npc_registry").items()
    ]
    registry = NPCRegistry(records)
    registry.sync_from_state(state)
    return registry


def _manifest_path(
    root: Path,
    value: str | Path | None,
    external_paths: dict[str, str | Path] | None,
) -> object:
    if value is None:
        return None
    path = Path(value)
    root_resolved = root.resolve()
    external = {
        str(Path(item).resolve())
        for item in (external_paths or {}).values()
    }
    resolved = path.resolve()
    if str(resolved) in external:
        return {"path": str(path), "external": True}
    try:
        return str(resolved.relative_to(root_resolved))
    except ValueError:
        if path.is_absolute():
            return {"path": str(path), "external": True}
        return str(path)


def _dataclass_dict(value: object) -> dict[str, object]:
    return asdict(value)  # type: ignore[return-value]


def _affordance_dict(affordance: SemanticAffordance) -> dict[str, object]:
    return _dataclass_dict(affordance)


def _location_dict(location: Location) -> dict[str, object]:
    data = _dataclass_dict(location)
    data["affordances"] = [_affordance_dict(item) for item in location.affordances]
    return data


def _object_dict(obj: TownObject) -> dict[str, object]:
    data = _dataclass_dict(obj)
    data["affordances"] = [_affordance_dict(item) for item in obj.affordances]
    return data


def _event_dict(event: TownEvent) -> dict[str, object]:
    return _dataclass_dict(event)


def _schedule_segment_dict(segment: ScheduleSegment) -> dict[str, object]:
    return _dataclass_dict(segment)


def _current_action_dict(action: CurrentAction) -> dict[str, object]:
    return _dataclass_dict(action)


def _day_plan_dict(plan: ResidentDayPlan) -> dict[str, object]:
    return _dataclass_dict(plan)


def _reflection_evidence_dict(evidence: ReflectionEvidence) -> dict[str, object]:
    return _dataclass_dict(evidence)


def _resident_dict(resident: TownResidentState) -> dict[str, object]:
    return {
        "npc_id": resident.npc_id,
        "location_id": resident.location_id,
        "home_location_id": resident.home_location_id,
        "sleep_location_id": resident.sleep_location_id,
        "default_wake_window": list(resident.default_wake_window or []),
        "default_sleep_window": list(resident.default_sleep_window or []),
        "lifecycle_status": resident.lifecycle_status,
        "schedule": [_schedule_segment_dict(item) for item in resident.schedule],
        "current_action": (
            _current_action_dict(resident.current_action)
            if resident.current_action is not None
            else None
        ),
        "scratch": _dataclass_dict(resident.scratch),
        "persona": _dataclass_dict(resident.persona),
        "schedule_day": resident.schedule_day,
        "day_plans": {
            str(day): _day_plan_dict(plan)
            for day, plan in sorted(resident.day_plans.items())
        },
        "spatial_memory": _dataclass_dict(resident.spatial_memory),
        "poignancy": resident.poignancy,
        "reflection_evidence": [
            _reflection_evidence_dict(item) for item in resident.reflection_evidence
        ],
    }


def _conversation_turn_dict(turn: ConversationTurn) -> dict[str, object]:
    return _dataclass_dict(turn)


def _conversation_session_dict(session: ConversationSession) -> dict[str, object]:
    return {
        **_dataclass_dict(session),
        "participants": list(session.participants),
        "turns": [_conversation_turn_dict(turn) for turn in session.turns],
    }


def _town_clock(payload: dict[str, object]) -> TownClock:
    return TownClock(
        day=int(payload.get("day", 1)),
        minute=int(payload.get("minute", 8 * 60)),
        stride_minutes=int(payload.get("stride_minutes", 10)),
    )


def _affordance(payload: object) -> SemanticAffordance:
    data = _as_mapping(payload, "affordance")
    return SemanticAffordance(
        id=str(data["id"]),
        label=str(data["label"]),
        description=str(data.get("description", "")),
        duration_minutes=int(data.get("duration_minutes", 5)),
        aliases=[str(item) for item in _as_list(data.get("aliases", []), "affordance.aliases")],
        event_type=str(data.get("event_type", "interaction")),
    )


def _location(payload: object) -> Location:
    data = _as_mapping(payload, "location")
    return Location(
        id=str(data["id"]),
        name=str(data["name"]),
        description=str(data.get("description", "")),
        exits=[str(item) for item in _as_list(data.get("exits", []), "location.exits")],
        exit_travel_minutes={
            str(k): int(v)
            for k, v in _as_mapping(data.get("exit_travel_minutes", {}), "location.exit_travel_minutes").items()
        },
        object_ids=[str(item) for item in _as_list(data.get("object_ids", []), "location.object_ids")],
        occupant_ids=[str(item) for item in _as_list(data.get("occupant_ids", []), "location.occupant_ids")],
        affordances=[_affordance(item) for item in _as_list(data.get("affordances", []), "location.affordances")],
    )


def _object(payload: object) -> TownObject:
    data = _as_mapping(payload, "object")
    return TownObject(
        id=str(data["id"]),
        name=str(data["name"]),
        location_id=str(data["location_id"]),
        description=str(data.get("description", "")),
        interactable=bool(data.get("interactable", True)),
        affordances=[_affordance(item) for item in _as_list(data.get("affordances", []), "object.affordances")],
    )


def _event(payload: object) -> TownEvent:
    data = _as_mapping(payload, "event")
    return TownEvent(
        id=str(data["id"]),
        minute=int(data["minute"]),
        location_id=str(data["location_id"]),
        actor_id=str(data["actor_id"]) if data.get("actor_id") is not None else None,
        event_type=str(data["event_type"]),
        summary=str(data["summary"]),
        visible=bool(data.get("visible", True)),
        target_ids=[str(item) for item in _as_list(data.get("target_ids", []), "event.target_ids")],
    )


def _schedule_segment(payload: object) -> ScheduleSegment:
    data = _as_mapping(payload, "schedule_segment")
    return ScheduleSegment(
        npc_id=str(data["npc_id"]),
        start_minute=int(data["start_minute"]),
        duration_minutes=int(data["duration_minutes"]),
        location_id=str(data["location_id"]),
        intent=str(data["intent"]),
        subtasks=[str(item) for item in _as_list(data.get("subtasks", []), "schedule_segment.subtasks")],
        completion_tags=[
            str(item)
            for item in _as_list(
                data.get("completion_tags", []),
                "schedule_segment.completion_tags",
            )
        ],
        day=int(data["day"]) if data.get("day") is not None else None,
        completion_policy=_normalize_completion_policy(str(data.get("completion_policy", "first_matching_action"))),
        min_matching_actions=max(1, int(data.get("min_matching_actions", 1))),
        allow_explicit_override=bool(data.get("allow_explicit_override", True)),
    )


def _current_action(payload: object) -> CurrentAction:
    data = _as_mapping(payload, "current_action")
    return CurrentAction(
        npc_id=str(data["npc_id"]),
        action_type=str(data["action_type"]),
        location_id=str(data["location_id"]),
        start_minute=int(data["start_minute"]),
        duration_minutes=int(data["duration_minutes"]),
        status=str(data["status"]),
        summary=str(data.get("summary", "")),
        lifecycle_state=str(data.get("lifecycle_state", "in_progress")),
        effect_model=str(data.get("effect_model", "immediate_effect")),
        occupancy_model=str(data.get("occupancy_model", "duration_occupied")),
        effect_applied=bool(data.get("effect_applied", True)),
        failure_reason=(
            str(data["failure_reason"]) if data.get("failure_reason") is not None else None
        ),
        interrupted_reason=(
            str(data["interrupted_reason"])
            if data.get("interrupted_reason") is not None
            else None
        ),
        finalized_minute=(
            int(data["finalized_minute"]) if data.get("finalized_minute") is not None else None
        ),
        metadata=_as_mapping(data.get("metadata", {}), "current_action.metadata"),
    )


def _resident(payload: object) -> TownResidentState:
    data = _as_mapping(payload, "resident")
    return TownResidentState(
        npc_id=str(data["npc_id"]),
        location_id=str(data["location_id"]),
        home_location_id=(
            str(data["home_location_id"]) if data.get("home_location_id") is not None else None
        ),
        sleep_location_id=(
            str(data["sleep_location_id"]) if data.get("sleep_location_id") is not None else None
        ),
        default_wake_window=_optional_int_pair(data.get("default_wake_window")),
        default_sleep_window=_optional_int_pair(data.get("default_sleep_window")),
        lifecycle_status=str(data.get("lifecycle_status", "awake")),
        schedule=[_schedule_segment(item) for item in _as_list(data.get("schedule", []), "resident.schedule")],
        current_action=(
            _current_action(data["current_action"])
            if data.get("current_action") is not None
            else None
        ),
        scratch=ResidentScratch(currently=str(_as_mapping(data.get("scratch", {}), "resident.scratch").get("currently", ""))),
        persona=_resident_persona(data.get("persona", {})),
        schedule_day=int(data["schedule_day"]) if data.get("schedule_day") is not None else None,
        day_plans={
            int(day): _day_plan(plan)
            for day, plan in _as_mapping(data.get("day_plans", {}), "resident.day_plans").items()
        },
        spatial_memory=_spatial_memory(data.get("spatial_memory", {})),
        poignancy=int(data.get("poignancy", 0)),
        reflection_evidence=[
            _reflection_evidence(item)
            for item in _as_list(data.get("reflection_evidence", []), "resident.reflection_evidence")
        ],
    )


def _resident_persona(payload: object) -> ResidentPersona:
    data = _as_mapping(payload, "resident.persona")
    relationships = _as_mapping(data.get("relationships", {}), "resident.persona.relationships")
    return ResidentPersona(
        currently=str(data.get("currently", "")),
        lifestyle=str(data.get("lifestyle", "")),
        background=str(data.get("background", "")),
        traits=[str(item) for item in _as_list(data.get("traits", []), "resident.persona.traits")],
        relationships={str(key): str(value) for key, value in relationships.items()},
    )


def _day_plan(payload: object) -> ResidentDayPlan:
    data = _as_mapping(payload, "day_plan")
    return ResidentDayPlan(
        day=int(data["day"]),
        currently=str(data.get("currently", "")),
        wake_up_minute=int(data["wake_up_minute"]) if data.get("wake_up_minute") is not None else None,
        daily_intentions=[str(item) for item in _as_list(data.get("daily_intentions", []), "day_plan.daily_intentions")],
        planning_evidence=[_as_mapping(item, "day_plan.planning_evidence") for item in _as_list(data.get("planning_evidence", []), "day_plan.planning_evidence")],
        validation=_as_mapping(data.get("validation", {}), "day_plan.validation"),
        schedule_summary=str(data.get("schedule_summary", "")),
        day_summary=str(data.get("day_summary", "")),
        schedule_evidence=[
            _as_mapping(item, "day_plan.schedule_evidence")
            for item in _as_list(data.get("schedule_evidence", []), "day_plan.schedule_evidence")
        ],
        started_minute=int(data["started_minute"]) if data.get("started_minute") is not None else None,
        ended_minute=int(data["ended_minute"]) if data.get("ended_minute") is not None else None,
        lifecycle_anomalies=[
            _as_mapping(item, "day_plan.lifecycle_anomalies")
            for item in _as_list(data.get("lifecycle_anomalies", []), "day_plan.lifecycle_anomalies")
        ],
    )


def _spatial_memory(payload: object) -> ResidentSpatialMemory:
    data = _as_mapping(payload, "spatial_memory")
    return ResidentSpatialMemory(
        known_location_ids=[str(item) for item in _as_list(data.get("known_location_ids", []), "spatial_memory.locations")],
        known_object_ids=[str(item) for item in _as_list(data.get("known_object_ids", []), "spatial_memory.objects")],
    )


def _reflection_evidence(payload: object) -> ReflectionEvidence:
    data = _as_mapping(payload, "reflection_evidence")
    return ReflectionEvidence(
        id=str(data["id"]),
        evidence_type=str(data["evidence_type"]),
        summary=str(data["summary"]),
        poignancy=int(data["poignancy"]),
        clock_minute=int(data["clock_minute"]),
        metadata=_as_mapping(data.get("metadata", {}), "reflection_evidence.metadata"),
    )


def _schedule_completion(payload: object) -> ScheduleCompletion:
    data = _as_mapping(payload, "schedule_completion")
    return ScheduleCompletion(
        npc_id=str(data["npc_id"]),
        start_minute=int(data["start_minute"]),
        location_id=str(data["location_id"]),
        note=str(data.get("note", "")),
        day=int(data["day"]) if data.get("day") is not None else None,
        completion_type=_normalize_completion_type(str(data.get("completion_type", "explicit_request"))),
        matched_action_id=(
            str(data["matched_action_id"]) if data.get("matched_action_id") is not None else None
        ),
        matched_action_type=(
            str(data["matched_action_type"]) if data.get("matched_action_type") is not None else None
        ),
        matching_reason=str(data.get("matching_reason", "")),
        completion_policy=_normalize_completion_policy(str(data.get("completion_policy", "first_matching_action"))),
        action_end_minute=(
            int(data["action_end_minute"]) if data.get("action_end_minute") is not None else None
        ),
        completion_reason=str(data.get("completion_reason", data.get("matching_reason", ""))),
    )


def _schedule_satisfaction(payload: object) -> ScheduleSatisfaction:
    data = _as_mapping(payload, "schedule_satisfaction")
    return ScheduleSatisfaction(
        npc_id=str(data["npc_id"]),
        start_minute=int(data["start_minute"]),
        location_id=str(data["location_id"]),
        day=int(data["day"]) if data.get("day") is not None else None,
        completion_policy=_normalize_completion_policy(str(data.get("completion_policy", "first_matching_action"))),
        matched_action_id=(
            str(data["matched_action_id"]) if data.get("matched_action_id") is not None else None
        ),
        matched_action_type=(
            str(data["matched_action_type"]) if data.get("matched_action_type") is not None else None
        ),
        matching_reason=str(data.get("matching_reason", "")),
        action_end_minute=(
            int(data["action_end_minute"]) if data.get("action_end_minute") is not None else None
        ),
        match_count=max(1, int(data.get("match_count", 1))),
    )


def _normalize_completion_policy(value: str) -> str:
    if value in {
        "first_matching_action",
        "occupy_until_segment_end",
        "min_matching_actions",
        "explicit",
    }:
        return value
    return "first_matching_action"


def _normalize_completion_type(value: str) -> str:
    return {
        "explicit": "explicit_request",
        "inferred": "inferred_action_match",
        "automatic": "automatic_action_match",
        "auto": "automatic_action_match",
        "explicit_request": "explicit_request",
        "inferred_action_match": "inferred_action_match",
        "automatic_action_match": "automatic_action_match",
        "repair": "repair",
        "day_finalize_missed": "day_finalize_missed",
    }.get(value, "explicit_request")


def _optional_int_pair(payload: object) -> tuple[int, int] | None:
    if payload is None:
        return None
    values = _as_list(payload, "int_pair")
    if len(values) != 2:
        return None
    return (int(values[0]), int(values[1]))


def _conversation_turn(payload: object) -> ConversationTurn:
    data = _as_mapping(payload, "conversation_turn")
    return ConversationTurn(
        speaker_id=str(data["speaker_id"]),
        listener_id=str(data["listener_id"]),
        text=str(data["text"]),
        minute=int(data["minute"]),
    )


def _conversation_session(payload: object) -> ConversationSession:
    data = _as_mapping(payload, "conversation_session")
    participants = _as_list(data["participants"], "conversation_session.participants")
    return ConversationSession(
        id=str(data["id"]),
        participants=(str(participants[0]), str(participants[1])),
        initiator_id=str(data["initiator_id"]),
        location_id=str(data["location_id"]),
        topic=str(data.get("topic", "")),
        started_minute=int(data["started_minute"]),
        max_turns=int(data["max_turns"]),
        turns=[_conversation_turn(item) for item in _as_list(data.get("turns", []), "conversation_session.turns")],
        status=str(data.get("status", "active")),
        close_reason=str(data.get("close_reason", "")),
        ended_minute=int(data["ended_minute"]) if data.get("ended_minute") is not None else None,
    )


def _schedule_revision(payload: object) -> ScheduleRevision:
    data = _as_mapping(payload, "schedule_revision")
    return ScheduleRevision(
        npc_id=str(data["npc_id"]),
        event_id=str(data["event_id"]),
        reason=str(data["reason"]),
        inserted_segment=_schedule_segment(data["inserted_segment"]),
    )


def engine_runtime_to_dict(
    *,
    perception_policy: TownPerceptionPolicy,
    npc_registry: NPCRegistry,
    speak_cooldowns: dict[tuple[str, str], int],
    schedule_revisions: dict[tuple[str, str], ScheduleRevision],
    latest_schedule_revision_by_npc: dict[str, ScheduleRevision],
    planning_log: list[dict[str, object]],
    action_log: list[dict[str, object]],
    replay_log: list[dict[str, object]],
    reflection_log: list[dict[str, object]],
    chat_iter: int,
    conversation_cooldown_minutes: int,
    speak_cooldown_minutes: int,
    reflection_threshold: int,
) -> dict[str, object]:
    return {
        "perception_policy": _dataclass_dict(perception_policy),
        "npc_registry": npc_registry_to_dict(npc_registry),
        "speak_cooldowns": [
            {"speaker_id": pair[0], "listener_id": pair[1], "until_minute": until}
            for pair, until in sorted(speak_cooldowns.items())
        ],
        "schedule_revisions": [
            {
                "npc_id": key[0],
                "event_id": key[1],
                "revision": _schedule_revision_dict(revision),
            }
            for key, revision in sorted(schedule_revisions.items())
        ],
        "latest_schedule_revision_by_npc": {
            npc_id: _schedule_revision_dict(revision)
            for npc_id, revision in sorted(latest_schedule_revision_by_npc.items())
        },
        "planning_log": list(planning_log),
        "action_log": list(action_log),
        "replay_log": list(replay_log),
        "reflection_log": list(reflection_log),
        "chat_iter": chat_iter,
        "conversation_cooldown_minutes": conversation_cooldown_minutes,
        "speak_cooldown_minutes": speak_cooldown_minutes,
        "reflection_threshold": reflection_threshold,
    }


def _schedule_revision_dict(revision: ScheduleRevision) -> dict[str, object]:
    return {
        "npc_id": revision.npc_id,
        "event_id": revision.event_id,
        "reason": revision.reason,
        "inserted_segment": _schedule_segment_dict(revision.inserted_segment),
    }


def engine_runtime_from_dict(payload: dict[str, object]) -> dict[str, object]:
    policy = _as_mapping(payload.get("perception_policy", {}), "engine.perception_policy")
    return {
        "perception_policy": TownPerceptionPolicy(
            max_events=int(policy.get("max_events", 5)),
            max_objects=int(policy.get("max_objects", 5)),
            max_npcs=int(policy.get("max_npcs", 5)),
            max_exits=int(policy.get("max_exits", 4)),
            max_known_locations=int(policy.get("max_known_locations", 8)),
            max_known_objects=int(policy.get("max_known_objects", 8)),
        ),
        "speak_cooldowns": {
            (str(item["speaker_id"]), str(item["listener_id"])): int(item["until_minute"])
            for item in (
                _as_mapping(row, "engine.speak_cooldown")
                for row in _as_list(payload.get("speak_cooldowns", []), "engine.speak_cooldowns")
            )
        },
        "schedule_revisions": {
            (str(item["npc_id"]), str(item["event_id"])): _schedule_revision(item["revision"])
            for item in (
                _as_mapping(row, "engine.schedule_revision")
                for row in _as_list(payload.get("schedule_revisions", []), "engine.schedule_revisions")
            )
        },
        "latest_schedule_revision_by_npc": {
            npc_id: _schedule_revision(revision)
            for npc_id, revision in _mapping_items(
                _as_mapping(payload.get("latest_schedule_revision_by_npc", {}), "engine.latest_schedule_revision_by_npc"),
                "engine.latest_schedule_revision_by_npc",
            ).items()
        },
        "planning_log": [
            _as_mapping(item, "engine.planning_log")
            for item in _as_list(payload.get("planning_log", []), "engine.planning_log")
        ],
        "action_log": [
            _as_mapping(item, "engine.action_log")
            for item in _as_list(payload.get("action_log", []), "engine.action_log")
        ],
        "replay_log": [
            _as_mapping(item, "engine.replay_log")
            for item in _as_list(payload.get("replay_log", []), "engine.replay_log")
        ],
        "reflection_log": [
            _as_mapping(item, "engine.reflection_log")
            for item in _as_list(payload.get("reflection_log", []), "engine.reflection_log")
        ],
        "chat_iter": int(payload.get("chat_iter", 4)),
        "conversation_cooldown_minutes": int(payload.get("conversation_cooldown_minutes", 60)),
        "speak_cooldown_minutes": int(payload.get("speak_cooldown_minutes", 10)),
        "reflection_threshold": int(payload.get("reflection_threshold", 6)),
    }


def _required_mapping(payload: dict[str, object], key: str) -> dict[str, object]:
    if key not in payload:
        raise TownPersistenceError(f"runtime snapshot missing required section: {key}")
    return _as_mapping(payload[key], key)


def _required_list(payload: dict[str, object], key: str) -> list[object]:
    if key not in payload:
        raise TownPersistenceError(f"runtime snapshot missing required section: {key}")
    return _as_list(payload[key], key)


def _as_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TownPersistenceError(f"{label} must be an object")
    return value


def _mapping_items(value: dict[str, object], label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TownPersistenceError(f"{label} must be an object")
    return {str(k): v for k, v in value.items()}


def _as_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise TownPersistenceError(f"{label} must be a list")
    return value

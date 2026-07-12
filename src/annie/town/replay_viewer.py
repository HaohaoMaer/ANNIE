"""Presentation read model and static viewer generation for TownWorld runs."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from annie.town.persistence import (
    load_run_manifest,
    load_snapshot,
    resolve_manifest_path,
    resolve_manifest_paths,
    write_json_atomic,
)

TOWN_REPLAY_READ_MODEL_VERSION = 1


def build_town_replay_read_model(manifest_path: str | Path) -> dict[str, object]:
    """Build a stable UI-facing read model from a TownWorld run manifest."""
    manifest_file = Path(manifest_path)
    run_dir = manifest_file.parent
    manifest = load_run_manifest(manifest_file)
    resolved = resolve_manifest_paths(run_dir, manifest)
    latest_snapshot_path = resolved.get("latest_snapshot_path")
    if not isinstance(latest_snapshot_path, Path):
        raise ValueError("manifest latest_snapshot_path did not resolve to a path")

    snapshot = load_snapshot(latest_snapshot_path)
    replay_paths = _path_mapping(resolved.get("replay_paths", {}))
    diagnostics_path = _resolve_optional_manifest_path(run_dir, manifest, "diagnostics_path")
    validation_path = _resolve_optional_manifest_path(run_dir, manifest, "validation_path")
    diagnostics = _read_json(diagnostics_path) or _read_json(run_dir / "diagnostics.json") or {}
    validation = _read_json(validation_path) or _read_json(run_dir / "validation.json")
    if validation is None and isinstance(diagnostics, dict):
        validation = diagnostics.get("validation", {})
    if not isinstance(validation, dict):
        validation = {}

    actions = _read_jsonl(replay_paths.get("actions"))
    checkpoints = _read_jsonl(replay_paths.get("checkpoints"))
    reflections = _read_jsonl(replay_paths.get("reflections"))

    artifacts = _artifact_provenance(
        run_dir,
        manifest_file,
        manifest,
        resolved,
        diagnostics_path,
        validation_path,
    )
    locations = _locations(snapshot)
    residents = _residents(snapshot)
    schedules = _schedules(snapshot)
    conversations = _conversations(snapshot)
    frames = _world_frames(checkpoints, snapshot, replay_paths.get("checkpoints"))
    planning = _planning_evidence(snapshot)
    reflection_entries = _reflections(reflections, snapshot, replay_paths.get("reflections"))
    day_summaries = _day_summaries(snapshot)
    lifecycle_anomalies = _lifecycle_anomalies(snapshot, validation)
    warnings = _warnings(validation, diagnostics)
    resume_markers = _resume_markers(diagnostics)

    timeline = _timeline_events(
        manifest,
        snapshot,
        actions,
        checkpoints,
        reflections,
        planning,
        day_summaries,
        lifecycle_anomalies,
        warnings,
        resume_markers,
        replay_paths,
    )

    return {
        "schema": {
            "name": "annie.town.replay_read_model",
            "version": TOWN_REPLAY_READ_MODEL_VERSION,
        },
        "run": {
            "run_id": str(manifest.get("run_id", run_dir.name)),
            "run_dir": str(run_dir),
            "manifest_path": str(manifest_file),
            "resumed": bool(_get(diagnostics, "run", "resumed")),
            "clock": snapshot.get("clock", {}),
            "parameters": _get(diagnostics, "run", "parameters") or {},
            "scenario": diagnostics.get("scenario", {}) if isinstance(diagnostics, dict) else {},
        },
        "artifacts": artifacts,
        "locations": locations,
        "residents": residents,
        "timeline_events": timeline,
        "world_frames": frames,
        "schedules": schedules,
        "conversations": conversations,
        "planning_evidence": planning,
        "reflections": reflection_entries,
        "day_summaries": day_summaries,
        "lifecycle_anomalies": lifecycle_anomalies,
        "warnings": warnings,
        "resume_markers": resume_markers,
        "final_resident_states": _final_resident_states(snapshot),
        "debug": {
            "diagnostics_summary": _diagnostics_summary(diagnostics),
        },
    }


def write_town_replay_read_model(
    manifest_path: str | Path,
    output_path: str | Path | None = None,
) -> Path:
    manifest_file = Path(manifest_path)
    path = Path(output_path) if output_path is not None else manifest_file.parent / "presentation" / "replay_read_model.json"
    model = build_town_replay_read_model(manifest_file)
    return write_json_atomic(path, model)


def write_town_replay_viewer(
    manifest_path: str | Path,
    viewer_dir: str | Path | None = None,
    *,
    read_model_path: str | Path | None = None,
) -> dict[str, Path]:
    manifest_file = Path(manifest_path)
    root = Path(viewer_dir) if viewer_dir is not None else manifest_file.parent / "viewer"
    root.mkdir(parents=True, exist_ok=True)
    model_path = root / "replay_read_model.json"
    if read_model_path is None:
        write_town_replay_read_model(manifest_file, model_path)
    else:
        payload = json.loads(Path(read_model_path).read_text(encoding="utf-8"))
        write_json_atomic(model_path, payload)
    index_path = root / "index.html"
    index_path.write_text(_viewer_html(), encoding="utf-8")
    return {"viewer_index": index_path, "viewer_read_model": model_path}


def _timeline_events(
    manifest: dict[str, object],
    snapshot: dict[str, object],
    actions: list[dict[str, object]],
    checkpoints: list[dict[str, object]],
    reflections: list[dict[str, object]],
    planning: list[dict[str, object]],
    day_summaries: list[dict[str, object]],
    lifecycle_anomalies: list[dict[str, object]],
    warnings: list[dict[str, object]],
    resume_markers: list[dict[str, object]],
    replay_paths: dict[str, Path],
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    first_frame = _first_checkpoint_snapshot(checkpoints) or snapshot
    clock = first_frame.get("clock", {}) if isinstance(first_frame.get("clock"), dict) else {}
    events.append(
        _event(
            "run_started",
            clock.get("day"),
            clock.get("minute"),
            f"Run {manifest.get('run_id', 'town')} started",
            source={"artifact": "manifest", "path": "manifest.json"},
        )
    )
    seen_days: set[int] = set()
    for line, row in enumerate(checkpoints, start=1):
        snap = row.get("snapshot")
        if not isinstance(snap, dict):
            continue
        day = snap.get("day")
        minute = snap.get("minute", row.get("minute"))
        if isinstance(day, int) and day not in seen_days:
            seen_days.add(day)
            events.append(
                _event(
                    "day_started",
                    day,
                    minute,
                    f"Day {day} began",
                    source=_source("checkpoints", replay_paths.get("checkpoints"), line),
                )
            )
        for item in _list(row.get("schedule_evidence")):
            if isinstance(item, dict):
                events.append(_schedule_event(item, day, minute, replay_paths.get("checkpoints"), line))
        for item in _list(row.get("finalized_actions")):
            if isinstance(item, dict):
                events.append(_action_event(item, replay_paths.get("checkpoints"), line, default_type="resident_finished_action"))

    for line, action in enumerate(actions, start=1):
        events.append(_action_event(action, replay_paths.get("actions"), line))

    for item in planning:
        events.append(
            _event(
                "resident_planned_day",
                item.get("day"),
                item.get("minute"),
                str(item.get("summary") or f"{item.get('resident_id')} planning {item.get('stage', 'checkpoint')}"),
                resident_id=item.get("resident_id"),
                details={k: v for k, v in item.items() if k not in {"source"}},
                source=item.get("source") if isinstance(item.get("source"), dict) else None,
            )
        )
    for line, item in enumerate(reflections, start=1):
        if isinstance(item, dict):
            events.append(
                _event(
                    "reflection_created",
                    item.get("day"),
                    item.get("minute") or item.get("clock_minute"),
                    str(item.get("summary") or item.get("content") or "Reflection created"),
                    resident_id=item.get("npc_id") or item.get("resident_id"),
                    source=_source("reflections", replay_paths.get("reflections"), line),
                    details=item,
                )
            )
    for item in day_summaries:
        events.append(
            _event(
                "day_summary_created",
                item.get("day"),
                item.get("ended_minute") or item.get("minute"),
                str(item.get("summary") or "Day summary created"),
                resident_id=item.get("resident_id"),
                source=item.get("source") if isinstance(item.get("source"), dict) else None,
                details=item,
            )
        )
    for item in lifecycle_anomalies:
        events.append(
            _event(
                "lifecycle_anomaly_recorded",
                item.get("day"),
                item.get("minute"),
                str(item.get("summary") or item.get("kind") or "Lifecycle anomaly recorded"),
                resident_id=item.get("resident_id") or item.get("npc_id"),
                source=item.get("source") if isinstance(item.get("source"), dict) else None,
                details=item,
            )
        )
    for item in warnings:
        events.append(
            _event(
                "warning_recorded",
                item.get("day"),
                item.get("minute"),
                str(item.get("summary") or item.get("kind") or "Warning recorded"),
                resident_id=item.get("resident_id") or item.get("npc_id"),
                source=item.get("source") if isinstance(item.get("source"), dict) else None,
                details=item,
            )
        )
    for item in resume_markers:
        events.append(
            _event(
                "run_resumed",
                _get(item, "restored_time", "day"),
                _get(item, "restored_time", "minute"),
                "Run resumed from snapshot",
                source=item.get("source") if isinstance(item.get("source"), dict) else None,
                details=item,
            )
        )
    events.extend(_conversation_events(_conversations(snapshot)))
    return sorted(
        (event for event in events if event),
        key=lambda event: (
            _sort_int(event.get("day")),
            _sort_int(event.get("minute")),
            str(event.get("type")),
            str(event.get("resident_id", "")),
        ),
    )


def _action_event(
    action: dict[str, object],
    path: Path | None,
    line: int,
    *,
    default_type: str | None = None,
) -> dict[str, object]:
    action_type = str(action.get("action_type") or action.get("type") or "action")
    status = str(action.get("status") or action.get("lifecycle_state") or "unknown")
    event_type = default_type or "resident_started_action"
    if action_type in {"move_to", "move"}:
        event_type = "resident_moved"
    elif action_type in {"speak_to", "speak"}:
        event_type = "resident_spoke"
    elif status in {"success", "succeeded", "done", "completed", "finished", "finalized"}:
        event_type = "resident_finished_action"
    summary = str(action.get("summary") or action.get("text") or f"{action.get('npc_id', action.get('resident_id', 'resident'))} {action_type} {status}")
    details = {
        "action_type": action_type,
        "status": status,
        "start_minute": action.get("start_minute", action.get("minute")),
        "end_minute": action.get("end_minute"),
        "facts": action.get("facts", {}),
    }
    return _event(
        event_type,
        action.get("day"),
        action.get("minute", action.get("start_minute")),
        summary,
        resident_id=action.get("npc_id") or action.get("resident_id"),
        location_id=action.get("location_id"),
        status=status,
        source=_source("actions", path, line),
        details=details,
    )


def _schedule_event(
    item: dict[str, object],
    day: object,
    minute: object,
    path: Path | None,
    line: int,
) -> dict[str, object]:
    transition = str(item.get("status") or item.get("stage") or item.get("transition_type") or "changed")
    return _event(
        "schedule_segment_changed",
        item.get("day", day),
        item.get("minute", minute),
        str(item.get("summary") or item.get("intent") or f"Schedule segment {transition}"),
        resident_id=item.get("npc_id") or item.get("resident_id"),
        location_id=item.get("location_id"),
        status=transition,
        source=_source("checkpoints", path, line),
        details={
            "segment_id": item.get("segment_id") or item.get("start_minute"),
            "intent": item.get("intent"),
            "transition_type": transition,
            "evidence": item,
        },
    )


def _event(
    event_type: str,
    day: object,
    minute: object,
    summary: str,
    *,
    resident_id: object = None,
    location_id: object = None,
    status: object = None,
    source: dict[str, object] | None = None,
    details: dict[str, object] | None = None,
) -> dict[str, object]:
    event: dict[str, object] = {
        "id": f"{event_type}:{day}:{minute}:{resident_id or location_id or len(summary)}",
        "type": event_type,
        "day": day,
        "minute": minute,
        "time": _time_label(day, minute),
        "summary": summary,
    }
    if resident_id is not None:
        event["resident_id"] = resident_id
    if location_id is not None:
        event["location_id"] = location_id
    if status is not None:
        event["status"] = status
    if source is not None:
        event["source"] = source
    if details:
        event["details"] = details
    return event


def _locations(snapshot: dict[str, object]) -> list[dict[str, object]]:
    world = _mapping(snapshot.get("semantic_world"))
    locations = _mapping(world.get("locations"))
    objects = _mapping(world.get("objects"))
    result = []
    for location_id, payload in sorted(locations.items()):
        data = _mapping(payload)
        object_ids = [str(item) for item in _list(data.get("object_ids"))]
        result.append(
            {
                "id": str(location_id),
                "name": str(data.get("name", location_id)),
                "description": str(data.get("description", "")),
                "exits": list(data.get("exits", [])) if isinstance(data.get("exits"), list) else [],
                "objects": [
                    {
                        "id": object_id,
                        "name": str(_mapping(objects.get(object_id)).get("name", object_id)),
                        "description": str(_mapping(objects.get(object_id)).get("description", "")),
                        "affordances": _mapping(objects.get(object_id)).get("affordances", []),
                    }
                    for object_id in object_ids
                ],
                "affordances": data.get("affordances", []),
            }
        )
    return result


def _residents(snapshot: dict[str, object]) -> list[dict[str, object]]:
    residents = _mapping(snapshot.get("residents"))
    result = []
    for npc_id, payload in sorted(residents.items()):
        data = _mapping(payload)
        persona = _mapping(data.get("persona"))
        result.append(
            {
                "id": str(npc_id),
                "label": str(data.get("name") or npc_id),
                "location_id": data.get("location_id"),
                "home_location_id": data.get("home_location_id"),
                "sleep_location_id": data.get("sleep_location_id"),
                "lifecycle_status": data.get("lifecycle_status"),
                "persona": {
                    "currently": persona.get("currently", ""),
                    "lifestyle": persona.get("lifestyle", ""),
                    "background": persona.get("background", ""),
                    "traits": persona.get("traits", []),
                    "relationships": persona.get("relationships", {}),
                },
            }
        )
    return result


def _schedules(snapshot: dict[str, object]) -> dict[str, list[dict[str, object]]]:
    schedules = _mapping(snapshot.get("schedules"))
    completed = _mapping(_mapping(snapshot.get("semantic_world")).get("completed_schedule_segments"))
    result: dict[str, list[dict[str, object]]] = {}
    for npc_id, rows in sorted(schedules.items()):
        result[str(npc_id)] = [
            {
                **_mapping(row),
                "state": _schedule_state(_mapping(row), _list(completed.get(npc_id))),
                "source": {"artifact": "snapshot", "section": f"schedules.{npc_id}"},
            }
            for row in _list(rows)
            if isinstance(row, dict)
        ]
    return result


def _schedule_state(segment: dict[str, object], completed: list[object]) -> str:
    for item in completed:
        data = _mapping(item)
        if data.get("start_minute") == segment.get("start_minute") and data.get("location_id") == segment.get("location_id"):
            return "completed"
    return "planned"


def _conversations(snapshot: dict[str, object]) -> list[dict[str, object]]:
    sessions = _mapping(_mapping(snapshot.get("conversations")).get("sessions"))
    result = []
    for session_id, payload in sorted(sessions.items()):
        data = _mapping(payload)
        turns = [
            {
                **_mapping(turn),
                "source": {"artifact": "snapshot", "section": f"conversations.sessions.{session_id}.turns"},
            }
            for turn in _list(data.get("turns"))
            if isinstance(turn, dict)
        ]
        result.append(
            {
                "id": str(session_id),
                "participants": data.get("participants", []),
                "location_id": data.get("location_id"),
                "topic": data.get("topic", ""),
                "started_minute": data.get("started_minute"),
                "ended_minute": data.get("ended_minute"),
                "status": data.get("status"),
                "turns": turns,
                "source": {"artifact": "snapshot", "section": f"conversations.sessions.{session_id}"},
            }
        )
    return result


def _conversation_events(sessions: list[dict[str, object]]) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for session in sessions:
        events.append(
            _event(
                "conversation_started",
                None,
                session.get("started_minute"),
                str(session.get("topic") or "Conversation started"),
                location_id=session.get("location_id"),
                status=session.get("status"),
                source=session.get("source") if isinstance(session.get("source"), dict) else None,
                details={"participants": session.get("participants", []), "session_id": session.get("id")},
            )
        )
        for turn in _list(session.get("turns")):
            data = _mapping(turn)
            events.append(
                _event(
                    "resident_spoke",
                    None,
                    data.get("minute"),
                    str(data.get("text", "")),
                    resident_id=data.get("speaker_id"),
                    location_id=session.get("location_id"),
                    source=data.get("source") if isinstance(data.get("source"), dict) else None,
                    details={"listener_id": data.get("listener_id"), "session_id": session.get("id")},
                )
            )
        if session.get("ended_minute") is not None:
            events.append(
                _event(
                    "conversation_ended",
                    None,
                    session.get("ended_minute"),
                    str(session.get("close_reason") or "Conversation ended"),
                    location_id=session.get("location_id"),
                    status=session.get("status"),
                    source=session.get("source") if isinstance(session.get("source"), dict) else None,
                    details={"participants": session.get("participants", []), "session_id": session.get("id")},
                )
            )
    return events


def _world_frames(
    checkpoints: list[dict[str, object]],
    snapshot: dict[str, object],
    checkpoint_path: Path | None,
) -> list[dict[str, object]]:
    frames = []
    for line, row in enumerate(checkpoints, start=1):
        snap = row.get("snapshot")
        if isinstance(snap, dict):
            frames.append(_frame(snap, source=_source("checkpoints", checkpoint_path, line), tick=row.get("tick")))
    if not frames:
        frames.append(_frame(snapshot, source={"artifact": "snapshot", "path": "state/latest.json"}))
    return frames


def _frame(snapshot: dict[str, object], *, source: dict[str, object], tick: object = None) -> dict[str, object]:
    residents = _mapping(snapshot.get("residents"))
    schedules = _mapping(snapshot.get("schedules"))
    current_actions = _mapping(snapshot.get("current_actions"))
    minute = snapshot.get("minute") or _mapping(snapshot.get("clock")).get("minute")
    day = snapshot.get("day") or _mapping(snapshot.get("clock")).get("day")
    resident_states = {}
    by_location: dict[str, list[str]] = {}
    for npc_id, payload in sorted(residents.items()):
        data = _mapping(payload)
        location_id = str(data.get("location_id", "unknown"))
        by_location.setdefault(location_id, []).append(str(npc_id))
        resident_states[str(npc_id)] = {
            "location_id": location_id,
            "lifecycle_status": data.get("lifecycle_status"),
            "current_action": current_actions.get(npc_id),
            "active_schedule_segment": _active_segment(_list(schedules.get(npc_id)), minute),
        }
    return {
        "tick": tick,
        "day": day,
        "minute": minute,
        "time": _time_label(day, minute),
        "residents": resident_states,
        "locations": [{"location_id": key, "resident_ids": value} for key, value in sorted(by_location.items())],
        "source": source,
    }


def _active_segment(rows: list[object], minute: object) -> dict[str, object] | None:
    if not isinstance(minute, int):
        return None
    for row in rows:
        data = _mapping(row)
        start = data.get("start_minute")
        duration = data.get("duration_minutes")
        if isinstance(start, int) and isinstance(duration, int) and start <= minute < start + duration:
            return data
    return None


def _planning_evidence(snapshot: dict[str, object]) -> list[dict[str, object]]:
    result = []
    for line, item in enumerate(_list(_mapping(snapshot.get("engine")).get("planning_log")), start=1):
        if isinstance(item, dict):
            data = dict(item)
            data.setdefault("resident_id", data.get("npc_id"))
            data.setdefault("summary", f"{data.get('resident_id')} planning {data.get('stage', 'checkpoint')}")
            data["source"] = {"artifact": "snapshot", "section": "engine.planning_log", "index": line - 1}
            result.append(data)
    residents = _mapping(snapshot.get("residents"))
    for npc_id, resident in sorted(residents.items()):
        for day, plan in sorted(_mapping(_mapping(resident).get("day_plans")).items()):
            for index, item in enumerate(_list(_mapping(plan).get("planning_evidence"))):
                if isinstance(item, dict):
                    result.append(
                        {
                            **item,
                            "resident_id": npc_id,
                            "day": _int_or_original(day),
                            "source": {
                                "artifact": "snapshot",
                                "section": f"residents.{npc_id}.day_plans.{day}.planning_evidence",
                                "index": index,
                            },
                        }
                    )
    return result


def _reflections(
    reflection_rows: list[dict[str, object]],
    snapshot: dict[str, object],
    reflection_path: Path | None,
) -> list[dict[str, object]]:
    result = []
    for line, row in enumerate(reflection_rows, start=1):
        result.append({**row, "source": _source("reflections", reflection_path, line)})
    for npc_id, resident in sorted(_mapping(snapshot.get("residents")).items()):
        for index, item in enumerate(_list(_mapping(resident).get("reflection_evidence"))):
            if isinstance(item, dict):
                result.append(
                    {
                        **item,
                        "resident_id": npc_id,
                        "minute": item.get("clock_minute"),
                        "source": {
                            "artifact": "snapshot",
                            "section": f"residents.{npc_id}.reflection_evidence",
                            "index": index,
                        },
                    }
                )
    return result


def _day_summaries(snapshot: dict[str, object]) -> list[dict[str, object]]:
    rows = []
    for npc_id, resident in sorted(_mapping(snapshot.get("residents")).items()):
        for day, plan in sorted(_mapping(_mapping(resident).get("day_plans")).items()):
            data = _mapping(plan)
            if data.get("day_summary"):
                rows.append(
                    {
                        "resident_id": npc_id,
                        "day": _int_or_original(day),
                        "summary": data.get("day_summary"),
                        "started_minute": data.get("started_minute"),
                        "ended_minute": data.get("ended_minute"),
                        "source": {"artifact": "snapshot", "section": f"residents.{npc_id}.day_plans.{day}.day_summary"},
                    }
                )
    return rows


def _lifecycle_anomalies(snapshot: dict[str, object], validation: dict[str, object]) -> list[dict[str, object]]:
    rows = []
    for npc_id, resident in sorted(_mapping(snapshot.get("residents")).items()):
        for day, plan in sorted(_mapping(_mapping(resident).get("day_plans")).items()):
            for index, item in enumerate(_list(_mapping(plan).get("lifecycle_anomalies"))):
                if isinstance(item, dict):
                    rows.append(
                        {
                            **item,
                            "resident_id": npc_id,
                            "day": _int_or_original(day),
                            "source": {
                                "artifact": "snapshot",
                                "section": f"residents.{npc_id}.day_plans.{day}.lifecycle_anomalies",
                                "index": index,
                            },
                        }
                    )
    for index, item in enumerate(_list(validation.get("lifecycle_warnings"))):
        if isinstance(item, dict):
            rows.append({**item, "source": {"artifact": "validation", "section": "lifecycle_warnings", "index": index}})
    return rows


def _warnings(validation: dict[str, object], diagnostics: dict[str, object]) -> list[dict[str, object]]:
    rows = []
    for section in ("lifecycle_warnings", "warnings"):
        for index, item in enumerate(_list(validation.get(section))):
            if isinstance(item, dict):
                rows.append({**item, "source": {"artifact": "validation", "section": section, "index": index}})
    for index, item in enumerate(_list(_get(diagnostics, "action_lifecycle", "warnings"))):
        if isinstance(item, dict):
            rows.append({**item, "source": {"artifact": "diagnostics", "section": "action_lifecycle.warnings", "index": index}})
    return rows


def _resume_markers(diagnostics: dict[str, object]) -> list[dict[str, object]]:
    resume = diagnostics.get("resume") if isinstance(diagnostics, dict) else None
    if not isinstance(resume, dict):
        return []
    return [{**resume, "source": {"artifact": "diagnostics", "section": "resume"}}]


def _final_resident_states(snapshot: dict[str, object]) -> dict[str, dict[str, object]]:
    states = {}
    current_actions = _mapping(snapshot.get("current_actions"))
    schedules = _mapping(snapshot.get("schedules"))
    completed = _mapping(_mapping(snapshot.get("semantic_world")).get("completed_schedule_segments"))
    for npc_id, payload in sorted(_mapping(snapshot.get("residents")).items()):
        data = _mapping(payload)
        states[str(npc_id)] = {
            "location_id": data.get("location_id"),
            "lifecycle_status": data.get("lifecycle_status"),
            "current_action": current_actions.get(npc_id),
            "schedule_count": len(_list(schedules.get(npc_id))),
            "completed_schedule_count": len(_list(completed.get(npc_id))),
            "has_anomalies": any(
                _list(_mapping(plan).get("lifecycle_anomalies"))
                for plan in _mapping(data.get("day_plans")).values()
            ),
            "source": {"artifact": "snapshot", "section": f"residents.{npc_id}"},
        }
    return states


def _artifact_provenance(
    run_dir: Path,
    manifest_path: Path,
    manifest: dict[str, object],
    resolved: dict[str, object],
    diagnostics_path: Path | None,
    validation_path: Path | None,
) -> dict[str, object]:
    replay_paths = _path_mapping(resolved.get("replay_paths", {}))
    presentation = manifest.get("presentation_paths", {})
    return {
        "manifest": _provenance(run_dir, manifest_path),
        "latest_snapshot": _provenance(run_dir, resolved.get("latest_snapshot_path")),
        "step_snapshots": [_provenance(run_dir, item) for item in _list(resolved.get("step_snapshot_paths"))],
        "replay_paths": {name: _provenance(run_dir, path) for name, path in sorted(replay_paths.items())},
        "diagnostics": _provenance(run_dir, diagnostics_path or run_dir / "diagnostics.json"),
        "validation": _provenance(run_dir, validation_path or run_dir / "validation.json"),
        "presentation_paths": presentation if isinstance(presentation, dict) else {},
    }


def _diagnostics_summary(diagnostics: dict[str, object]) -> dict[str, object]:
    if not isinstance(diagnostics, dict):
        return {}
    return {
        "ticks": diagnostics.get("ticks", {}),
        "actions": diagnostics.get("actions", {}),
        "schedule_evidence": diagnostics.get("schedule_evidence", {}),
        "validation": diagnostics.get("validation", {}),
    }


def _source(name: str, path: Path | None, line: int | None = None) -> dict[str, object]:
    source: dict[str, object] = {"artifact": name}
    if path is not None:
        source["path"] = str(path)
    if line is not None:
        source["line"] = line
    return source


def _provenance(run_dir: Path, path: object) -> dict[str, object] | None:
    if not isinstance(path, Path):
        return None
    item: dict[str, object] = {"path": _relative_or_external(run_dir, path), "exists": path.exists()}
    return item


def _path_mapping(payload: object) -> dict[str, Path]:
    if not isinstance(payload, dict):
        return {}
    return {str(key): value for key, value in payload.items() if isinstance(value, Path)}


def _resolve_optional_manifest_path(run_dir: Path, manifest: dict[str, object], key: str) -> Path | None:
    if key not in manifest:
        return None
    return resolve_manifest_path(run_dir, manifest.get(key))


def _read_json(path: Path | None) -> dict[str, object] | None:
    if path is None or not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else None


def _read_jsonl(path: Path | None) -> list[dict[str, object]]:
    if path is None or not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _first_checkpoint_snapshot(checkpoints: list[dict[str, object]]) -> dict[str, object] | None:
    for row in checkpoints:
        snapshot = row.get("snapshot")
        if isinstance(snapshot, dict):
            return snapshot
    return None


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _get(payload: object, *keys: str) -> object:
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _sort_int(value: object) -> int:
    return value if isinstance(value, int) else 10**9


def _int_or_original(value: object) -> object:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return value


def _time_label(day: object, minute: object) -> str:
    if isinstance(minute, int):
        hours, minutes = divmod(minute, 60)
        if isinstance(day, int):
            return f"Day {day} {hours:02d}:{minutes:02d}"
        return f"{hours:02d}:{minutes:02d}"
    return ""


def _relative_or_external(run_dir: Path, path: Path) -> object:
    try:
        return str(path.resolve().relative_to(run_dir.resolve()))
    except ValueError:
        return {"external": True, "path": str(path)}


def _viewer_html() -> str:
    title = html.escape("TownWorld Replay Viewer")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{ color-scheme: light; font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    body {{ margin: 0; background: #f7f7f4; color: #20221f; }}
    header {{ padding: 18px 24px; border-bottom: 1px solid #deded8; background: #ffffff; position: sticky; top: 0; z-index: 2; }}
    h1 {{ margin: 0; font-size: 20px; letter-spacing: 0; }}
    main {{ display: grid; grid-template-columns: 320px minmax(0, 1fr) 360px; min-height: calc(100vh - 62px); }}
    aside, section {{ padding: 18px; overflow: auto; }}
    aside {{ border-right: 1px solid #deded8; background: #ffffff; }}
    section.detail {{ border-left: 1px solid #deded8; background: #ffffff; }}
    button {{ width: 100%; text-align: left; border: 1px solid #d7d7d0; background: #fff; padding: 10px; margin: 0 0 8px; border-radius: 6px; cursor: pointer; }}
    button.active {{ border-color: #2f6f73; box-shadow: inset 3px 0 0 #2f6f73; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
    .panel {{ border: 1px solid #d9d9d2; border-radius: 8px; padding: 12px; background: #fff; }}
    .muted {{ color: #666b62; font-size: 13px; }}
    .warning {{ color: #8a4b00; font-weight: 600; }}
    pre {{ white-space: pre-wrap; word-break: break-word; background: #f0f0eb; padding: 10px; border-radius: 6px; max-height: 420px; overflow: auto; }}
    @media (max-width: 920px) {{ main {{ grid-template-columns: 1fr; }} aside, section.detail {{ border: 0; }} }}
  </style>
</head>
<body>
  <header><h1>TownWorld Replay</h1><div id="run" class="muted"></div></header>
  <main>
    <aside><div id="timeline"></div></aside>
    <section><h2 id="time">Loading</h2><div id="town" class="grid"></div><h2>Feed</h2><div id="feed"></div></section>
    <section class="detail"><h2>Details</h2><div id="details"></div></section>
  </main>
  <script>
    const state = {{ model: null, selected: 0 }};
    fetch('replay_read_model.json').then(r => r.json()).then(model => {{
      state.model = model;
      document.getElementById('run').textContent = `${{model.run.run_id || ''}} · ${{model.run.scenario?.name || model.run.scenario?.id || ''}}`;
      render();
    }});
    function render() {{
      const model = state.model;
      const events = model.timeline_events || [];
      const selected = events[state.selected] || events[0] || {{}};
      const frame = frameFor(selected);
      document.getElementById('timeline').innerHTML = events.map((event, index) =>
        `<button class="${{index === state.selected ? 'active' : ''}}" onclick="state.selected=${{index}};render()">
          <strong>${{event.time || event.type}}</strong><br><span class="muted">${{event.type}}</span><br>${{escapeHtml(event.summary || '')}}
        </button>`).join('');
      document.getElementById('time').textContent = selected.time || frame?.time || 'Town state';
      renderTown(frame);
      renderFeed(selected);
      renderDetails(selected, frame);
    }}
    function frameFor(event) {{
      const frames = state.model.world_frames || [];
      let best = frames[0];
      for (const frame of frames) {{
        if ((frame.day ?? 0) <= (event.day ?? 999999) && (frame.minute ?? 0) <= (event.minute ?? 999999)) best = frame;
      }}
      return best;
    }}
    function renderTown(frame) {{
      const model = state.model;
      const residents = Object.entries(frame?.residents || {{}});
      const byLocation = new Map((frame?.locations || []).map(item => [item.location_id, item.resident_ids || []]));
      document.getElementById('town').innerHTML = (model.locations || []).map(location => {{
        const ids = byLocation.get(location.id) || [];
        const residentRows = ids.map(id => {{
          const r = frame.residents[id] || {{}};
          const action = r.current_action ? `${{r.current_action.action_type}} · ${{r.current_action.status}}` : 'idle';
          const schedule = r.active_schedule_segment ? r.active_schedule_segment.intent : '';
          return `<li><strong>${{id}}</strong><br><span class="muted">${{action}}${{schedule ? ' · ' + escapeHtml(schedule) : ''}}</span></li>`;
        }}).join('');
        return `<div class="panel"><h3>${{escapeHtml(location.name || location.id)}}</h3><div class="muted">${{escapeHtml(location.description || '')}}</div><ul>${{residentRows}}</ul></div>`;
      }}).join('') || residents.map(([id, r]) => `<div class="panel"><strong>${{id}}</strong><div class="muted">${{r.location_id}}</div></div>`).join('');
    }}
    function renderFeed(selected) {{
      const events = state.model.timeline_events || [];
      const nearby = events.filter(event => event.day === selected.day && Math.abs((event.minute ?? 0) - (selected.minute ?? 0)) <= 30).slice(0, 20);
      document.getElementById('feed').innerHTML = nearby.map(event => `<div class="panel"><strong>${{event.type}}</strong><div>${{escapeHtml(event.summary || '')}}</div><div class="muted">${{event.time || ''}}</div></div>`).join('');
    }}
    function renderDetails(selected, frame) {{
      const model = state.model;
      const panels = [
        ['Selected event', selected],
        ['Frame', frame],
        ['Schedules', model.schedules],
        ['Planning', model.planning_evidence],
        ['Reflections', model.reflections],
        ['Day summaries', model.day_summaries],
        ['Lifecycle anomalies', model.lifecycle_anomalies],
        ['Resume markers', model.resume_markers],
        ['Warnings', model.warnings],
        ['Sources', model.artifacts],
      ];
      document.getElementById('details').innerHTML = panels.map(([label, value]) => `<h3>${{label}}</h3><pre>${{escapeHtml(JSON.stringify(value, null, 2))}}</pre>`).join('');
    }}
    function escapeHtml(value) {{
      return String(value).replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
    }}
  </script>
</body>
</html>
"""

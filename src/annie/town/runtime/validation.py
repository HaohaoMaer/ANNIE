"""Stable runtime validation helpers for TownWorld resume behavior."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from annie.town.engine import TownWorldEngine
from annie.town.content import load_town_scenario, validate_scaled_town_scenario
from annie.town.runtime.runner import (
    TownAgentFactory,
    TownRuntimeConfig,
    TownRuntimeResult,
    run_town_runtime,
)


@dataclass(frozen=True)
class ResumeContinuationValidation:
    ok: bool
    continuous: TownRuntimeResult
    resumed: TownRuntimeResult
    continuous_signature: dict[str, object]
    resumed_signature: dict[str, object]
    differences: list[str]


@dataclass(frozen=True)
class DeterministicLongRunValidation:
    ok: bool
    result: TownRuntimeResult
    diagnostics: dict[str, object]
    failed_checks: list[str]
    lifecycle_warnings: list[dict[str, object]]


@dataclass(frozen=True)
class DeterministicScaleValidation:
    ok: bool
    result: TownRuntimeResult
    diagnostics: dict[str, object]
    scenario_report: object
    failed_checks: list[str]
    behavior_warnings: list[dict[str, object]]


def validate_deterministic_scale_run(
    *,
    run_root: Path,
    scenario_path: Path,
    run_id: str = "deterministic-scale-run",
    npc_ids: list[str] | None = None,
    days: int = 1,
    start_minute: int = 8 * 60,
    end_minute: int = 10 * 60,
    max_ticks_per_day: int = 16,
    agent_factory: TownAgentFactory | None = None,
) -> DeterministicScaleValidation:
    scenario = load_town_scenario(scenario_path)
    checked_residents = npc_ids or sorted(scenario.state.residents)[:8]
    report = validate_scaled_town_scenario(
        scenario,
        representative_resident_ids=checked_residents,
    )
    result = run_town_runtime(
        TownRuntimeConfig(
            run_id=run_id,
            run_root=run_root,
            scenario_path=scenario_path,
            npc_ids=checked_residents,
            days=days,
            start_minute=start_minute,
            end_minute=end_minute,
            max_ticks_per_day=max_ticks_per_day,
            finalize_day=False,
            agent_mode="deterministic",
        ),
        agent_factory=agent_factory,
    )
    diagnostics = result.diagnostics
    failed_checks = _scale_failed_checks(result, checked_residents)
    behavior_warnings = _scale_behavior_warnings(result)
    return DeterministicScaleValidation(
        ok=not failed_checks,
        result=result,
        diagnostics=diagnostics,
        scenario_report=report,
        failed_checks=failed_checks,
        behavior_warnings=behavior_warnings,
    )


def validate_deterministic_long_run(
    *,
    run_root: Path,
    scenario_path: Path,
    run_id: str = "deterministic-long-run",
    npc_ids: list[str] | None = None,
    days: int = 2,
    start_minute: int = 8 * 60,
    end_minute: int = 10 * 60,
    max_ticks_per_day: int = 24,
    agent_factory: TownAgentFactory | None = None,
) -> DeterministicLongRunValidation:
    result = run_town_runtime(
        TownRuntimeConfig(
            run_id=run_id,
            run_root=run_root,
            scenario_path=scenario_path,
            npc_ids=npc_ids,
            days=days,
            start_minute=start_minute,
            end_minute=end_minute,
            max_ticks_per_day=max_ticks_per_day,
            finalize_day=True,
            agent_mode="deterministic",
        ),
        agent_factory=agent_factory,
    )
    validation = result.diagnostics.get("validation", {})
    checks = validation.get("checks", {}) if isinstance(validation, dict) else {}
    failed_checks = [
        key
        for key, value in sorted(checks.items())
        if key
        in {
            "runner_completed",
            "multiple_residents",
            "multiple_days",
            "fixed_tick_advancement",
            "schedule_execution_observed",
            "reflection_or_day_summary_observed",
            "loop_guard_failures_absent",
            "lifecycle_warnings_absent",
        }
        and not value
    ]
    lifecycle_warnings = validation.get("lifecycle_warnings", [])
    if not isinstance(lifecycle_warnings, list):
        lifecycle_warnings = []
    return DeterministicLongRunValidation(
        ok=not failed_checks and result.diagnostics["validation"]["status"] == "pass",
        result=result,
        diagnostics=result.diagnostics,
        failed_checks=failed_checks,
        lifecycle_warnings=[
            item for item in lifecycle_warnings if isinstance(item, dict)
        ],
    )


def extract_behavior_signature(engine: TownWorldEngine) -> dict[str, object]:
    npc_ids = sorted(engine.state.resident_ids())
    return {
        "clock": {
            "day": engine.state.clock.day,
            "minute": engine.state.clock.minute,
        },
        "resident_locations": {
            npc_id: engine.state.location_id_for(npc_id) for npc_id in npc_ids
        },
        "schedule_state": {
            npc_id: {
                "schedule": [
                    {
                        "day": segment.day,
                        "start_minute": segment.start_minute,
                        "duration_minutes": segment.duration_minutes,
                        "location_id": segment.location_id,
                        "intent": segment.intent,
                    }
                    for segment in engine.state.schedule_for(npc_id)
                ],
                "completed": [
                    {
                        "day": item.day,
                        "start_minute": item.start_minute,
                        "location_id": item.location_id,
                    }
                    for item in engine.state.completed_schedule_segments.get(npc_id, [])
                ],
            }
            for npc_id in npc_ids
        },
        "active_actions": {
            npc_id: _current_action_signature(npc_id, engine) for npc_id in npc_ids
        },
        "action_lifecycle": _action_lifecycle_signature(engine),
        "conversation_state": {
            session_id: {
                "participants": list(session.participants),
                "status": session.status,
                "turn_count": len(session.turns),
                "ended_minute": session.ended_minute,
            }
            for session_id, session in sorted(engine.state.conversation_sessions.items())
        },
        "conversation_cooldowns": {
            key: engine.state.conversation_cooldowns[key]
            for key in sorted(engine.state.conversation_cooldowns)
        },
        "loop_guards": [
            {
                "npc_id": item.get("npc_id"),
                "guard_type": item.get("guard_type"),
                "day": item.get("day"),
                "minute": item.get("minute"),
            }
            for item in engine.loop_guard_events
        ],
        "memory_evidence": {
            npc_id: {
                category: len(engine.memory_for(npc_id).grep("", category=category, k=20))
                for category in ("semantic", "reflection", "impression", "todo")
            }
            for npc_id in npc_ids
        },
        "replay_checkpoint_shape": _replay_checkpoint_shape(engine),
    }


def validate_resume_continuation(
    *,
    run_root: Path,
    scenario_path: Path,
    split_minute: int,
    end_minute: int,
    max_ticks_per_day: int = 120,
    agent_factory: TownAgentFactory | None = None,
) -> ResumeContinuationValidation:
    continuous = run_town_runtime(
        TownRuntimeConfig(
            run_id="continuous",
            run_root=run_root,
            scenario_path=scenario_path,
            end_minute=end_minute,
            max_ticks_per_day=max_ticks_per_day,
            finalize_day=False,
        ),
        agent_factory=agent_factory,
    )
    run_town_runtime(
        TownRuntimeConfig(
            run_id="resumed",
            run_root=run_root,
            scenario_path=scenario_path,
            end_minute=split_minute,
            max_ticks_per_day=max_ticks_per_day,
            finalize_day=False,
        ),
        agent_factory=agent_factory,
    )
    resumed = run_town_runtime(
        TownRuntimeConfig(
            run_id="resumed",
            run_root=run_root,
            scenario_path=scenario_path,
            resume=True,
            end_minute=end_minute,
            max_ticks_per_day=max_ticks_per_day,
            finalize_day=False,
        ),
        agent_factory=agent_factory,
    )
    continuous_signature = extract_behavior_signature(continuous.engine)
    resumed_signature = extract_behavior_signature(resumed.engine)
    differences = _signature_differences(continuous_signature, resumed_signature)
    return ResumeContinuationValidation(
        ok=not differences,
        continuous=continuous,
        resumed=resumed,
        continuous_signature=continuous_signature,
        resumed_signature=resumed_signature,
        differences=differences,
    )


def _scale_failed_checks(
    result: TownRuntimeResult,
    checked_residents: list[str],
) -> list[str]:
    failed: list[str] = []
    diagnostics = result.diagnostics
    validation = diagnostics.get("validation", {})
    if not isinstance(validation, dict) or validation.get("status") == "fail":
        failed.append("runtime_validation_status")
    if not result.persistence_paths.get("manifest") or not result.persistence_paths["manifest"].exists():
        failed.append("manifest_written")
    if not result.persistence_paths.get("latest_snapshot") or not result.persistence_paths["latest_snapshot"].exists():
        failed.append("latest_snapshot_written")
    if not result.replay_paths.get("checkpoints") or not result.replay_paths["checkpoints"].exists():
        failed.append("replay_checkpoints_written")
    if not result.diagnostics_path.exists():
        failed.append("diagnostics_written")
    if any(
        str(_facts(action).get("reason", "")).startswith("unknown_")
        or str(_facts(action).get("reason", "")) == "unreachable_destination"
        for action in result.engine.action_log
    ):
        failed.append("no_unreported_invalid_routes")
    action_count = max(1, len(result.engine.action_log))
    failed_count = sum(
        1
        for action in result.engine.action_log
        if str(action.get("status", "")).lower() not in {"ok", "success", "succeeded", "done"}
    )
    if failed_count / action_count > 0.35:
        failed.append("bounded_failed_action_rate")
    if len(result.engine.loop_guard_events) > max(2, len(checked_residents) // 2):
        failed.append("bounded_loop_guard_count")
    scale = diagnostics.get("scale", {})
    resident_inspection = scale.get("resident_inspection", {}) if isinstance(scale, dict) else {}
    if not isinstance(resident_inspection, dict) or not all(
        npc_id in resident_inspection for npc_id in checked_residents
    ):
        failed.append("inspectable_schedule_progress")
    return failed


def _scale_behavior_warnings(result: TownRuntimeResult) -> list[dict[str, object]]:
    warnings: list[dict[str, object]] = []
    schedule = result.diagnostics.get("schedule_evidence", {})
    if isinstance(schedule, dict) and int(schedule.get("unfinished_count", 0)) > 0:
        warnings.append(
            {
                "kind": "unfinished_schedule",
                "count": schedule.get("unfinished_count", 0),
            }
        )
    social = result.diagnostics.get("scale", {})
    if isinstance(social, dict):
        social_behavior = social.get("social_behavior", {})
        if (
            isinstance(social_behavior, dict)
            and social_behavior.get("conversation_session_count") == 0
        ):
            warnings.append({"kind": "no_conversations_observed"})
    if result.engine.loop_guard_events:
        warnings.append(
            {
                "kind": "loop_guards_observed",
                "count": len(result.engine.loop_guard_events),
            }
        )
    return warnings


def _facts(action: dict[str, object]) -> dict[str, object]:
    facts = action.get("facts", {})
    return facts if isinstance(facts, dict) else {}


def _current_action_signature(npc_id: str, engine: TownWorldEngine) -> dict[str, object] | None:
    action = engine.state.current_action_for(npc_id)
    if action is None:
        return None
    return {
        "action_type": action.action_type,
        "location_id": action.location_id,
        "start_minute": action.start_minute,
        "duration_minutes": action.duration_minutes,
        "end_minute": action.end_minute,
        "finalized_minute": action.finalized_minute,
        "status": action.status,
        "lifecycle_state": action.lifecycle_state,
        "effect_model": action.effect_model,
        "occupancy_model": action.occupancy_model,
        "effect_applied": action.effect_applied,
        "failure_reason": action.failure_reason,
        "interrupted_reason": action.interrupted_reason,
    }


def _action_lifecycle_signature(engine: TownWorldEngine) -> dict[str, object]:
    return {
        "finalized_actions": [
            {
                "tick": row.get("tick"),
                "minute": row.get("minute"),
                "count": len(row.get("finalized_actions", []))
                if isinstance(row.get("finalized_actions", []), list)
                else 0,
            }
            for row in engine.replay_log
        ],
        "action_rows": [
            {
                "npc_id": item.get("npc_id"),
                "action_type": item.get("action_type"),
                "status": item.get("status"),
                "lifecycle_state": item.get("lifecycle_state"),
                "start_minute": item.get("minute"),
                "end_minute": item.get("end_minute"),
                "next_available_minute": item.get("next_available_minute"),
            }
            for item in engine.action_log
        ],
    }


def _replay_checkpoint_shape(engine: TownWorldEngine) -> dict[str, object]:
    rows = engine.replay_log
    return {
        "count": len(rows),
        "ticks": [row.get("tick") for row in rows],
        "minutes": [row.get("minute") for row in rows],
        "has_snapshots": [isinstance(row.get("snapshot"), dict) for row in rows],
        "record_counts": [len(row.get("records", [])) for row in rows],
        "finalized_counts": [len(row.get("finalized_actions", [])) for row in rows],
        "restored_current_action_shapes": [
            sorted(
                row.get("current_action_lifecycle", {}).keys()
                if isinstance(row.get("current_action_lifecycle"), dict)
                else []
            )
            for row in rows
        ],
    }


def _signature_differences(left: dict[str, object], right: dict[str, object]) -> list[str]:
    differences: list[str] = []
    for key in sorted(set(left) | set(right)):
        if left.get(key) != right.get(key):
            differences.append(key)
    return differences

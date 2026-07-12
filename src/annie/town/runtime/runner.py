"""Consolidated function-based TownWorld runtime runner."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from annie.npc.core.context import AgentContext
from annie.npc.core.response import AgentResponse
from annie.npc.tools.base_tool import ToolContext
from annie.town.content import (
    apply_memory_seeds,
    default_small_town_scenario_path,
    load_town_scenario,
)
from annie.town.domain import TownPerceptionPolicy
from annie.town.engine import TownWorldEngine
from annie.town.persistence import (
    load_run_manifest,
    resolve_manifest_paths,
    write_json_atomic,
)
from annie.town.replay_viewer import write_town_replay_read_model, write_town_replay_viewer
from annie.town.runtime.multi_npc_runner import (
    TownAgent,
    TownMultiDayRunResult,
    run_multi_npc_day,
    run_multi_npc_days,
)

TownAgentFactory = Callable[["TownRuntimeConfig"], TownAgent]
_SUCCESS_STATUSES = {"ok", "success", "succeeded", "done"}


@dataclass
class TownRuntimeConfig:
    run_id: str
    scenario_path: Path = field(default_factory=default_small_town_scenario_path)
    run_root: Path = Path("runs/town")
    resume: bool = False
    npc_ids: list[str] | None = None
    days: int = 1
    start_minute: int = 8 * 60
    end_minute: int = 22 * 60
    max_ticks_per_day: int = 120
    agent_mode: Literal["deterministic", "real_llm"] = "deterministic"
    model_config_path: Path = Path("config/model_config.yaml")
    perception_policy: TownPerceptionPolicy | None = None
    write_replay_artifacts: bool = True
    write_presentation_artifacts: bool = True
    write_step_snapshots: bool = False
    write_validation: bool = True
    finalize_day: bool = True
    validation_options: dict[str, object] = field(default_factory=dict)

    @property
    def run_dir(self) -> Path:
        return self.run_root / self.run_id


@dataclass
class TownRuntimeResult:
    run_id: str
    run_dir: Path
    engine: TownWorldEngine
    replay_paths: dict[str, Path]
    presentation_paths: dict[str, Path]
    persistence_paths: dict[str, Path]
    diagnostics_path: Path
    diagnostics: dict[str, object]
    resumed: bool
    validation_path: Path | None = None


@dataclass
class ResumeMetadata:
    source_manifest: Path
    source_snapshot: Path
    restored_day: int
    restored_minute: int
    restored_current_actions: dict[str, dict[str, object]] = field(default_factory=dict)
    first_continued_tick: int | None = None

    def to_dict(self, run_dir: Path) -> dict[str, object]:
        return {
            "source_manifest": _relative_or_external(run_dir, self.source_manifest),
            "source_snapshot": _relative_or_external(run_dir, self.source_snapshot),
            "restored_time": {
                "day": self.restored_day,
                "minute": self.restored_minute,
            },
            "restored_current_actions": self.restored_current_actions,
            "first_continued_tick": self.first_continued_tick,
        }


class DeterministicTownAgent:
    """Small stateless tool-driving agent for deterministic runtime runs."""

    def run(self, context: AgentContext) -> AgentResponse:
        town = context.extra["town"]
        if town.get("conversation_session_id"):
            return AgentResponse(dialogue="好的。")
        tool_context = ToolContext(agent_context=context, runtime={})
        npc_id = context.npc_id
        location = str(town["location_id"])
        target = str(town["current_schedule_target_location_id"])
        exits = [str(item) for item in town["exits"]]
        object_ids = [str(item) for item in town["object_ids"]]
        visible_npcs = [str(item) for item in town["visible_npc_ids"]]

        if npc_id == "clara" and location == "library" and "bookshelf" in object_ids:
            _tool(context, "interact_with").safe_call(
                {"object_id": "bookshelf", "intent": "整理归还书籍"},
                tool_context,
            )
            _tool(context, "complete_current_schedule").safe_call(
                {"note": "书籍已经整理完毕"},
                tool_context,
            )
            return AgentResponse()

        if npc_id == "alice" and location == "home_alice" and "breakfast_table" in object_ids:
            _tool(context, "interact_with").safe_call(
                {"object_id": "breakfast_table", "intent": "吃早餐"},
                tool_context,
            )
            _tool(context, "complete_current_schedule").safe_call(
                {"note": "早餐已完成"},
                tool_context,
            )
            return AgentResponse()

        if npc_id == "alice" and location == "cafe" and "bob" in visible_npcs:
            _tool(context, "talk_to").safe_call(
                {"target_npc_id": "bob", "topic_or_reason": "我来买一杯咖啡。"},
                tool_context,
            )
            _tool(context, "complete_current_schedule").safe_call(
                {"note": "已经到咖啡馆并向 Bob 点单"},
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
            _tool(context, "move_to").safe_call({"destination_id": target}, tool_context)
        elif exits:
            _tool(context, "move_to").safe_call({"destination_id": exits[0]}, tool_context)
        return AgentResponse()


def create_town_engine_for_new_run(config: TownRuntimeConfig) -> tuple[TownWorldEngine, dict[str, object]]:
    scenario = load_town_scenario(config.scenario_path)
    run_dir = config.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    engine = TownWorldEngine(
        scenario.state,
        memory_path=run_dir / "vector_store",
        history_dir=run_dir / "history",
        perception_policy=config.perception_policy,
    )
    apply_memory_seeds(scenario, engine.memory_for)
    metadata = {
        "scenario": {
            "id": scenario.id,
            "name": scenario.name,
            "schema_version": 1,
            "path": str(Path(config.scenario_path)),
            "memory_seed_count": len(scenario.memory_seeds),
        }
    }
    return engine, metadata


def resume_town_engine(config: TownRuntimeConfig) -> tuple[TownWorldEngine, ResumeMetadata]:
    manifest_path = config.run_dir / "manifest.json"
    manifest = load_run_manifest(manifest_path)
    resolved = resolve_manifest_paths(config.run_dir, manifest)
    latest_snapshot = resolved["latest_snapshot_path"]
    if not isinstance(latest_snapshot, Path):
        raise ValueError("manifest latest_snapshot_path did not resolve to a path")
    engine = TownWorldEngine.resume_run(manifest_path)
    return engine, ResumeMetadata(
        source_manifest=manifest_path,
        source_snapshot=latest_snapshot,
        restored_day=engine.state.clock.day,
        restored_minute=engine.state.clock.minute,
        restored_current_actions={
            npc_id: {
                "action_type": action.action_type,
                "start_minute": action.start_minute,
                "duration_minutes": action.duration_minutes,
                "end_minute": action.end_minute,
                "status": action.status,
                "lifecycle_state": action.lifecycle_state,
            }
            for npc_id, action in sorted(engine.state.current_actions.items())
        },
    )


def run_town_runtime(
    config: TownRuntimeConfig,
    *,
    agent_factory: TownAgentFactory | None = None,
) -> TownRuntimeResult:
    run_dir = config.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    resume_metadata: ResumeMetadata | None = None
    scenario_metadata: dict[str, object]
    if config.resume:
        engine, resume_metadata = resume_town_engine(config)
        scenario_metadata = {"scenario": {"path": str(Path(config.scenario_path))}}
    else:
        engine, scenario_metadata = create_town_engine_for_new_run(config)

    first_tick_before = len(engine.replay_log) + 1
    agent = agent_factory(config) if agent_factory is not None else _default_agent(config)
    run_result = _run_bounded_window(engine, agent, config)
    if resume_metadata is not None:
        resume_metadata.first_continued_tick = (
            first_tick_before if len(engine.replay_log) >= first_tick_before else None
        )

    replay_paths: dict[str, Path] = {}
    if config.write_replay_artifacts:
        replay_paths = engine.write_replay_artifacts(run_dir / "replay")
    presentation_paths: dict[str, Path] = {}
    if config.write_presentation_artifacts:
        presentation_paths = {
            "read_model": run_dir / "presentation" / "replay_read_model.json",
            "viewer": run_dir / "viewer" / "index.html",
            "viewer_read_model": run_dir / "viewer" / "replay_read_model.json",
        }

    diagnostics = _build_diagnostics(
        config,
        engine,
        run_result,
        replay_paths=replay_paths,
        presentation_paths=presentation_paths,
        persistence_paths={},
        scenario_metadata=scenario_metadata,
        resume_metadata=resume_metadata,
    )
    validation_path: Path | None = None
    if config.write_validation:
        validation_path = write_json_atomic(run_dir / "validation.json", diagnostics["validation"])
    persistence_paths = engine.save_run(
        run_dir,
        run_id=config.run_id,
        replay_paths=replay_paths,
        write_step_snapshot=config.write_step_snapshots,
        model_summary=diagnostics["model"],
        validation=diagnostics["validation"],
        diagnostics_path=run_dir / "diagnostics.json",
        validation_path=validation_path,
        presentation_paths=presentation_paths,
    )
    diagnostics = _build_diagnostics(
        config,
        engine,
        run_result,
        replay_paths=replay_paths,
        presentation_paths=presentation_paths,
        persistence_paths=persistence_paths,
        scenario_metadata=scenario_metadata,
        resume_metadata=resume_metadata,
    )
    diagnostics_path = write_json_atomic(run_dir / "diagnostics.json", diagnostics)
    if config.write_validation:
        validation_path = write_json_atomic(run_dir / "validation.json", diagnostics["validation"])
    if config.write_presentation_artifacts:
        read_model_path = write_town_replay_read_model(
            persistence_paths["manifest"],
            presentation_paths["read_model"],
        )
        viewer_paths = write_town_replay_viewer(
            persistence_paths["manifest"],
            run_dir / "viewer",
            read_model_path=read_model_path,
        )
        presentation_paths = {
            "read_model": read_model_path,
            "viewer": viewer_paths["viewer_index"],
            **viewer_paths,
        }
        persistence_paths = engine.save_run(
            run_dir,
            run_id=config.run_id,
            replay_paths=replay_paths,
            write_step_snapshot=config.write_step_snapshots,
            model_summary=diagnostics["model"],
            validation=diagnostics["validation"],
            diagnostics_path=diagnostics_path,
            validation_path=validation_path,
            presentation_paths=presentation_paths,
        )
        diagnostics = _build_diagnostics(
            config,
            engine,
            run_result,
            replay_paths=replay_paths,
            presentation_paths=presentation_paths,
            persistence_paths=persistence_paths,
            scenario_metadata=scenario_metadata,
            resume_metadata=resume_metadata,
        )
        _add_presentation_validation(diagnostics, read_model_path, presentation_paths)
        diagnostics_path = write_json_atomic(run_dir / "diagnostics.json", diagnostics)
        if config.write_validation:
            validation_path = write_json_atomic(run_dir / "validation.json", diagnostics["validation"])
        persistence_paths = engine.save_run(
            run_dir,
            run_id=config.run_id,
            replay_paths=replay_paths,
            write_step_snapshot=config.write_step_snapshots,
            model_summary=diagnostics["model"],
            validation=diagnostics["validation"],
            diagnostics_path=diagnostics_path,
            validation_path=validation_path,
            presentation_paths=presentation_paths,
        )

    return TownRuntimeResult(
        run_id=config.run_id,
        run_dir=run_dir,
        engine=engine,
        replay_paths=replay_paths,
        presentation_paths=presentation_paths,
        persistence_paths=persistence_paths,
        diagnostics_path=diagnostics_path,
        diagnostics=diagnostics,
        resumed=config.resume,
        validation_path=validation_path,
    )


def _run_bounded_window(
    engine: TownWorldEngine,
    agent: TownAgent,
    config: TownRuntimeConfig,
) -> Any:
    npc_ids = config.npc_ids or engine.state.resident_ids()
    if config.validation_options.get("full_day_validation") and config.agent_mode == "real_llm":
        return _run_full_day_real_llm_validation(engine, agent, npc_ids, config)
    if config.resume:
        return run_multi_npc_day(
            engine,
            agent,
            npc_ids,
            start_minute=None,
            end_minute=config.end_minute,
            max_ticks=config.max_ticks_per_day,
        )
    if not config.finalize_day:
        return run_multi_npc_day(
            engine,
            agent,
            npc_ids,
            start_minute=config.start_minute,
            end_minute=config.end_minute,
            max_ticks=config.max_ticks_per_day,
        )
    return run_multi_npc_days(
        engine,
        agent,
        npc_ids,
        days=max(1, config.days),
        start_minute=config.start_minute,
        end_minute=config.end_minute,
        max_ticks_per_day=config.max_ticks_per_day,
    )


def _run_full_day_real_llm_validation(
    engine: TownWorldEngine,
    agent: TownAgent,
    npc_ids: list[str],
    config: TownRuntimeConfig,
) -> TownMultiDayRunResult:
    day_results = []
    note = ""
    for offset in range(max(1, config.days)):
        day = offset + 1
        engine.start_day_for_residents(
            npc_ids,
            day=day,
            start_minute=config.start_minute,
            end_minute=config.end_minute,
        )
        for npc_id in npc_ids:
            engine.generate_day_plan_for_resident(
                npc_id,
                agent,
                start_minute=config.start_minute,
                end_minute=config.end_minute,
            )
        result = run_multi_npc_day(
            engine,
            agent,
            npc_ids,
            start_minute=config.start_minute,
            end_minute=config.end_minute,
            max_ticks=config.max_ticks_per_day,
        )
        day_results.append(result)
        engine.end_day_for_residents(npc_ids, day=day)
        if not result.ok:
            note = result.note
            break
    return TownMultiDayRunResult(npc_ids=npc_ids, days=day_results, note=note)


def _default_agent(config: TownRuntimeConfig) -> TownAgent:
    if config.agent_mode == "deterministic":
        return DeterministicTownAgent()
    if config.agent_mode == "real_llm":
        from annie.npc.agent import NPCAgent
        from annie.npc.model.config import load_model_config
        from annie.npc.model.llm import create_chat_model

        model_config = load_model_config(config.model_config_path)
        return NPCAgent(llm=create_chat_model(model_config))
    raise ValueError(f"unsupported town agent_mode: {config.agent_mode}")


def _build_diagnostics(
    config: TownRuntimeConfig,
    engine: TownWorldEngine,
    run_result: Any,
    *,
    replay_paths: dict[str, Path],
    presentation_paths: dict[str, Path],
    persistence_paths: dict[str, Path],
    scenario_metadata: dict[str, object],
    resume_metadata: ResumeMetadata | None,
) -> dict[str, object]:
    run_dir = config.run_dir
    tick_rows = _tick_rows(engine)
    validation = _runtime_validation_summary(config, engine, run_result, tick_rows)
    return {
        "run": {
            "run_id": config.run_id,
            "run_dir": str(run_dir),
            "resumed": config.resume,
            "parameters": {
                "npc_ids": config.npc_ids,
                "days": config.days,
                "start_minute": config.start_minute,
                "end_minute": config.end_minute,
                "max_ticks_per_day": config.max_ticks_per_day,
                "agent_mode": config.agent_mode,
                "finalize_day": config.finalize_day,
            },
        },
        **scenario_metadata,
        "model": {
            "agent_mode": config.agent_mode,
            "model_config_path": str(config.model_config_path)
            if config.agent_mode == "real_llm"
            else None,
        },
        "clock": {
            "day": engine.state.clock.day,
            "minute": engine.state.clock.minute,
        },
        "ticks": {
            "count": len(engine.replay_log),
            "rows": tick_rows,
            "ran_count": sum(len(row["ran_npc_ids"]) for row in tick_rows),
            "skipped_count": sum(len(row["skipped"]) for row in tick_rows),
        },
        "actions": _action_summary(engine.action_log),
        "schedule_revisions": {
            "count": len(getattr(engine, "_schedule_revisions", {})),
            "planning_checkpoint_count": len(engine.planning_log),
        },
        "schedule_evidence": _schedule_evidence_summary(engine),
        "action_lifecycle": _action_lifecycle_summary(engine, tick_rows),
        "loop_guards": {
            "count": len(engine.loop_guard_events),
            "events": list(engine.loop_guard_events),
        },
        "memory": {
            "seeded_by_scenario": scenario_metadata.get("scenario", {}).get("memory_seed_count", 0)
            if isinstance(scenario_metadata.get("scenario"), dict)
            else 0,
            "reflection_count": len(engine.reflection_log),
        },
        "scale": _scale_diagnostics(engine, tick_rows),
        "artifacts": {
            "manifest": _path_or_none(run_dir, persistence_paths.get("manifest")),
            "latest_snapshot": _path_or_none(run_dir, persistence_paths.get("latest_snapshot")),
            "replay_paths": {
                name: _relative_or_external(run_dir, path)
                for name, path in sorted(replay_paths.items())
            },
            "presentation_paths": {
                name: _relative_or_external(run_dir, path)
                for name, path in sorted(presentation_paths.items())
            },
            "history_path": _relative_or_external(run_dir, run_dir / "history"),
            "vector_store_path": _relative_or_external(run_dir, run_dir / "vector_store"),
            "validation_path": "validation.json",
        },
        "validation": validation,
        "resume": resume_metadata.to_dict(run_dir) if resume_metadata is not None else None,
    }


def _tick_rows(engine: TownWorldEngine) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in engine.replay_log:
        ran = [str(item) for item in row.get("ran_npc_ids", [])]
        reasons = row.get("skipped_reasons", {})
        if not isinstance(reasons, dict):
            reasons = {}
        skipped = [
            {
                "npc_id": str(npc_id),
                "reason": str(reasons.get(str(npc_id), "not_activated")),
                "lifecycle": _lifecycle_for(row, str(npc_id)),
            }
            for npc_id in row.get("skipped_npc_ids", [])
        ]
        rows.append(
            {
                "tick": row.get("tick"),
                "minute": row.get("minute"),
                "ran_npc_ids": ran,
                "skipped": skipped,
                "finalized_actions": list(row.get("finalized_actions", []))
                if isinstance(row.get("finalized_actions", []), list)
                else [],
                "schedule_evidence": list(row.get("schedule_evidence", []))
                if isinstance(row.get("schedule_evidence", []), list)
                else [],
            }
        )
    return rows


def _action_summary(action_log: list[dict[str, object]]) -> dict[str, object]:
    by_type: Counter[str] = Counter()
    by_resident: dict[str, Counter[str]] = defaultdict(Counter)
    failures: dict[str, Counter[str]] = defaultdict(Counter)
    for action in action_log:
        action_type = str(action.get("action_type", "unknown"))
        npc_id = str(action.get("npc_id", "unknown"))
        status = str(action.get("status", "unknown"))
        by_type[action_type] += 1
        by_resident[npc_id][action_type] += 1
        if status.lower() not in _SUCCESS_STATUSES:
            reason = str(_facts(action).get("reason", status))
            failures[action_type][reason] += 1
    return {
        "count": len(action_log),
        "by_type": dict(sorted(by_type.items())),
        "by_resident": {
            npc_id: dict(sorted(counter.items()))
            for npc_id, counter in sorted(by_resident.items())
        },
        "failures_by_resident": _failure_counts_by_resident(action_log),
        "failures": {
            action_type: dict(sorted(counter.items()))
            for action_type, counter in sorted(failures.items())
        },
    }


def _failure_counts_by_resident(action_log: list[dict[str, object]]) -> dict[str, dict[str, int]]:
    failures: dict[str, Counter[str]] = defaultdict(Counter)
    for action in action_log:
        status = str(action.get("status", "unknown"))
        if status.lower() in _SUCCESS_STATUSES:
            continue
        npc_id = str(action.get("npc_id", "unknown"))
        reason = str(_facts(action).get("reason", action.get("failure_reason") or status))
        failures[npc_id][reason] += 1
    return {
        npc_id: dict(sorted(counter.items()))
        for npc_id, counter in sorted(failures.items())
    }


def _action_lifecycle_summary(
    engine: TownWorldEngine,
    tick_rows: list[dict[str, object]],
) -> dict[str, object]:
    lifecycle_counts: Counter[str] = Counter()
    finalized_counts: Counter[str] = Counter()
    next_available: dict[str, int] = {}
    due_finalizations = 0
    in_progress_skips = 0
    for action in engine.action_log:
        lifecycle_counts[str(action.get("lifecycle_state", "unknown"))] += 1
        npc_id = str(action.get("npc_id", "unknown"))
        value = action.get("next_available_minute")
        if isinstance(value, int):
            next_available[npc_id] = value
    for row in tick_rows:
        finalized_actions = row.get("finalized_actions", [])
        due_finalizations += len(finalized_actions)
        if isinstance(finalized_actions, list):
            for action in finalized_actions:
                if isinstance(action, dict):
                    finalized_counts[str(action.get("lifecycle_state", "unknown"))] += 1
        for skipped in row.get("skipped", []):
            if isinstance(skipped, dict) and skipped.get("reason") == "action_in_progress":
                in_progress_skips += 1
    return {
        "counts": dict(sorted(lifecycle_counts.items())),
        "submitted_counts": dict(sorted(lifecycle_counts.items())),
        "finalized_counts": dict(sorted(finalized_counts.items())),
        "in_progress_skips": in_progress_skips,
        "due_finalizations": due_finalizations,
        "next_available_minutes": dict(sorted(next_available.items())),
        "warnings": _action_lifecycle_warnings(engine, tick_rows),
    }


def _runtime_validation_summary(
    config: TownRuntimeConfig,
    engine: TownWorldEngine,
    run_result: Any,
    tick_rows: list[dict[str, object]],
) -> dict[str, object]:
    lifecycle_warnings = _action_lifecycle_warnings(engine, tick_rows)
    note = str(getattr(run_result, "note", ""))
    checks = {
        "runner_completed": not note,
        "multiple_residents": len(config.npc_ids or engine.state.resident_ids()) >= 2,
        "multiple_days": config.days >= 2 if config.finalize_day else False,
        "fixed_tick_advancement": _fixed_tick_advancement_ok(engine),
        "action_blocking_observed": any(
            skipped.get("reason") == "action_in_progress"
            for row in tick_rows
            for skipped in row.get("skipped", [])
            if isinstance(skipped, dict)
        ),
        "schedule_execution_observed": any(
            engine.state.completed_schedule_segments.get(npc_id)
            for npc_id in engine.state.resident_ids()
        )
        or bool(_schedule_evidence_summary(engine)["overdue_count"]),
        "conversation_cooldowns_reported": bool(engine.state.conversation_cooldowns)
        or config.agent_mode == "real_llm",
        "reflection_or_day_summary_observed": _has_day_summary_memory(engine),
        "loop_guard_failures_absent": not any(
            item.get("guard_type") == "unhandled_loop_failure"
            for item in engine.loop_guard_events
        ),
        "resume_metadata_reported": not config.resume,
        "lifecycle_warnings_absent": not lifecycle_warnings,
    }
    status = "pass" if checks["runner_completed"] and not lifecycle_warnings else "fail"
    return {
        "status": status,
        "note": note,
        "options": dict(config.validation_options),
        "checks": checks,
        "lifecycle_warnings": lifecycle_warnings,
    }


def _fixed_tick_advancement_ok(engine: TownWorldEngine) -> bool:
    rows = [
        row
        for row in engine.replay_log
        if isinstance(row.get("minute"), int)
    ]
    if len(rows) < 2:
        return True
    stride = engine.state.clock.stride_minutes
    for left, right in zip(rows, rows[1:]):
        left_day = _checkpoint_day(left)
        right_day = _checkpoint_day(right)
        if left_day != right_day:
            continue
        if int(right["minute"]) - int(left["minute"]) != stride:
            return False
    return True


def _checkpoint_day(row: dict[str, object]) -> int | None:
    snapshot = row.get("snapshot")
    if not isinstance(snapshot, dict):
        return None
    day = snapshot.get("day")
    return day if isinstance(day, int) else None


def _has_day_summary_memory(engine: TownWorldEngine) -> bool:
    for npc_id in engine.state.resident_ids():
        if engine.memory_for(npc_id).grep(
            "",
            category="impression",
            metadata_filters={"source": "town_day_summary"},
            k=1,
        ):
            return True
    return False


def _action_lifecycle_warnings(
    engine: TownWorldEngine,
    tick_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    warnings: list[dict[str, object]] = []
    for npc_id, action in sorted(engine.state.current_actions.items()):
        if action.end_minute <= engine.state.clock.minute:
            warnings.append(
                {
                    "kind": "due_current_action_not_finalized",
                    "npc_id": npc_id,
                    "action_type": action.action_type,
                    "end_minute": action.end_minute,
                    "clock_minute": engine.state.clock.minute,
                }
            )
    for action in engine.action_log:
        if action.get("occupancy_model") == "duration_occupied" and not action.get(
            "lifecycle_state"
        ):
            warnings.append(
                {
                    "kind": "missing_lifecycle_state",
                    "npc_id": action.get("npc_id"),
                    "action_type": action.get("action_type"),
                }
            )
    for row in tick_rows:
        for skipped in row.get("skipped", []):
            if (
                isinstance(skipped, dict)
                and skipped.get("reason") == "action_in_progress"
                and not skipped.get("lifecycle")
            ):
                warnings.append(
                    {
                        "kind": "missing_in_progress_skip_lifecycle",
                        "npc_id": skipped.get("npc_id"),
                        "tick": row.get("tick"),
                    }
                )
    return warnings


def _schedule_evidence_summary(engine: TownWorldEngine) -> dict[str, object]:
    by_stage = Counter(str(item.get("stage", "unknown")) for item in engine.planning_log)
    day_evidence: dict[str, list[dict[str, object]]] = {}
    for npc_id, resident in sorted(engine.state.residents.items()):
        for day, plan in sorted(resident.day_plans.items()):
            if plan.schedule_evidence:
                day_evidence[f"{npc_id}:day-{day}"] = list(plan.schedule_evidence)
    return {
        "overdue_count": by_stage.get("schedule_overdue", 0),
        "explicit_completion_count": _completion_count(engine, "explicit_request"),
        "inferred_completion_count": _completion_count(engine, "inferred_action_match"),
        "automatic_completion_count": _completion_count(engine, "automatic_action_match"),
        "unfinished_count": sum(
            1
            for resident in engine.state.residents.values()
            for plan in resident.day_plans.values()
            for item in plan.schedule_evidence
            if item.get("status") not in {"completed", "satisfied_in_progress", "future_not_run"}
        ),
        "satisfied_in_progress_count": sum(
            1
            for resident in engine.state.residents.values()
            for plan in resident.day_plans.values()
            for item in plan.schedule_evidence
            if item.get("status") == "satisfied_in_progress"
        ),
        "future_not_run_count": sum(
            1
            for resident in engine.state.residents.values()
            for plan in resident.day_plans.values()
            for item in plan.schedule_evidence
            if item.get("status") == "future_not_run"
        ),
        "lifecycle_anomaly_count": sum(
            len(plan.lifecycle_anomalies)
            for resident in engine.state.residents.values()
            for plan in resident.day_plans.values()
        ),
        "by_planning_stage": dict(sorted(by_stage.items())),
        "day_evidence": day_evidence,
    }


def _scale_diagnostics(
    engine: TownWorldEngine,
    tick_rows: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "action_quality": _scaled_action_quality(engine, tick_rows),
        "social_behavior": _scaled_social_behavior(engine),
        "resident_inspection": _scaled_resident_inspection(engine),
        "replay_checkpoints": {
            "count": len(engine.replay_log),
            "resident_ids": sorted(engine.state.resident_ids()),
            "checkpoint_resident_counts": [
                len(_safe_mapping(_safe_mapping(row.get("snapshot")).get("residents")))
                for row in engine.replay_log
            ],
            "has_current_action_lifecycle": all(
                isinstance(row.get("current_action_lifecycle"), dict)
                for row in engine.replay_log
            ),
            "has_next_available_minutes": all(
                isinstance(row.get("next_available_minutes"), dict)
                for row in engine.replay_log
            ),
        },
    }


def _scaled_action_quality(
    engine: TownWorldEngine,
    tick_rows: list[dict[str, object]],
) -> dict[str, object]:
    action_counts_by_resident: dict[str, Counter[str]] = defaultdict(Counter)
    failure_reasons_by_resident: dict[str, Counter[str]] = defaultdict(Counter)
    lifecycle_states: Counter[str] = Counter()
    failed_targets: Counter[str] = Counter()
    failed_intents: Counter[str] = Counter()
    suggested_affordance_misses = 0
    rest_lifecycle_failures: list[dict[str, object]] = []
    for action in engine.action_log:
        npc_id = str(action.get("npc_id", "unknown"))
        action_type = str(action.get("action_type", "unknown"))
        status = str(action.get("status", "unknown"))
        facts = _facts(action)
        action_counts_by_resident[npc_id][action_type] += 1
        lifecycle_states[str(action.get("lifecycle_state", "unknown"))] += 1
        if status.lower() not in _SUCCESS_STATUSES:
            reason = str(facts.get("reason", action.get("failure_reason") or status))
            failure_reasons_by_resident[npc_id][reason] += 1
            target = facts.get("target_id") or facts.get("object_id")
            if target:
                failed_targets[str(target)] += 1
            intent = facts.get("intent") or facts.get("affordance_id")
            if intent:
                failed_intents[str(intent)] += 1
            suggestions = facts.get("suggested_affordances", [])
            if isinstance(suggestions, list) and suggestions:
                suggested_affordance_misses += 1
            if _is_rest_lifecycle_action(action):
                rest_lifecycle_failures.append(
                    {
                        "npc_id": npc_id,
                        "action_type": action_type,
                        "reason": reason,
                        "location_id": action.get("location_id"),
                        "facts": facts,
                    }
                )
        elif _is_rest_lifecycle_action(action) and str(action.get("lifecycle_state")) == "failed":
            rest_lifecycle_failures.append(
                {
                    "npc_id": npc_id,
                    "action_type": action_type,
                    "reason": str(action.get("failure_reason", "lifecycle_failed")),
                    "location_id": action.get("location_id"),
                    "facts": facts,
                }
            )

    active_lifecycle_counts = Counter(
        action.lifecycle_state
        for action in engine.state.current_actions.values()
    )
    loop_guard_counts: Counter[str] = Counter(
        str(item.get("npc_id", "unknown")) for item in engine.loop_guard_events
    )
    schedule_by_resident: dict[str, dict[str, int]] = {}
    for npc_id in sorted(engine.state.resident_ids()):
        completed = engine.state.completed_schedule_segments.get(npc_id, [])
        schedule = engine.state.schedule_for(npc_id)
        schedule_by_resident[npc_id] = {
            "total": len(schedule),
            "completed": len(completed),
            "explicit_completed": sum(
                1 for item in completed if getattr(item, "completion_type", "explicit_request") == "explicit_request"
            ),
            "inferred_completed": sum(
                1 for item in completed if getattr(item, "completion_type", "explicit_request") == "inferred_action_match"
            ),
            "unfinished": max(0, len(schedule) - len(completed)),
        }

    skipped_by_reason: Counter[str] = Counter(
        str(skipped.get("reason", "unknown"))
        for row in tick_rows
        for skipped in row.get("skipped", [])
        if isinstance(skipped, dict)
    )
    return {
        "action_counts_by_resident": {
            npc_id: dict(sorted(counter.items()))
            for npc_id, counter in sorted(action_counts_by_resident.items())
        },
        "failure_reasons_by_resident": {
            npc_id: dict(sorted(counter.items()))
            for npc_id, counter in sorted(failure_reasons_by_resident.items())
        },
        "action_lifecycle_state_counts": dict(sorted(lifecycle_states.items())),
        "current_action_lifecycle_state_counts": dict(sorted(active_lifecycle_counts.items())),
        "schedule_by_resident": schedule_by_resident,
        "loop_guard_count_by_resident": dict(sorted(loop_guard_counts.items())),
        "skipped_by_reason": dict(sorted(skipped_by_reason.items())),
        "affordance_alignment": {
            "top_failed_targets": dict(failed_targets.most_common(10)),
            "top_failed_intents": dict(failed_intents.most_common(10)),
            "suggested_affordance_miss_count": suggested_affordance_misses,
            "unsupported_affordance_count": sum(
                counter.get("unsupported_affordance", 0)
                for counter in failure_reasons_by_resident.values()
            ),
        },
        "rest_lifecycle_failures": {
            "count": len(rest_lifecycle_failures),
            "items": rest_lifecycle_failures[:20],
            "lifecycle_anomaly_count": sum(
                len(plan.lifecycle_anomalies)
                for resident in engine.state.residents.values()
                for plan in resident.day_plans.values()
            ),
        },
    }


def _is_rest_lifecycle_action(action: dict[str, object]) -> bool:
    facts = _facts(action)
    haystack = " ".join(
        str(value)
        for value in [
            action.get("action_type", ""),
            action.get("summary", ""),
            facts.get("intent", ""),
            facts.get("affordance_id", ""),
            facts.get("requested_affordance_id", ""),
            facts.get("note", ""),
            facts.get("reason", ""),
        ]
    ).lower()
    return any(token in haystack for token in ("rest", "sleep", "home", "lifecycle", "休息", "睡"))


def _scaled_social_behavior(engine: TownWorldEngine) -> dict[str, object]:
    sessions_by_resident: Counter[str] = Counter()
    for session in engine.state.conversation_sessions.values():
        for npc_id in session.participants:
            sessions_by_resident[npc_id] += 1
    relationship_cues = {
        npc_id: {
            "relationship_count": len(resident.persona.relationships),
            "known_targets": sorted(
                target
                for target in resident.persona.relationships
                if target in engine.state.residents
            ),
        }
        for npc_id, resident in sorted(engine.state.residents.items())
    }
    conversation_memory_by_resident = {
        npc_id: len(
            engine.memory_for(npc_id).grep(
                "",
                category="impression",
                metadata_filters={"source": "town_conversation"},
                k=20,
            )
        )
        for npc_id in engine.state.resident_ids()
    }
    return {
        "conversation_session_count": len(engine.state.conversation_sessions),
        "conversation_sessions_by_resident": dict(sorted(sessions_by_resident.items())),
        "cooldowns": {
            key: value
            for key, value in sorted(engine.state.conversation_cooldowns.items())
        },
        "blocked_or_cooldown_evidence_count": len(engine.state.conversation_cooldowns)
        + sum(
            1
            for action in engine.action_log
            if str(_facts(action).get("reason", "")).find("cooldown") >= 0
        ),
        "relationship_cue_availability": relationship_cues,
        "conversation_derived_memory_by_resident": conversation_memory_by_resident,
        "conversation_planning_evidence": [
            item
            for item in engine.planning_log
            if "conversation" in json.dumps(item, ensure_ascii=False).lower()
        ],
    }


def _scaled_resident_inspection(engine: TownWorldEngine) -> dict[str, object]:
    residents: dict[str, object] = {}
    for npc_id, resident in sorted(engine.state.residents.items()):
        current_action = engine.state.current_action_for(npc_id)
        residents[npc_id] = {
            "location_id": resident.location_id,
            "home_location_id": resident.home_location_id,
            "sleep_location_id": resident.sleep_location_id,
            "lifecycle_status": resident.lifecycle_status,
            "current_action": {
                "action_type": current_action.action_type,
                "status": current_action.status,
                "lifecycle_state": current_action.lifecycle_state,
                "end_minute": current_action.end_minute,
            }
            if current_action is not None
            else None,
            "schedule": [
                {
                    "day": segment.day,
                    "start_minute": segment.start_minute,
                    "duration_minutes": segment.duration_minutes,
                    "location_id": segment.location_id,
                    "intent": segment.intent,
                    "completed": engine.state.is_schedule_segment_complete(npc_id, segment),
                }
                for segment in engine.state.schedule_for(npc_id)
            ],
            "completed_schedule_count": len(engine.state.completed_schedule_segments.get(npc_id, [])),
            "reflection_evidence_count": len(resident.reflection_evidence),
            "day_plan_count": len(resident.day_plans),
        }
    return residents


def _completion_count(engine: TownWorldEngine, completion_type: str) -> int:
    return sum(
        1
        for completions in engine.state.completed_schedule_segments.values()
        for item in completions
        if getattr(item, "completion_type", "explicit_request") == completion_type
    )


def _lifecycle_for(
    row: dict[str, object],
    npc_id: str,
) -> dict[str, object]:
    lifecycle = row.get("current_action_lifecycle", {})
    if not isinstance(lifecycle, dict):
        return {}
    value = lifecycle.get(npc_id, {})
    return value if isinstance(value, dict) else {}


def _facts(action: dict[str, object]) -> dict[str, object]:
    facts = action.get("facts", {})
    return facts if isinstance(facts, dict) else {}


def _tool(context: AgentContext, name: str):
    return next(tool for tool in context.tools if tool.name == name)


def _path_or_none(run_dir: Path, path: Path | None) -> object:
    return _relative_or_external(run_dir, path) if path is not None else None


def _relative_or_external(run_dir: Path, path: Path) -> object:
    try:
        return str(path.resolve().relative_to(run_dir.resolve()))
    except ValueError:
        return {"external": True, "path": str(path)}


def _add_presentation_validation(
    diagnostics: dict[str, object],
    read_model_path: Path,
    presentation_paths: dict[str, Path],
) -> None:
    validation = diagnostics.get("validation")
    if not isinstance(validation, dict):
        return
    try:
        model = json.loads(read_model_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        validation["presentation_artifacts"] = {
            "status": "artifact_generation_failed",
            "error": str(exc),
        }
        validation["status"] = "fail"
        return
    events = model.get("timeline_events", []) if isinstance(model, dict) else []
    frames = model.get("world_frames", []) if isinstance(model, dict) else []
    final_states = model.get("final_resident_states", {}) if isinstance(model, dict) else {}
    event_types = {
        str(event.get("type"))
        for event in events
        if isinstance(event, dict)
    }
    checks = validation.get("checks")
    if not isinstance(checks, dict):
        checks = {}
        validation["checks"] = checks
    viewer_checks = {
        "read_model_generated": read_model_path.exists(),
        "viewer_generated": bool(presentation_paths.get("viewer") and presentation_paths["viewer"].exists()),
        "day_start_visible": "day_started" in event_types or any(isinstance(frame, dict) and frame.get("day") for frame in frames),
        "wake_or_sleep_state_visible": any(
            isinstance(frame, dict)
            and any(
                isinstance(resident, dict) and resident.get("lifecycle_status")
                for resident in _safe_mapping(frame.get("residents")).values()
            )
            for frame in frames
        ),
        "planning_visible": "resident_planned_day" in event_types,
        "schedule_execution_visible": "schedule_segment_changed" in event_types
        or any(
            isinstance(resident, dict) and resident.get("completed_schedule_count", 0)
            for resident in _safe_mapping(final_states).values()
        ),
        "day_summary_visible": "day_summary_created" in event_types
        or bool(model.get("day_summaries") if isinstance(model, dict) else False),
        "final_resident_states_visible": bool(final_states),
        "warnings_visible": "warning_recorded" in event_types or bool(model.get("warnings") if isinstance(model, dict) else False),
    }
    checks.update(viewer_checks)
    validation["presentation_artifacts"] = {
        "status": "generated",
        "read_model": str(read_model_path),
        "viewer": str(presentation_paths.get("viewer")),
        "checks": viewer_checks,
        "behavior_quality": (
            "inspectable_anomalies"
            if model.get("warnings") or model.get("lifecycle_anomalies")
            else "no_viewer_warnings"
        )
        if isinstance(model, dict)
        else "unknown",
    }


def _safe_mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def read_runtime_diagnostics(path: str | Path) -> dict[str, object]:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("town runtime diagnostics must be a JSON object")
    return payload

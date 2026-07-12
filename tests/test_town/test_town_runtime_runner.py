from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from annie.npc.core.context import AgentContext
from annie.npc.core.response import AgentResponse
from annie.town import (
    TownRuntimeConfig,
    default_scaled_town_scenario_path,
    default_small_town_scenario_path,
    run_town_runtime,
    validate_deterministic_long_run,
    validate_deterministic_scale_run,
    validate_resume_continuation,
)


def test_town_runtime_new_run_writes_standard_artifacts(tmp_path: Path) -> None:
    result = run_town_runtime(
        TownRuntimeConfig(
            run_id="new-run",
            run_root=tmp_path,
            scenario_path=default_small_town_scenario_path(),
            end_minute=9 * 60,
            max_ticks_per_day=8,
        )
    )

    assert result.run_dir == tmp_path / "new-run"
    assert result.persistence_paths["manifest"].exists()
    assert result.persistence_paths["latest_snapshot"].exists()
    assert result.replay_paths["checkpoints"].exists()
    assert result.diagnostics_path.exists()
    assert result.validation_path is not None and result.validation_path.exists()

    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["latest_snapshot_path"] == "state/latest.json"
    assert manifest["replay_paths"]["checkpoints"] == "replay/town_checkpoints.jsonl"
    assert manifest["history_path"] == "history"
    assert manifest["vector_store_path"] == "vector_store"

    diagnostics = result.diagnostics
    assert diagnostics["run"]["run_id"] == "new-run"
    assert diagnostics["scenario"]["id"] == "small_town"
    assert diagnostics["ticks"]["count"] >= 1
    skipped = [
        item
        for row in diagnostics["ticks"]["rows"]
        for item in row["skipped"]
    ]
    assert all(item["reason"] for item in skipped)
    assert diagnostics["actions"]["by_type"]
    assert "due_finalizations" in diagnostics["action_lifecycle"]
    assert "overdue_count" in diagnostics["schedule_evidence"]
    assert "succeeded" not in json.dumps(
        diagnostics["actions"]["failures"],
        ensure_ascii=False,
    )
    assert diagnostics["artifacts"]["manifest"] == "manifest.json"
    assert diagnostics["validation"]["status"] == "pass"
    assert "checks" in diagnostics["validation"]
    assert "lifecycle_warnings" in diagnostics["validation"]
    assert "warnings" in diagnostics["action_lifecycle"]


def test_deterministic_long_run_validation_covers_multiday_multi_resident_runtime(
    tmp_path: Path,
) -> None:
    validation = validate_deterministic_long_run(
        run_root=tmp_path,
        scenario_path=default_small_town_scenario_path(),
        npc_ids=["alice", "bob", "clara"],
        days=2,
        end_minute=10 * 60,
        max_ticks_per_day=16,
    )
    checks = validation.diagnostics["validation"]["checks"]

    assert validation.ok is True
    assert validation.failed_checks == []
    assert validation.lifecycle_warnings == []
    assert checks["multiple_residents"] is True
    assert checks["multiple_days"] is True
    assert checks["fixed_tick_advancement"] is True
    assert checks["schedule_execution_observed"] is True
    assert checks["reflection_or_day_summary_observed"] is True


def test_town_runtime_uses_injected_agent_factory(tmp_path: Path) -> None:
    calls: list[str] = []

    def factory(config: TownRuntimeConfig) -> RecordingAgent:
        calls.append(config.run_id)
        return RecordingAgent()

    result = run_town_runtime(
        TownRuntimeConfig(
            run_id="factory-run",
            run_root=tmp_path,
            end_minute=8 * 60 + 10,
            max_ticks_per_day=1,
        ),
        agent_factory=factory,
    )

    assert calls == ["factory-run"]
    assert result.diagnostics["ticks"]["count"] == 1
    assert result.diagnostics["actions"]["count"] == 0


def test_town_runtime_resume_continues_with_fresh_stateless_agent(tmp_path: Path) -> None:
    first = run_town_runtime(
        TownRuntimeConfig(
            run_id="resume-run",
            run_root=tmp_path,
            end_minute=8 * 60 + 20,
            max_ticks_per_day=2,
        )
    )
    restored_minute = first.engine.state.clock.minute

    second = run_town_runtime(
        TownRuntimeConfig(
            run_id="resume-run",
            run_root=tmp_path,
            resume=True,
            end_minute=8 * 60 + 40,
            max_ticks_per_day=2,
        ),
        agent_factory=lambda _config: RecordingAgent(),
    )

    assert second.resumed is True
    assert second.engine.state.clock.minute > restored_minute
    resume = second.diagnostics["resume"]
    assert resume["source_manifest"] == "manifest.json"
    assert resume["source_snapshot"] == "state/latest.json"
    assert resume["restored_time"]["minute"] == restored_minute
    assert "restored_current_actions" in resume
    assert resume["first_continued_tick"] is not None


def test_scaled_town_runtime_writes_inspectable_scale_diagnostics(tmp_path: Path) -> None:
    validation = validate_deterministic_scale_run(
        run_root=tmp_path,
        scenario_path=default_scaled_town_scenario_path(),
        npc_ids=["ada", "ben", "cara", "dan", "elena", "finn", "grace", "hugo"],
        end_minute=9 * 60 + 40,
        max_ticks_per_day=10,
    )

    diagnostics = validation.diagnostics
    scale = diagnostics["scale"]

    assert validation.ok is True
    assert validation.failed_checks == []
    assert validation.result.persistence_paths["manifest"].exists()
    assert validation.result.persistence_paths["latest_snapshot"].exists()
    assert validation.result.replay_paths["checkpoints"].exists()
    assert scale["action_quality"]["schedule_by_resident"]["ada"]["total"] >= 3
    assert "failure_reasons_by_resident" in scale["action_quality"]
    assert scale["replay_checkpoints"]["has_current_action_lifecycle"] is True
    assert scale["replay_checkpoints"]["has_next_available_minutes"] is True
    assert "relationship_cue_availability" in scale["social_behavior"]
    assert "ada" in scale["resident_inspection"]


def test_scaled_town_runtime_resume_continues_from_manifest(tmp_path: Path) -> None:
    validation = validate_resume_continuation(
        run_root=tmp_path,
        scenario_path=default_scaled_town_scenario_path(),
        split_minute=8 * 60 + 20,
        end_minute=8 * 60 + 40,
        max_ticks_per_day=4,
    )

    assert validation.ok is True
    assert validation.resumed.diagnostics["resume"]["source_manifest"] == "manifest.json"
    assert validation.resumed.diagnostics["scale"]["resident_inspection"]["ada"]["schedule"]


@dataclass
class RecordingAgent:
    def run(self, context: AgentContext) -> AgentResponse:
        return AgentResponse()

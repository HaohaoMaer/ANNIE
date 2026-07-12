from __future__ import annotations

import json
from pathlib import Path

from annie.town import (
    TownRuntimeConfig,
    build_town_replay_read_model,
    default_replay_demo_scenario_path,
    load_town_scenario,
    run_town_runtime,
    write_town_replay_read_model,
    write_town_replay_viewer,
)


def test_read_model_generated_from_manifest_without_live_engine(tmp_path: Path) -> None:
    result = run_town_runtime(
        TownRuntimeConfig(
            run_id="watchable",
            run_root=tmp_path,
            end_minute=9 * 60,
            max_ticks_per_day=8,
        )
    )

    model = build_town_replay_read_model(result.persistence_paths["manifest"])

    assert model["schema"]["version"] == 1
    assert model["run"]["run_id"] == "watchable"
    assert model["locations"]
    assert model["residents"]
    assert model["world_frames"]
    assert model["timeline_events"]
    assert model["schedules"]
    assert "final_resident_states" in model
    event_types = {event["type"] for event in model["timeline_events"]}
    assert "run_started" in event_types
    assert "day_started" in event_types
    assert "resident_planned_day" in event_types
    assert any("source" in event for event in model["timeline_events"])


def test_runtime_links_presentation_artifacts_and_preserves_existing_manifest_paths(
    tmp_path: Path,
) -> None:
    result = run_town_runtime(
        TownRuntimeConfig(
            run_id="linked",
            run_root=tmp_path,
            end_minute=9 * 60,
            max_ticks_per_day=8,
        )
    )

    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["latest_snapshot_path"] == "state/latest.json"
    assert manifest["replay_paths"]["checkpoints"] == "replay/town_checkpoints.jsonl"
    assert manifest["diagnostics_path"] == "diagnostics.json"
    assert manifest["validation_path"] == "validation.json"
    assert manifest["presentation_paths"]["read_model"] == "presentation/replay_read_model.json"
    assert manifest["presentation_paths"]["viewer"] == "viewer/index.html"
    assert result.presentation_paths["read_model"].exists()
    assert result.presentation_paths["viewer"].exists()
    assert result.diagnostics["artifacts"]["presentation_paths"]["viewer"] == "viewer/index.html"
    assert result.diagnostics["validation"]["checks"]["read_model_generated"] is True
    assert result.diagnostics["validation"]["checks"]["final_resident_states_visible"] is True


def test_resume_boundary_is_visible_in_read_model(tmp_path: Path) -> None:
    run_town_runtime(
        TownRuntimeConfig(
            run_id="resume-visible",
            run_root=tmp_path,
            end_minute=8 * 60 + 20,
            max_ticks_per_day=2,
        )
    )
    result = run_town_runtime(
        TownRuntimeConfig(
            run_id="resume-visible",
            run_root=tmp_path,
            resume=True,
            end_minute=8 * 60 + 40,
            max_ticks_per_day=2,
        )
    )

    model = build_town_replay_read_model(result.persistence_paths["manifest"])

    assert model["resume_markers"]
    marker = model["resume_markers"][0]
    assert marker["source_manifest"] == "manifest.json"
    assert marker["source_snapshot"] == "state/latest.json"
    assert marker["restored_time"]["minute"] == result.diagnostics["resume"]["restored_time"]["minute"]
    assert any(event["type"] == "run_resumed" for event in model["timeline_events"])


def test_viewer_generation_for_existing_manifest_uses_resolvable_paths(tmp_path: Path) -> None:
    result = run_town_runtime(
        TownRuntimeConfig(
            run_id="existing",
            run_root=tmp_path,
            end_minute=8 * 60 + 20,
            max_ticks_per_day=2,
            write_presentation_artifacts=False,
        )
    )

    read_model = write_town_replay_read_model(result.persistence_paths["manifest"])
    viewer_paths = write_town_replay_viewer(result.persistence_paths["manifest"], read_model_path=read_model)

    assert read_model == result.run_dir / "presentation" / "replay_read_model.json"
    assert viewer_paths["viewer_index"] == result.run_dir / "viewer" / "index.html"
    assert viewer_paths["viewer_read_model"].exists()
    model = json.loads(viewer_paths["viewer_read_model"].read_text(encoding="utf-8"))
    assert model["artifacts"]["manifest"]["path"] == "manifest.json"


def test_replay_demo_scenario_uses_semantic_schema_without_legacy_visual_fields() -> None:
    path = default_replay_demo_scenario_path()
    scenario = load_town_scenario(path)
    raw = path.read_text(encoding="utf-8")

    assert scenario.id == "replay_demo_town"
    assert 5 <= len(scenario.state.residents) <= 8
    assert 8 <= len(scenario.state.locations) <= 12
    assert scenario.memory_seeds
    assert all(resident.home_location_id for resident in scenario.state.residents.values())
    assert all(resident.sleep_location_id for resident in scenario.state.residents.values())
    assert "tile" not in raw
    assert "sprite" not in raw
    assert "portrait" not in raw
    assert "llm" not in raw.lower()


def test_replay_demo_scenario_generates_viewer_without_live_llm(tmp_path: Path) -> None:
    result = run_town_runtime(
        TownRuntimeConfig(
            run_id="demo",
            run_root=tmp_path,
            scenario_path=default_replay_demo_scenario_path(),
            npc_ids=["mira", "ren", "sora", "theo", "lio"],
            end_minute=9 * 60,
            max_ticks_per_day=8,
        )
    )

    model = json.loads(result.presentation_paths["read_model"].read_text(encoding="utf-8"))

    assert result.presentation_paths["viewer"].exists()
    assert model["run"]["scenario"]["id"] == "replay_demo_town"
    assert len(model["residents"]) == 5
    assert model["timeline_events"]

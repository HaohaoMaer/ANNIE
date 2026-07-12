from __future__ import annotations

from pathlib import Path

from annie.town import (
    default_small_town_scenario_path,
    extract_behavior_signature,
    validate_resume_continuation,
)


def test_resume_continuation_matches_stable_behavior_signature(tmp_path: Path) -> None:
    validation = validate_resume_continuation(
        run_root=tmp_path,
        scenario_path=default_small_town_scenario_path(),
        split_minute=8 * 60 + 20,
        end_minute=8 * 60 + 40,
        max_ticks_per_day=4,
    )

    assert validation.ok is True
    assert validation.differences == []
    assert validation.resumed.diagnostics["resume"]["restored_time"]["minute"] == 8 * 60 + 20
    assert validation.resumed.diagnostics["resume"]["first_continued_tick"] == 3
    assert "action_lifecycle" in validation.continuous_signature
    assert (
        validation.continuous_signature["action_lifecycle"]
        == validation.resumed_signature["action_lifecycle"]
    )


def test_behavior_signature_excludes_byte_for_byte_replay_payload(tmp_path: Path) -> None:
    validation = validate_resume_continuation(
        run_root=tmp_path,
        scenario_path=default_small_town_scenario_path(),
        split_minute=8 * 60 + 10,
        end_minute=8 * 60 + 20,
        max_ticks_per_day=2,
    )
    signature = extract_behavior_signature(validation.resumed.engine)

    assert "replay_log" not in signature
    assert "action_log" not in signature
    assert "replay_checkpoint_shape" in signature
    assert "action_lifecycle" in signature

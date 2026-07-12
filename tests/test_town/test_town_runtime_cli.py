from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path


def test_run_town_runtime_cli_parses_core_options() -> None:
    module_path = Path("scripts/run_town_runtime.py")
    spec = importlib.util.spec_from_file_location("run_town_runtime", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    run_root = Path(tempfile.gettempdir()) / "town-runs"

    args = module.build_parser().parse_args(
        [
            "--run-id",
            "cli-smoke",
            "--run-root",
            str(run_root),
            "--resume",
            "--npc-id",
            "alice",
            "--npc-id",
            "bob",
            "--end-minute",
            "600",
            "--max-ticks-per-day",
            "3",
            "--agent-mode",
            "deterministic",
        ]
    )

    assert args.run_id == "cli-smoke"
    assert args.run_root == run_root
    assert args.resume is True
    assert args.npc_ids == ["alice", "bob"]
    assert args.end_minute == 600
    assert args.max_ticks_per_day == 3


def test_real_llm_validation_cli_accepts_multiple_npc_ids() -> None:
    module_path = Path("scripts/validate_townworld_phase1_multiday_real_llm.py")
    spec = importlib.util.spec_from_file_location("validate_real_llm", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["validate_real_llm"] = module
    spec.loader.exec_module(module)

    output_dir = Path(tempfile.gettempdir()) / "town-real-llm"

    args = module.build_parser().parse_args(
        [
            "--output-dir",
            str(output_dir),
            "--npc-id",
            "alice",
            "--npc-id",
            "bob",
            "--days",
            "2",
            "--end-minute",
            "600",
            "--max-ticks-per-day",
            "4",
            "--resume-smoke",
        ]
    )

    assert args.output_dir == output_dir
    assert args.npc_ids == ["alice", "bob"]
    assert args.days == 2
    assert args.end_minute == 600
    assert args.max_ticks_per_day == 4
    assert args.resume_smoke is True

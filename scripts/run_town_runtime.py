#!/usr/bin/env python
"""Run or resume a consolidated TownWorld runtime."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from annie.npc.model.config import load_model_config
from annie.town import (
    TownRuntimeConfig,
    default_small_town_scenario_path,
    run_town_runtime,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a named TownWorld runtime.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-root", type=Path, default=Path("runs/town"))
    parser.add_argument("--scenario", type=Path, default=default_small_town_scenario_path())
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--npc-id", action="append", dest="npc_ids", default=None)
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--start-minute", type=int, default=8 * 60)
    parser.add_argument("--end-minute", type=int, default=22 * 60)
    parser.add_argument("--max-ticks-per-day", type=int, default=120)
    parser.add_argument("--agent-mode", choices=["deterministic", "real_llm"], default="deterministic")
    parser.add_argument("--model-config", type=Path, default=Path("config/model_config.yaml"))
    parser.add_argument("--write-step-snapshots", action="store_true")
    parser.add_argument("--no-replay", action="store_true")
    parser.add_argument("--no-viewer", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    load_dotenv()
    if args.agent_mode == "real_llm":
        model_config = load_model_config(args.model_config)
        if not model_config.api_key:
            raise SystemExit(f"Missing API key environment variable: {model_config.model.api_key_env}")
    result = run_town_runtime(
        TownRuntimeConfig(
            run_id=args.run_id,
            scenario_path=args.scenario,
            run_root=args.run_root,
            resume=args.resume,
            npc_ids=args.npc_ids,
            days=args.days,
            start_minute=args.start_minute,
            end_minute=args.end_minute,
            max_ticks_per_day=args.max_ticks_per_day,
            agent_mode=args.agent_mode,
            model_config_path=args.model_config,
            write_replay_artifacts=not args.no_replay,
            write_presentation_artifacts=not args.no_viewer,
            write_step_snapshots=args.write_step_snapshots,
        )
    )
    print(f"Run dir: {result.run_dir}")
    print(f"Manifest: {result.persistence_paths['manifest']}")
    print(f"Latest snapshot: {result.persistence_paths['latest_snapshot']}")
    print(f"Diagnostics: {result.diagnostics_path}")
    for name, path in result.replay_paths.items():
        print(f"Replay {name}: {path}")
    for name, path in result.presentation_paths.items():
        print(f"Presentation {name}: {path}")
    print(json.dumps(result.diagnostics["validation"], ensure_ascii=False))
    return 0 if result.diagnostics["validation"]["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

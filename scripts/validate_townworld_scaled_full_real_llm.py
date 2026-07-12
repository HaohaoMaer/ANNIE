#!/usr/bin/env python
"""Full-population, two-day real-LLM validation preset for scaled TownWorld.

This script is intentionally a thin preset over
`validate_townworld_scaled_real_llm.py`: it keeps one implementation of the
real-LLM runner and only changes defaults to the expensive full-scale run.
"""

from __future__ import annotations

import argparse
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path

import validate_townworld_scaled_real_llm as scaled
from annie.town import default_scaled_town_scenario_path, load_town_scenario

DEFAULT_STRIDE_MINUTES = 10


def main() -> int:
    args = parse_args()
    scenario = load_town_scenario(args.scenario)
    output_dir = args.output_dir or default_run_dir()
    max_ticks = args.max_ticks_per_day or resolved_max_ticks_per_day(args)
    resident_ids = args.resident_ids or ",".join(sorted(scenario.state.residents))
    scaled_args = argparse.Namespace(
        scenario=args.scenario,
        resident_ids=resident_ids,
        resident_count=len(scenario.state.residents),
        days=args.days,
        start_minute=args.start_minute,
        end_minute=args.end_minute,
        max_ticks=max_ticks,
        model_config=args.model_config,
        temperature=args.temperature,
        retries=args.retries,
        output_dir=output_dir,
        prompt_preview_length=args.prompt_preview_length,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    terminal_output = output_dir / "terminal_output.txt"
    with terminal_output.open("w", encoding="utf-8") as log_file:
        tee = scaled.Tee(sys.stdout, log_file)
        with redirect_stdout(tee), redirect_stderr(tee):
            print_full_run_plan(
                scenario_id=scenario.id,
                resident_count=len([item for item in resident_ids.split(",") if item.strip()]),
                days=args.days,
                start_minute=args.start_minute,
                end_minute=args.end_minute,
                max_ticks=max_ticks,
                output_dir=output_dir,
            )
            return scaled.run_validation(scaled_args, output_dir, terminal_output)


def resolved_max_ticks_per_day(args: argparse.Namespace) -> int:
    window = max(0, args.end_minute - args.start_minute)
    return max(1, (window + DEFAULT_STRIDE_MINUTES - 1) // DEFAULT_STRIDE_MINUTES)


def print_full_run_plan(
    *,
    scenario_id: str,
    resident_count: int,
    days: int,
    start_minute: int,
    end_minute: int,
    max_ticks: int,
    output_dir: Path,
) -> None:
    print("TownWorld scaled full real-LLM validation preset")
    print(f"scenario={scenario_id}")
    print(f"resident_count={resident_count}")
    print(f"days={days}")
    print(f"window={start_minute}-{end_minute}")
    print(f"max_ticks_per_day={max_ticks}")
    print(f"output_dir={output_dir}")


def default_run_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("runs/town_scaled_full_real_llm") / stamp


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the full scaled TownWorld population for two days with a real LLM."
    )
    parser.add_argument("--scenario", type=Path, default=default_scaled_town_scenario_path())
    parser.add_argument(
        "--resident-ids",
        default="",
        help="Optional comma-separated resident ids. Defaults to all residents in the scenario.",
    )
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--start-minute", type=int, default=0)
    parser.add_argument("--end-minute", type=int, default=24 * 60)
    parser.add_argument(
        "--max-ticks-per-day",
        type=int,
        default=None,
        help="Default derives from the configured time window and 10-minute stride.",
    )
    parser.add_argument("--model-config", type=Path, default=Path("config/model_config.yaml"))
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--prompt-preview-length", type=int, default=1200)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())

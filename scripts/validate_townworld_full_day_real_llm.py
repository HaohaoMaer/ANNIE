"""Opt-in real-LLM full-day TownWorld lifecycle validation.

Run:
    conda run -n annie python scripts/validate_townworld_full_day_real_llm.py

The script writes terminal output, replay artifacts, manifest/latest state,
diagnostics, and summary.json under runs/town_full_day_real_llm/<timestamp>/.
For cheaper smoke validation, keep using the short-window scripts such as
scripts/validate_townworld_phase1_multiday_real_llm.py and
scripts/validate_townworld_generative_agents_real_llm.py.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from annie.npc import NPCAgent
from annie.npc.model.config import load_model_config
from annie.town.runtime.runner import (
    TownRuntimeConfig,
    run_town_runtime,
)

DEFAULT_STRIDE_MINUTES = 10


class Tee:
    def __init__(self, *streams: TextIO) -> None:
        self._streams = streams

    def write(self, text: str) -> int:
        for stream in self._streams:
            stream.write(text)
            stream.flush()
        return len(text)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()


class TraceChatModel:
    def __init__(
        self,
        model: Any,
        *,
        state: dict[str, object] | None = None,
        bound_tool_names: list[str] | None = None,
        preview_chars: int = 1200,
    ) -> None:
        self._model = model
        self._state = state if state is not None else {"calls": 0}
        self._bound_tool_names = bound_tool_names or []
        self._preview_chars = preview_chars

    @property
    def call_count(self) -> int:
        return int(self._state["calls"])

    def bind_tools(self, tools: list[dict]) -> "TraceChatModel":
        names = [tool.get("function", {}).get("name", "<unknown>") for tool in tools]
        return TraceChatModel(
            self._model.bind_tools(tools),
            state=self._state,
            bound_tool_names=names,
            preview_chars=self._preview_chars,
        )

    def invoke(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        self._state["calls"] = self.call_count + 1
        print(f"\n## LLM call {self.call_count}")
        print(f"bound_tools={', '.join(self._bound_tool_names) or 'none'}")
        if messages:
            print(str(messages[-1].content).replace("\n", " ")[: self._preview_chars])
        response = self._model.invoke(messages, **kwargs)
        if not isinstance(response, AIMessage):
            return AIMessage(content=str(getattr(response, "content", response)))
        if response.tool_calls:
            print(json.dumps(response.tool_calls, ensure_ascii=False)[: self._preview_chars])
        else:
            print(str(response.content)[: self._preview_chars])
        return response


@dataclass
class RuntimeAgentFactory:
    args: argparse.Namespace
    traced_model: TraceChatModel

    def __call__(self, _config: TownRuntimeConfig) -> NPCAgent:
        return NPCAgent(llm=self.traced_model, max_retries=self.args.max_retries)


def main() -> int:
    args = parse_args()
    run_dir = args.output_dir or default_run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)
    terminal_output = run_dir / "terminal_output.txt"
    with terminal_output.open("w", encoding="utf-8") as log_file:
        tee = Tee(sys.stdout, log_file)
        with redirect_stdout(tee), redirect_stderr(tee):
            return run_validation(args, run_dir, terminal_output)


def run_validation(args: argparse.Namespace, run_dir: Path, terminal_output: Path) -> int:
    load_dotenv()
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    model_config = load_model_config(args.model_config)
    if not model_config.api_key:
        raise SystemExit(f"Missing API key environment variable: {model_config.model.api_key_env}")

    print("TownWorld full-day real-LLM validation")
    print(f"run_dir={run_dir}")
    print(f"terminal_output={terminal_output}")
    print(f"days={args.days}")
    print(f"npc_ids={args.npc_ids or 'default'}")
    print(f"window={args.start_minute}-{args.end_minute}")
    print(f"max_ticks_per_day={resolved_max_ticks_per_day(args)}")
    print(f"model={model_config.model.provider}/{model_config.model.model_name}")

    traced_model = TraceChatModel(
        ChatOpenAI(
            model=model_config.model.model_name,
            base_url=model_config.model.base_url,
            api_key=SecretStr(model_config.api_key),
            temperature=args.temperature,
            extra_body={"thinking": {"type": "disabled"}},
        ),
        preview_chars=args.preview_chars,
    )
    result = run_town_runtime(
        TownRuntimeConfig(
            run_id=run_dir.name,
            run_root=run_dir.parent,
            scenario_path=args.scenario,
            npc_ids=args.npc_ids,
            days=args.days,
            start_minute=args.start_minute,
            end_minute=args.end_minute,
            max_ticks_per_day=resolved_max_ticks_per_day(args),
            agent_mode="real_llm",
            model_config_path=args.model_config,
            finalize_day=True,
            validation_options={
                "full_day_validation": True,
                "max_retries": args.max_retries,
            },
        ),
        agent_factory=RuntimeAgentFactory(args, traced_model),
    )
    summary = build_summary(args, result, traced_model.call_count, terminal_output)
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"diagnostics_json={result.diagnostics_path}")
    print(f"summary_json={summary_path}")
    print(f"manifest_json={result.persistence_paths.get('manifest')}")
    for name, path in result.presentation_paths.items():
        print(f"presentation_{name}={path}")
    print("RESULT PASS" if summary["runner"]["status"] == "pass" else "RESULT DIAGNOSTICS_PRESENT")
    return 0


def build_summary(
    args: argparse.Namespace,
    result: Any,
    llm_call_count: int,
    terminal_output: Path,
) -> dict[str, object]:
    diagnostics = result.diagnostics
    schedule = diagnostics.get("schedule_evidence", {})
    actions = diagnostics.get("actions", {})
    validation = diagnostics.get("validation", {})
    return {
        "config": {
            "days": args.days,
            "npc_ids": args.npc_ids,
            "start_minute": args.start_minute,
            "end_minute": args.end_minute,
            "max_ticks_per_day": args.max_ticks_per_day,
            "resolved_max_ticks_per_day": resolved_max_ticks_per_day(args),
            "model_config": str(args.model_config),
            "temperature": args.temperature,
            "max_retries": args.max_retries,
            "preview_chars": args.preview_chars,
        },
        "runner": {
            "status": validation.get("status") if isinstance(validation, dict) else "unknown",
            "note": validation.get("note") if isinstance(validation, dict) else "",
        },
        "llm_call_count": llm_call_count,
        "action_counts": actions,
        "explicit_completion_count": schedule.get("explicit_completion_count") if isinstance(schedule, dict) else None,
        "inferred_completion_count": schedule.get("inferred_completion_count") if isinstance(schedule, dict) else None,
        "unfinished_schedule_count": schedule.get("unfinished_count") if isinstance(schedule, dict) else None,
        "lifecycle_anomaly_count": schedule.get("lifecycle_anomaly_count") if isinstance(schedule, dict) else None,
        "loop_guard_count": diagnostics.get("loop_guards", {}).get("count") if isinstance(diagnostics.get("loop_guards"), dict) else None,
        "repair_count": _repair_count(result.engine),
        "final_resident_states": {
            npc_id: {
                "location_id": resident.location_id,
                "home_location_id": resident.home_location_id,
                "sleep_location_id": resident.sleep_location_id,
                "lifecycle_status": resident.lifecycle_status,
            }
            for npc_id, resident in sorted(result.engine.state.residents.items())
        },
        "artifacts": {
            "terminal_output": str(terminal_output),
            "diagnostics": str(result.diagnostics_path),
            "validation": str(result.validation_path) if result.validation_path else None,
            "manifest": str(result.persistence_paths.get("manifest")),
            "latest_snapshot": str(result.persistence_paths.get("latest_snapshot")),
            "replay_paths": {name: str(path) for name, path in result.replay_paths.items()},
            "presentation_paths": {
                name: str(path) for name, path in result.presentation_paths.items()
            },
        },
    }


def _repair_count(engine: Any) -> int:
    total = 0
    for resident in engine.state.residents.values():
        for plan in resident.day_plans.values():
            warnings = plan.validation.get("warnings", [])
            if isinstance(warnings, list):
                total += sum(1 for item in warnings if "repair" in str(item))
    return total


def resolved_max_ticks_per_day(args: argparse.Namespace) -> int:
    if args.max_ticks_per_day is not None:
        return args.max_ticks_per_day
    window = max(0, args.end_minute - args.start_minute)
    return max(1, (window + DEFAULT_STRIDE_MINUTES - 1) // DEFAULT_STRIDE_MINUTES)


def default_run_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("runs/town_full_day_real_llm") / stamp


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run full-day TownWorld validation with a real LLM.")
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--npc-ids", nargs="+", default=["alice", "bob"])
    parser.add_argument("--start-minute", type=int, default=0)
    parser.add_argument("--end-minute", type=int, default=24 * 60)
    parser.add_argument(
        "--max-ticks-per-day",
        type=int,
        default=None,
        help="Default derives from the window and 10-minute stride; 00:00-24:00 uses 144.",
    )
    parser.add_argument("--model-config", type=Path, default=Path("config/model_config.yaml"))
    parser.add_argument("--scenario", type=Path, default=Path("src/annie/town/content/scenarios/small_town.yaml"))
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--preview-chars", type=int, default=1200)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())

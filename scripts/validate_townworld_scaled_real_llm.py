#!/usr/bin/env python
"""Opt-in real-LLM validation for the scaled TownWorld scenario."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO, cast

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from annie.npc import NPCAgent
from annie.npc.model.config import load_model_config
from annie.town import (
    TownRuntimeConfig,
    default_scaled_town_scenario_path,
    load_town_scenario,
    run_town_runtime,
)


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
        state: dict[str, Any] | None = None,
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
        bound = self._model.bind_tools(tools)
        names = [tool.get("function", {}).get("name", "<unknown>") for tool in tools]
        return TraceChatModel(
            bound,
            state=self._state,
            bound_tool_names=names,
            preview_chars=self._preview_chars,
        )

    def invoke(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        self._state["calls"] += 1
        print(f"LLM call {self.call_count}: tools={','.join(self._bound_tool_names) or 'none'}")
        if messages:
            print(squash(str(messages[-1].content))[: self._preview_chars])
        response = self._model.invoke(messages, **kwargs)
        if not isinstance(response, AIMessage):
            return AIMessage(content=str(getattr(response, "content", response)))
        return response


@dataclass
class RuntimeAgentFactory:
    args: argparse.Namespace
    traced_model: TraceChatModel

    def __call__(self, _config: TownRuntimeConfig) -> NPCAgent:
        return NPCAgent(llm=cast(Any, self.traced_model), max_retries=self.args.retries)


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

    scenario = load_town_scenario(args.scenario)
    npc_ids = resolve_residents(args, sorted(scenario.state.residents))
    print("TownWorld scaled real-LLM validation")
    print(f"scenario={scenario.id} residents={len(scenario.state.residents)} locations={len(scenario.state.locations)}")
    print(f"selected_residents={','.join(npc_ids)}")
    print(f"run_dir={run_dir}")
    print(f"days={args.days} window={args.start_minute}-{args.end_minute} max_ticks={args.max_ticks}")
    print(f"model={model_config.model.provider}/{model_config.model.model_name}")

    traced_model = TraceChatModel(
        ChatOpenAI(
            model=model_config.model.model_name,
            base_url=model_config.model.base_url,
            api_key=SecretStr(model_config.api_key),
            temperature=args.temperature,
            extra_body={"thinking": {"type": "disabled"}},
        ),
        preview_chars=args.prompt_preview_length,
    )
    result = run_town_runtime(
        TownRuntimeConfig(
            run_id=run_dir.name,
            run_root=run_dir.parent,
            scenario_path=args.scenario,
            npc_ids=npc_ids,
            days=args.days,
            start_minute=args.start_minute,
            end_minute=args.end_minute,
            max_ticks_per_day=args.max_ticks,
            agent_mode="real_llm",
            model_config_path=args.model_config,
            finalize_day=True,
            validation_options={"scaled_real_llm": True, "retries": args.retries},
        ),
        agent_factory=RuntimeAgentFactory(args, traced_model),
    )
    summary = build_summary(args, result, traced_model.call_count, terminal_output)
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"diagnostics_json={result.diagnostics_path}")
    print(f"summary_json={summary_path}")
    print(f"manifest_json={result.persistence_paths.get('manifest')}")
    print(f"latest_snapshot={result.persistence_paths.get('latest_snapshot')}")
    print("behavior_warnings:")
    warnings = summary.get("behavior_quality_warnings", [])
    if not isinstance(warnings, list):
        warnings = []
    for warning in warnings:
        print(f"- {warning}")
    return 0 if summary["runner_failure"] is None else 1


def build_summary(
    args: argparse.Namespace,
    result: Any,
    llm_call_count: int,
    terminal_output: Path,
) -> dict[str, object]:
    diagnostics = result.diagnostics
    schedule = diagnostics.get("schedule_evidence", {})
    actions = diagnostics.get("actions", {})
    scale = diagnostics.get("scale", {})
    social = scale.get("social_behavior", {}) if isinstance(scale, dict) else {}
    validation = diagnostics.get("validation", {})
    warnings = behavior_quality_warnings(diagnostics)
    status = validation.get("status") if isinstance(validation, dict) else "unknown"
    note = validation.get("note") if isinstance(validation, dict) else ""
    return {
        "config": {
            "scenario": str(args.scenario),
            "resident_ids": args.resident_ids,
            "resident_count": args.resident_count,
            "days": args.days,
            "start_minute": args.start_minute,
            "end_minute": args.end_minute,
            "max_ticks": args.max_ticks,
            "model_config": str(args.model_config),
            "temperature": args.temperature,
            "retries": args.retries,
            "prompt_preview_length": args.prompt_preview_length,
        },
        "runner": {"status": status, "note": note},
        "runner_failure": note or None,
        "behavior_quality_warnings": warnings,
        "llm_call_count": llm_call_count,
        "action_counts": actions,
        "failed_action_reasons": actions.get("failures") if isinstance(actions, dict) else {},
        "schedule_metrics": {
            "explicit_completion_count": schedule.get("explicit_completion_count") if isinstance(schedule, dict) else None,
            "inferred_completion_count": schedule.get("inferred_completion_count") if isinstance(schedule, dict) else None,
            "unfinished_count": schedule.get("unfinished_count") if isinstance(schedule, dict) else None,
        },
        "loop_guard_metrics": diagnostics.get("loop_guards", {}),
        "conversation_metrics": social,
        "reflection_day_summary_metrics": {
            "reflection_count": diagnostics.get("memory", {}).get("reflection_count")
            if isinstance(diagnostics.get("memory"), dict)
            else None,
            "day_summary_check": validation.get("checks", {}).get("reflection_or_day_summary_observed")
            if isinstance(validation.get("checks"), dict)
            else None,
        },
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
            "presentation_paths": {name: str(path) for name, path in result.presentation_paths.items()},
            "history": str(result.run_dir / "history"),
            "vector_store": str(result.run_dir / "vector_store"),
        },
    }


def behavior_quality_warnings(diagnostics: dict[str, object]) -> list[str]:
    warnings: list[str] = []
    schedule = diagnostics.get("schedule_evidence", {})
    if isinstance(schedule, dict) and int(schedule.get("unfinished_count", 0)) > 0:
        warnings.append(f"unfinished_schedule_count={schedule.get('unfinished_count')}")
    loop_guards = diagnostics.get("loop_guards", {})
    if isinstance(loop_guards, dict) and int(loop_guards.get("count", 0)) > 0:
        warnings.append(f"loop_guard_count={loop_guards.get('count')}")
    actions = diagnostics.get("actions", {})
    if isinstance(actions, dict) and actions.get("failures"):
        warnings.append("failed_actions_present")
    scale = diagnostics.get("scale", {})
    social = scale.get("social_behavior", {}) if isinstance(scale, dict) else {}
    if isinstance(social, dict) and social.get("conversation_session_count") == 0:
        warnings.append("no_conversations_observed")
    return warnings


def resolve_residents(args: argparse.Namespace, resident_ids: list[str]) -> list[str]:
    if args.resident_ids:
        requested = [item.strip() for item in args.resident_ids.split(",") if item.strip()]
    else:
        requested = resident_ids[: args.resident_count]
    unknown = sorted(set(requested) - set(resident_ids))
    if unknown:
        raise SystemExit(f"Unknown resident ids: {', '.join(unknown)}")
    return requested


def squash(text: str) -> str:
    return " ".join(text.split())


def default_run_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("runs/town_scaled_real_llm") / stamp


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run scaled TownWorld validation with a real LLM.")
    parser.add_argument("--scenario", type=Path, default=default_scaled_town_scenario_path())
    parser.add_argument("--resident-ids", default="")
    parser.add_argument("--resident-count", type=int, default=5)
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--start-minute", type=int, default=8 * 60)
    parser.add_argument("--end-minute", type=int, default=10 * 60)
    parser.add_argument("--max-ticks", type=int, default=12)
    parser.add_argument("--model-config", type=Path, default=Path("config/model_config.yaml"))
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--prompt-preview-length", type=int, default=1200)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())

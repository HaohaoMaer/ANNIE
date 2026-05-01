"""Real-LLM validation for Phase 1 TownWorld multi-day behavior.

Run:
    python scripts/validate_townworld_phase1_multiday_real_llm.py

The script reads ``.env`` and ``config/model_config.yaml``. It uses the real
``NPCAgent`` for daily schedule generation and action ticks, then writes the
full terminal trace to:

    runs/town_phase1_real_llm/<timestamp>/terminal_output.txt
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

import chromadb
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from annie.npc import NPCAgent
from annie.npc.config import load_model_config
from annie.town import (
    ScheduleSegment,
    TownWorldEngine,
    create_small_town_state,
    run_multi_npc_day,
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
    """Real model wrapper that prints prompts, tool calls, and responses."""

    def __init__(
        self,
        model: Any,
        *,
        state: dict[str, Any] | None = None,
        bound_tool_names: list[str] | None = None,
        preview_chars: int = 1600,
        verbose_messages: bool = False,
    ) -> None:
        self._model = model
        self._state = state if state is not None else {"calls": 0, "phase": "bootstrap"}
        self._bound_tool_names = bound_tool_names or []
        self._preview_chars = preview_chars
        self._verbose_messages = verbose_messages

    @property
    def call_count(self) -> int:
        return int(self._state["calls"])

    @property
    def phase(self) -> str:
        return str(self._state["phase"])

    @phase.setter
    def phase(self, value: str) -> None:
        self._state["phase"] = value

    def bind_tools(self, tools: list[dict]) -> "TraceChatModel":
        bound = self._model.bind_tools(tools)
        names = [tool.get("function", {}).get("name", "<unknown>") for tool in tools]
        return TraceChatModel(
            bound,
            state=self._state,
            bound_tool_names=names,
            preview_chars=self._preview_chars,
            verbose_messages=self._verbose_messages,
        )

    def invoke(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        self._state["calls"] += 1
        print_header(f"LLM call {self.call_count} | phase={self.phase}")
        print(f"bound_tools={', '.join(self._bound_tool_names) or 'none'}")
        print(f"message_count={len(messages)}")
        if messages:
            last = str(messages[-1].content)
            print("last_message:")
            print(indent((last if self._verbose_messages else squash(last))[: self._preview_chars]))

        response = self._model.invoke(messages, **kwargs)
        if not isinstance(response, AIMessage):
            response = AIMessage(content=str(getattr(response, "content", response)))
        if response.tool_calls:
            print("tool_calls:")
            print(indent(json.dumps(response.tool_calls, ensure_ascii=False, indent=2)))
        else:
            print("model_response:")
            print(indent(str(response.content)[: self._preview_chars]))
        return response


@dataclass
class CheckBoard:
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    def add(self, label: str, ok: bool, detail: str = "") -> None:
        self.checks.append((label, ok, detail))
        print(f"{'PASS' if ok else 'FAIL'} {label}" + (f" | {detail}" if detail else ""))

    @property
    def ok(self) -> bool:
        return all(ok for _, ok, _ in self.checks)


def main() -> int:
    args = parse_args()
    run_dir = args.output_dir or default_run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)
    terminal_output = run_dir / "terminal_output.txt"

    with terminal_output.open("w", encoding="utf-8") as log_file:
        tee = Tee(sys.stdout, log_file)
        with redirect_stdout(tee), redirect_stderr(tee):
            code = run_validation(args, run_dir, terminal_output)
    return code


def run_validation(args: argparse.Namespace, run_dir: Path, terminal_output: Path) -> int:
    load_dotenv()
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    replay_dir = run_dir / "replay"
    history_dir = run_dir / "history"
    vector_dir = run_dir / "vector_store"
    config = load_model_config(args.model_config)

    print_header("Phase 1 Real-LLM TownWorld Validation")
    print(f"run_dir={run_dir}")
    print(f"terminal_output={terminal_output}")
    print(f"replay_dir={replay_dir}")
    print(f"days={args.days}")
    print(f"npc_id={args.npc_id}")
    print(f"time_window={minute_label(args.start_minute)}-{minute_label(args.end_minute)}")

    print_header("Model Config")
    print(f"provider={config.model.provider}")
    print(f"model={config.model.model_name}")
    print(f"base_url={config.model.base_url}")
    print(f"api_key_env={config.model.api_key_env}")
    if not config.api_key:
        raise SystemExit(f"Missing API key environment variable: {config.model.api_key_env}")

    real_model = ChatOpenAI(
        model=config.model.model_name,
        base_url=config.model.base_url,
        api_key=SecretStr(config.api_key),
        temperature=args.temperature,
        extra_body={"thinking": {"type": "disabled"}},
    )
    traced_model = TraceChatModel(
        real_model,
        preview_chars=args.preview_chars,
        verbose_messages=args.verbose_messages,
    )
    agent = NPCAgent(llm=traced_model, max_retries=args.max_retries)
    engine = TownWorldEngine(
        create_small_town_state(),
        chroma_client=chromadb.PersistentClient(path=str(vector_dir)),
        history_dir=history_dir,
    )
    checks = CheckBoard()
    forced_guard_result: dict[str, Any] = {
        "forced_guard_check_count": 0,
        "forced_guard_types": [],
        "forced_guard_replay_paths": {},
    }

    for day in range(1, args.days + 1):
        print_header(f"Day {day}: deterministic lifecycle bootstrap")
        engine.start_day_for_resident(
            args.npc_id,
            day=day,
            start_minute=args.start_minute,
            end_minute=args.end_minute,
        )
        print_resident_day_state(engine, args.npc_id, day)

        print_header(f"Day {day}: real LLM schedule generation")
        traced_model.phase = f"day-{day}:schedule"
        try:
            accepted = engine.generate_day_plan_for_resident(
                args.npc_id,
                agent,
                start_minute=args.start_minute,
                end_minute=args.end_minute,
            )
        except Exception as exc:
            checks.add(f"day {day} real LLM schedule accepted", False, repr(exc))
            if not args.continue_on_error:
                write_summary(run_dir, engine, traced_model, checks, terminal_output)
                return 1
        else:
            checks.add(f"day {day} real LLM schedule accepted", bool(accepted))
            print_schedule(accepted)

        print_header(f"Day {day}: real LLM action ticks")
        traced_model.phase = f"day-{day}:actions"
        result = run_multi_npc_day(
            engine,
            agent,
            [args.npc_id],
            start_minute=args.start_minute,
            end_minute=args.end_minute,
            max_ticks=args.max_ticks_per_day,
        )
        for tick in result.ticks:
            print(
                f"tick={tick.tick} minute={minute_label(tick.minute)} "
                f"ran={tick.ran_npc_ids or ['none']} skipped={tick.skipped_npc_ids or ['none']} "
                f"actions={tick.action_count} reflections={tick.reflection_count}"
            )
        print(
            "runner_outcome="
            f"reached_end_minute={result.reached_end_minute} "
            f"all_current_schedules_complete={result.all_current_schedules_complete} "
            f"max_ticks_exhausted={result.max_ticks_exhausted}"
        )
        checks.add(f"day {day} action runner completed", result.ok, result.note)
        if not result.ok:
            if not args.continue_on_error:
                replay_paths = engine.write_replay_artifacts(replay_dir)
                print_header("Replay Paths")
                for name, path in replay_paths.items():
                    print(f"{name}: {path}")
                write_summary(
                    run_dir,
                    engine,
                    traced_model,
                    checks,
                    terminal_output,
                    forced_guard_result=forced_guard_result,
                )
                return 1
            continue

        print_header(f"Day {day}: day-end summary memory")
        summary = engine.end_day_for_resident(args.npc_id, day=day)
        print(summary)
        day_summary = engine.memory_for(args.npc_id).grep(
            "",
            category="impression",
            metadata_filters={"source": "town_day_summary", "day": day},
        )
        checks.add(
            f"day {day} summary memory persisted after completed runner",
            bool(day_summary),
        )

    print_header("Phase 1 forced evidence checks")
    replay_paths = engine.write_replay_artifacts(replay_dir)
    checkpoint_rows = read_jsonl(replay_paths["checkpoints"])
    final_snapshot = checkpoint_rows[-1]["snapshot"] if checkpoint_rows else {}
    real_loop_guard_count = len(engine.loop_guard_events)
    forced_guard_result = force_revision_and_loop_guards(
        args.npc_id,
        checks,
        run_dir=run_dir,
    )
    checks.add("real LLM was called", traced_model.call_count > 0, str(traced_model.call_count))
    checks.add("planning checkpoints replayed", bool(final_snapshot.get("planning_checkpoints")))
    checks.add(
        "real run loop guard replay consistent",
        not engine.loop_guard_events or bool(final_snapshot.get("loop_guard_events")),
        f"real_loop_guard_count={real_loop_guard_count}",
    )
    checks.add(
        "forced guard checks isolated",
        len(engine.loop_guard_events) == real_loop_guard_count,
        f"forced_guard_count={forced_guard_result['forced_guard_check_count']}",
    )
    checks.add("timeline exists", replay_paths["timeline"].exists(), str(replay_paths["timeline"]))

    print_header("Replay Paths")
    for name, path in replay_paths.items():
        print(f"{name}: {path}")

    print_header("Summary")
    print(f"llm_call_count={traced_model.call_count}")
    print(f"planning_log_count={len(engine.planning_log)}")
    print(f"action_log_count={len(engine.action_log)}")
    print(f"loop_guard_count={len(engine.loop_guard_events)}")
    print(f"forced_guard_check_count={forced_guard_result['forced_guard_check_count']}")
    print(f"forced_guard_types={forced_guard_result['forced_guard_types']}")
    print(f"terminal_output={terminal_output}")
    write_summary(
        run_dir,
        engine,
        traced_model,
        checks,
        terminal_output,
        forced_guard_result=forced_guard_result,
    )

    if checks.ok:
        print("RESULT PASS phase1 real-LLM multi-day validation")
        return 0
    print("RESULT FAIL phase1 real-LLM multi-day validation")
    return 1


def force_revision_and_loop_guards(
    npc_id: str,
    checks: CheckBoard,
    *,
    run_dir: Path,
) -> dict[str, Any]:
    guard_dir = run_dir / "forced_guard_check"
    engine = TownWorldEngine(
        create_small_town_state(),
        chroma_client=chromadb.PersistentClient(path=str(guard_dir / "vector_store")),
        history_dir=guard_dir / "history",
    )
    engine.state.clock.day += 1
    engine.state.clock.minute = 8 * 60
    engine.plan_day_for_resident(
        npc_id,
        [
            ScheduleSegment(
                npc_id=npc_id,
                start_minute=8 * 60,
                duration_minutes=60,
                location_id="cafe",
                intent="买咖啡",
            )
        ],
    )
    revised = engine.revise_current_schedule_segment(
        npc_id,
        reason="phase1_real_llm_validation",
        subtasks=["确认柜台状态", "完成后调用 finish_schedule_segment"],
    )
    checks.add("active segment revision recorded", revised is not None)

    engine.state.set_location(npc_id, "home_alice")
    for _ in range(3):
        engine.move_to(npc_id, "clinic")
    for _ in range(3):
        engine.wait(npc_id, 1)
    engine.state.clock.minute = 8 * 60 + 40
    engine.wait(npc_id, 1)

    guard_types = {str(item["guard_type"]) for item in engine.loop_guard_events}
    checks.add("failed-action loop guard recorded", "repeated_failed_action" in guard_types)
    checks.add("low-value loop guard recorded", "repeated_low_value_action" in guard_types)
    checks.add("schedule-drift guard recorded", "schedule_drift" in guard_types)
    replay_paths = engine.write_replay_artifacts(guard_dir / "replay")
    return {
        "forced_guard_check_count": len(engine.loop_guard_events),
        "forced_guard_types": sorted(guard_types),
        "forced_guard_replay_paths": {
            name: str(path) for name, path in replay_paths.items()
        },
    }


def write_summary(
    run_dir: Path,
    engine: TownWorldEngine,
    traced_model: TraceChatModel,
    checks: CheckBoard,
    terminal_output: Path,
    *,
    forced_guard_result: dict[str, Any] | None = None,
) -> None:
    forced_guard_result = forced_guard_result or {
        "forced_guard_check_count": 0,
        "forced_guard_types": [],
        "forced_guard_replay_paths": {},
    }
    summary = {
        "ok": checks.ok,
        "llm_call_count": traced_model.call_count,
        "planning_log_count": len(engine.planning_log),
        "action_log_count": len(engine.action_log),
        "loop_guard_count": len(engine.loop_guard_events),
        **forced_guard_result,
        "terminal_output": str(terminal_output),
        "checks": [
            {"label": label, "ok": ok, "detail": detail}
            for label, ok, detail in checks.checks
        ],
    }
    path = run_dir / "summary.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"summary_json={path}")


def print_resident_day_state(engine: TownWorldEngine, npc_id: str, day: int) -> None:
    resident = engine.state.residents[npc_id]
    day_plan = resident.day_plans[day]
    print(f"schedule_day={resident.schedule_day}")
    print(f"currently={resident.scratch.currently}")
    print(f"wake_up={minute_label(day_plan.wake_up_minute or 0)}")
    print("daily_intentions:")
    for item in day_plan.daily_intentions:
        print(f"- {item}")
    print(f"planning_evidence_count={len(day_plan.planning_evidence)}")


def print_schedule(schedule: list[ScheduleSegment]) -> None:
    for segment in schedule:
        print(
            f"- day={segment.day} {minute_label(segment.start_minute)}-"
            f"{minute_label(segment.end_minute)} {segment.location_id}: {segment.intent}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Phase 1 TownWorld multi-day validation with a real LLM."
    )
    parser.add_argument("--model-config", default="config/model_config.yaml")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--npc-id", default="alice")
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--start-minute", type=int, default=8 * 60)
    parser.add_argument("--end-minute", type=int, default=9 * 60)
    parser.add_argument("--max-ticks-per-day", type=int, default=8)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--preview-chars", type=int, default=1600)
    parser.add_argument("--verbose-messages", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    return parser.parse_args()


def default_run_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("runs") / "town_phase1_real_llm" / stamp


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def minute_label(minute: int) -> str:
    hours, minutes = divmod(minute, 60)
    return f"{hours:02d}:{minutes:02d}"


def print_header(text: str) -> None:
    print("\n" + "=" * 80)
    print(text)
    print("=" * 80)


def indent(text: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


def squash(text: str) -> str:
    return " ".join(text.split())


if __name__ == "__main__":
    raise SystemExit(main())

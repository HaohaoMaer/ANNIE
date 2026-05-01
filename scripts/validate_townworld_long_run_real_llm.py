"""Opt-in real-LLM validation for TownWorld long-run memory influence.

Run:
    python scripts/validate_townworld_long_run_real_llm.py

The script reads ``.env`` and ``config/model_config.yaml``. It writes terminal
output, replay artifacts, and ``summary.json`` under:

    runs/town_long_run_real_llm/<timestamp>/
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
    ReflectionEvidence,
    ScheduleSegment,
    TownWorldEngine,
    create_small_town_state,
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
        preview_chars: int = 1600,
    ) -> None:
        self._model = model
        self._state = state if state is not None else {"calls": 0, "phase": "bootstrap"}
        self._bound_tool_names = bound_tool_names or []
        self._preview_chars = preview_chars

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
        )

    def invoke(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        self._state["calls"] += 1
        print_header(f"LLM call {self.call_count} | phase={self.phase}")
        print(f"bound_tools={', '.join(self._bound_tool_names) or 'none'}")
        if messages:
            print("last_message:")
            print(indent(squash(str(messages[-1].content))[: self._preview_chars]))
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
            return run_validation(args, run_dir, terminal_output)


def run_validation(args: argparse.Namespace, run_dir: Path, terminal_output: Path) -> int:
    load_dotenv()
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    config = load_model_config(args.model_config)
    print_header("TownWorld Long-Run Memory Influence Real-LLM Validation")
    print(f"run_dir={run_dir}")
    print(f"terminal_output={terminal_output}")
    print(f"model={config.model.provider}/{config.model.model_name}")
    print(f"base_url={config.model.base_url}")
    print(f"api_key_env={config.model.api_key_env}")
    if not config.api_key:
        raise SystemExit(f"Missing API key environment variable: {config.model.api_key_env}")

    traced_model = TraceChatModel(
        ChatOpenAI(
            model=config.model.model_name,
            base_url=config.model.base_url,
            api_key=SecretStr(config.api_key),
            temperature=args.temperature,
            extra_body={"thinking": {"type": "disabled"}},
        ),
        preview_chars=args.preview_chars,
    )
    agent = NPCAgent(llm=traced_model, max_retries=args.max_retries)
    engine = TownWorldEngine(
        create_small_town_state(),
        chroma_client=chromadb.PersistentClient(path=str(run_dir / "vector_store")),
        history_dir=run_dir / "history",
    )
    engine.chat_iter = args.chat_iter
    checks = CheckBoard()

    print_header("Day 1: real LLM conversation")
    engine.state.set_location("alice", "cafe")
    engine.state.set_location("bob", "cafe")
    engine.plan_day_for_resident("alice", [_cafe_segment("alice", day=1)], day=1)
    engine.plan_day_for_resident("bob", [_cafe_segment("bob", day=1)], day=1)
    traced_model.phase = "day-1:conversation"
    previous_agent = engine._active_step_agent
    engine._active_step_agent = agent
    try:
        conversation = engine.start_conversation(
            "alice",
            "bob",
            "确认明早咖啡馆推荐，并约定是否需要预留早餐",
        )
    finally:
        engine._active_step_agent = previous_agent
    print(json.dumps(conversation.model_dump(), ensure_ascii=False, indent=2))
    checks.add("conversation succeeded", conversation.status == "succeeded")
    checks.add(
        "conversation wrote relationship memory",
        bool(
            engine.memory_for("alice").grep(
                "",
                category="impression",
                metadata_filters={"source": "town_conversation", "partner_npc_id": "bob"},
            )
        ),
    )
    checks.add(
        "conversation wrote follow-up todo",
        bool(
            engine.memory_for("alice").grep(
                "",
                category="todo",
                metadata_filters={"source": "town_conversation_followup", "status": "open"},
            )
        ),
    )

    print_header("Day 1: real LLM reflection")
    _ensure_reflection_due(engine, "alice")
    traced_model.phase = "day-1:reflection"
    reflected = engine.reflect_for_resident("alice", agent)
    print(f"reflected={reflected}")
    checks.add("reflection persisted", reflected)
    reflection_records = engine.memory_for("alice").grep(
        "",
        category="reflection",
        metadata_filters={"source": "town_reflection"},
    )
    checks.add("reflection memory retrievable", bool(reflection_records))

    print_header("Day 2: memory-influenced planning")
    engine.state.clock.day = 2
    engine.state.clock.minute = args.start_minute
    planning_context = engine.build_daily_planning_context(
        "alice",
        start_minute=args.start_minute,
        end_minute=args.end_minute,
    )
    evidence = planning_context.extra["town"]["planning_evidence"]
    relationship_evidence = planning_context.extra["town"]["relationship_evidence"]
    print("planning evidence:")
    print(indent(json.dumps(evidence, ensure_ascii=False, indent=2)))
    print("relationship evidence:")
    print(indent(json.dumps(relationship_evidence, ensure_ascii=False, indent=2)))
    checks.add("planning context renders memory evidence", bool(evidence))
    checks.add("planning context renders relationship evidence", bool(relationship_evidence))

    traced_model.phase = "day-2:schedule"
    try:
        accepted = engine.generate_day_plan_for_resident(
            "alice",
            agent,
            start_minute=args.start_minute,
            end_minute=args.end_minute,
        )
    except Exception as exc:
        checks.add("real LLM day-2 schedule accepted", False, repr(exc))
        accepted = []
    else:
        checks.add("real LLM day-2 schedule accepted", bool(accepted))
        print_schedule(accepted)
    quality = schedule_quality(engine, accepted)
    for label, ok, detail in quality:
        checks.add(label, ok, detail)

    replay_paths = engine.write_replay_artifacts(run_dir / "replay")
    print_header("Replay Paths")
    for name, path in replay_paths.items():
        print(f"{name}: {path}")

    memory_outcomes = {
        "relationship_memory_count": len(
            engine.memory_for("alice").grep(
                "",
                category="impression",
                metadata_filters={"source": "town_conversation"},
            )
        ),
        "followup_todo_count": len(
            engine.memory_for("alice").grep(
                "",
                category="todo",
                metadata_filters={"source": "town_conversation_followup"},
            )
        ),
        "reflection_memory_count": len(reflection_records),
        "planning_evidence_count": len(evidence),
        "relationship_evidence_count": len(relationship_evidence),
    }
    summary = {
        "ok": checks.ok,
        "llm_call_count": traced_model.call_count,
        "replay_paths": {name: str(path) for name, path in replay_paths.items()},
        "schedule_quality": [
            {"label": label, "ok": ok, "detail": detail}
            for label, ok, detail in quality
        ],
        "loop_warnings": engine.loop_guard_events,
        "memory_reflection_outcomes": memory_outcomes,
        "terminal_output": str(terminal_output),
        "checks": [
            {"label": label, "ok": ok, "detail": detail}
            for label, ok, detail in checks.checks
        ],
    }
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print_header("Summary")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"summary_json={summary_path}")
    print("RESULT PASS long-run real-LLM validation" if checks.ok else "RESULT FAIL")
    return 0 if checks.ok else 1


def _cafe_segment(npc_id: str, *, day: int) -> ScheduleSegment:
    return ScheduleSegment(
        npc_id=npc_id,
        day=day,
        start_minute=8 * 60,
        duration_minutes=60,
        location_id="cafe",
        intent="咖啡馆晨间交流",
    )


def _ensure_reflection_due(engine: TownWorldEngine, npc_id: str) -> None:
    resident = engine.state.residents[npc_id]
    resident.poignancy = max(resident.poignancy, engine.reflection_threshold)
    if not resident.reflection_evidence:
        resident.reflection_evidence.append(
            ReflectionEvidence(
                id=f"{npc_id}_long_run_real_llm_reflection",
                evidence_type="conversation",
                summary="与 Bob 的咖啡馆对话可能影响明天的安排。",
                poignancy=engine.reflection_threshold,
                clock_minute=engine.state.clock.minute,
                metadata={"source": "validation_seed"},
            )
        )


def schedule_quality(
    engine: TownWorldEngine,
    schedule: list[ScheduleSegment],
) -> list[tuple[str, bool, str]]:
    known_locations = set(engine.state.locations)
    ordered = sorted(schedule, key=lambda item: item.start_minute)
    overlaps = [
        f"{prev.start_minute}-{item.start_minute}"
        for prev, item in zip(ordered, ordered[1:])
        if prev.end_minute > item.start_minute
    ]
    return [
        ("schedule quality: non-empty", bool(schedule), str(len(schedule))),
        (
            "schedule quality: known locations",
            all(item.location_id in known_locations for item in schedule),
            ",".join(item.location_id for item in schedule),
        ),
        ("schedule quality: no overlaps", not overlaps, ",".join(overlaps)),
        (
            "schedule quality: planning evidence persisted",
            bool(engine.state.residents["alice"].day_plans[2].planning_evidence),
            str(len(engine.state.residents["alice"].day_plans[2].planning_evidence)),
        ),
    ]


def print_schedule(schedule: list[ScheduleSegment]) -> None:
    for segment in schedule:
        print(
            f"- day={segment.day} {minute_label(segment.start_minute)}-"
            f"{minute_label(segment.end_minute)} {segment.location_id}: {segment.intent}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run long-run TownWorld memory influence validation with a real LLM."
    )
    parser.add_argument("--model-config", default="config/model_config.yaml")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--start-minute", type=int, default=8 * 60)
    parser.add_argument("--end-minute", type=int, default=10 * 60)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--chat-iter", type=int, default=2)
    parser.add_argument("--preview-chars", type=int, default=1600)
    return parser.parse_args()


def default_run_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("runs") / "town_long_run_real_llm" / stamp


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

"""Validate Phase 1 deterministic multi-day TownWorld behavior.

Run:
    python scripts/validate_townworld_phase1_multiday.py

This script intentionally avoids real LLM calls. It exercises the Phase 1
surface: day lifecycle, staged deterministic planning, schedule decomposition
and revision evidence, loop guards, and replay schedule evidence.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import chromadb

from annie.npc.context import AgentContext
from annie.npc.response import AgentResponse
from annie.npc.tools.base_tool import ToolContext
from annie.town import (
    ScheduleSegment,
    TownWorldEngine,
    create_small_town_state,
    run_multi_npc_days,
)


@dataclass
class CheckReport:
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, ok, detail))

    @property
    def ok(self) -> bool:
        return all(ok for _, ok, _ in self.checks)

    def print(self) -> None:
        for name, ok, detail in self.checks:
            status = "PASS" if ok else "FAIL"
            suffix = f" - {detail}" if detail else ""
            print(f"{status} {name}{suffix}")


class DeterministicTownAgent:
    """Small tool-driving agent for deterministic town smoke runs."""

    def run(self, context: AgentContext) -> AgentResponse:
        town = context.extra["town"]
        tool_context = ToolContext(agent_context=context, runtime={})
        location = str(town["location_id"])
        target = town["current_schedule_target_location_id"]
        object_ids = list(town["object_ids"])
        exits = list(town["exits"])

        if location == "home_alice" and "breakfast_table" in object_ids:
            _tool(context, "interact_with").safe_call(
                {"object_id": "breakfast_table", "intent": "吃早餐"},
                tool_context,
            )
            _tool(context, "finish_schedule_segment").safe_call(
                {"note": "早餐已完成"},
                tool_context,
            )
            return AgentResponse()

        if location == "cafe" and "cafe_counter" in object_ids:
            _tool(context, "interact_with").safe_call(
                {"object_id": "cafe_counter", "intent": "买咖啡"},
                tool_context,
            )
            _tool(context, "finish_schedule_segment").safe_call(
                {"note": "咖啡已买好"},
                tool_context,
            )
            return AgentResponse()

        if target in exits:
            _tool(context, "move_to").safe_call({"destination_id": target}, tool_context)
        elif exits:
            _tool(context, "move_to").safe_call({"destination_id": exits[0]}, tool_context)
        return AgentResponse()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate deterministic Phase 1 TownWorld multi-day behavior."
    )
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--npc-id", default="alice")
    parser.add_argument("--start-minute", type=int, default=8 * 60)
    parser.add_argument("--end-minute", type=int, default=10 * 60)
    parser.add_argument("--max-ticks-per-day", type=int, default=16)
    parser.add_argument("--replay-dir", type=Path, default=None)
    args = parser.parse_args()

    report = CheckReport()
    with tempfile.TemporaryDirectory(prefix="annie_town_phase1_") as tmp:
        tmp_path = Path(tmp)
        replay_dir = args.replay_dir or tmp_path / "replay"
        engine = TownWorldEngine(
            create_small_town_state(),
            chroma_client=chromadb.PersistentClient(path=str(tmp_path / "vs")),
            history_dir=tmp_path / "history",
        )

        result = run_multi_npc_days(
            engine,
            DeterministicTownAgent(),
            [args.npc_id],
            days=args.days,
            start_minute=args.start_minute,
            end_minute=args.end_minute,
            max_ticks_per_day=args.max_ticks_per_day,
            replay_dir=replay_dir,
        )

        report.add("multi-day runner completed", result.ok, result.note)
        resident = engine.state.residents[args.npc_id]
        report.add("schedule renewed for final day", resident.schedule_day == args.days)
        report.add(
            "day planning state persisted",
            args.days in resident.day_plans
            and bool(resident.day_plans[args.days].daily_intentions),
        )
        report.add(
            "day summaries stored as memory",
            bool(
                engine.memory_for(args.npc_id).grep(
                    "",
                    category="impression",
                    metadata_filters={"source": "town_day_summary", "day": args.days},
                )
            ),
        )
        report.add(
            "segment decomposition checkpoints recorded",
            any(item["stage"] == "segment_decomposition" for item in engine.planning_log),
        )

        engine.state.clock.day = args.days + 1
        engine.state.clock.minute = args.start_minute
        engine.plan_day_for_resident(
            args.npc_id,
            [
                ScheduleSegment(
                    npc_id=args.npc_id,
                    start_minute=args.start_minute,
                    duration_minutes=60,
                    location_id="cafe",
                    intent="买咖啡",
                )
            ],
        )
        engine.revise_current_schedule_segment(
            args.npc_id,
            reason="phase1_script_waiting",
            subtasks=["确认柜台状态", "完成后调用 finish_schedule_segment"],
        )
        report.add(
            "active segment revision checkpoint recorded",
            any(item["stage"] == "schedule_revision" for item in engine.planning_log),
        )

        trigger_loop_guards(engine, args.npc_id)
        guard_types = {str(item["guard_type"]) for item in engine.loop_guard_events}
        report.add("failed-action loop guard recorded", "repeated_failed_action" in guard_types)
        report.add("low-value loop guard recorded", "repeated_low_value_action" in guard_types)
        report.add("schedule-drift guard recorded", "schedule_drift" in guard_types)

        paths = engine.write_replay_artifacts(replay_dir)
        checkpoint_rows = _read_jsonl(paths["checkpoints"])
        final_snapshot = checkpoint_rows[-1]["snapshot"] if checkpoint_rows else {}
        report.add(
            "replay includes planning checkpoints",
            bool(final_snapshot.get("planning_checkpoints")),
        )
        report.add(
            "replay includes loop guard events",
            bool(final_snapshot.get("loop_guard_events")),
        )
        report.add("timeline artifact exists", paths["timeline"].exists(), str(paths["timeline"]))

        report.print()
        print(f"Replay dir: {replay_dir}")
        if report.ok:
            print("RESULT PASS phase1 deterministic multi-day validation")
            return 0
        print("RESULT FAIL phase1 deterministic multi-day validation")
        return 1


def trigger_loop_guards(engine: TownWorldEngine, npc_id: str) -> None:
    engine.state.set_location(npc_id, "home_alice")
    for _ in range(3):
        engine.move_to(npc_id, "clinic")

    for _ in range(3):
        engine.wait(npc_id, 1)

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
    engine.state.set_location(npc_id, "home_alice")
    engine.state.clock.minute = 8 * 60 + 40
    engine.wait(npc_id, 1)


def _tool(context: AgentContext, name: str):
    return next(tool for tool in context.tools if tool.name == name)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    raise SystemExit(main())

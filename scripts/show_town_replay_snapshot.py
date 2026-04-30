"""Print a deterministic replay snapshot smoke for TownWorld."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import chromadb

from annie.npc.context import AgentContext
from annie.npc.response import AgentResponse
from annie.npc.tools.base_tool import ToolContext
from annie.town import TownEvent, TownWorldEngine, create_small_town_state, run_multi_npc_day


class DrivingAgent:
    def __init__(self) -> None:
        self._spoke = False

    def run(self, context: AgentContext) -> AgentResponse:
        tool_context = ToolContext(agent_context=context, runtime={})
        town = context.extra["town"]
        if (
            context.npc_id == "alice"
            and town["location_id"] == "cafe"
            and "bob" in town["visible_npc_ids"]
            and not self._spoke
        ):
            self._tool(context, "speak_to").safe_call(
                {"target_npc_id": "bob", "text": "我来买一杯咖啡。"},
                tool_context,
            )
            self._spoke = True
            self._tool(context, "finish_schedule_segment").safe_call(
                {"note": "已经向 Bob 点单"},
                tool_context,
            )
            return AgentResponse()

        target = town["current_schedule_target_location_id"]
        if town["location_id"] == target:
            self._tool(context, "finish_schedule_segment").safe_call(
                {"note": "已经在目标地点"},
                tool_context,
            )
            return AgentResponse()

        destination = target if target in town["exits"] else town["exits"][0]
        self._tool(context, "move_to").safe_call(
            {"destination_id": destination},
            tool_context,
        )
        return AgentResponse()

    def _tool(self, context: AgentContext, name: str):
        return next(tool for tool in context.tools if tool.name == name)


class ReflectionAgent:
    def run(self, context: AgentContext) -> AgentResponse:
        return AgentResponse(reflection="Alice 认识到紧急事件需要优先处理。")


class ConversationAgent:
    def __init__(self) -> None:
        self._lines = {
            "alice": ["Bob，今天有什么推荐？", "谢谢你，我先去坐下了。"],
            "bob": ["今天的哥伦比亚豆子不错。", "好的，回头见。"],
        }

    def run(self, context: AgentContext) -> AgentResponse:
        lines = self._lines.setdefault(context.npc_id, [])
        return AgentResponse(dialogue=lines.pop(0) if lines else "嗯。")


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="annie_town_replay_"))
    engine = TownWorldEngine(
        create_small_town_state(),
        chroma_client=chromadb.PersistentClient(path=str(tmp / "vs")),
        history_dir=tmp / "history",
    )
    engine.state.move_npc("alice", "town_square")
    engine.state.events.append(
        TownEvent(
            id="smoke_urgent_reflection",
            minute=8 * 60,
            location_id="town_square",
            actor_id="gm",
            event_type="urgent",
            summary="广场响起紧急铃声。",
        )
    )
    engine.build_context("alice", "观察紧急事件。")
    engine.finish_schedule_segment("alice", "处理紧急铃声")
    engine.state.move_npc("alice", "cafe")
    conversation_agent = ConversationAgent()
    engine._active_step_agent = conversation_agent
    try:
        engine.start_conversation("alice", "bob", "咖啡推荐")
    finally:
        engine._active_step_agent = None

    result = run_multi_npc_day(
        engine,
        DrivingAgent(),
        ["alice", "bob", "clara"],
        start_minute=8 * 60,
        max_ticks=1,
        replay_dir=tmp / "replay",
        reflection_agent=ReflectionAgent(),
    )

    checkpoints = [
        json.loads(line)
        for line in result.replay_paths["checkpoints"].read_text().splitlines()
    ]
    reflections = [
        json.loads(line)
        for line in result.replay_paths["reflections"].read_text().splitlines()
    ]
    first_snapshot = checkpoints[0]["snapshot"]

    print(f"Replay dir: {result.replay_paths['checkpoints'].parent}")
    print(
        "Residents:",
        ", ".join(
            f"{npc_id}@{resident['location_id']}"
            for npc_id, resident in first_snapshot["residents"].items()
        ),
    )
    print("Conversation sessions:", first_snapshot["conversation_sessions"])
    print("Reflection events:", reflections)

    checks = {
        "checkpoint snapshot present": bool(first_snapshot["residents"]),
        "resident schedule/action fields present": all(
            "current_schedule" in resident and "current_action" in resident
            for resident in first_snapshot["residents"].values()
        ),
        "reflection artifact present": len(reflections) == 1,
        "reflection event in checkpoint": checkpoints[0]["snapshot"]["reflection_events"]
        == reflections,
    }
    for label, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'} {label}")
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

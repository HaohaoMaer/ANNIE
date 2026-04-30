"""Print a deterministic relationship-cue smoke snapshot for TownWorld."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import chromadb

from annie.npc.context import AgentContext
from annie.npc.response import AgentResponse
from annie.town import TownWorldEngine
from annie.town.content import create_small_town_state


class _ConversationAgent:
    def __init__(self) -> None:
        self.turns = {
            "alice": ["Bob，今天有什么咖啡推荐吗？", "谢谢，我先去坐下了。"],
            "bob": ["今天的哥伦比亚豆子很适合清晨。", "好的，我马上准备，回头见。"],
        }

    def run(self, context: AgentContext) -> AgentResponse:
        if context.extra.get("town", {}).get("conversation_session_id"):
            lines = self.turns.setdefault(context.npc_id, [])
            return AgentResponse(dialogue=lines.pop(0) if lines else "嗯。")
        return AgentResponse()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="annie_town_relationship_") as tmp:
        tmp_path = Path(tmp)
        engine = TownWorldEngine(
            create_small_town_state(),
            chroma_client=chromadb.PersistentClient(path=str(tmp_path / "vector_store")),
            history_dir=tmp_path / "history",
        )
        engine.state.move_npc("alice", "town_square")
        engine.state.move_npc("alice", "cafe")
        agent = _ConversationAgent()

        engine._active_step_agent = agent
        try:
            result = engine.start_conversation("alice", "bob", "咖啡推荐")
        finally:
            engine._active_step_agent = None

        session = next(iter(engine.state.conversation_sessions.values()))
        engine.state.clock.minute = session.ended_minute or engine.state.clock.minute
        context = engine.build_context("alice", "考虑是否继续和 Bob 交流。")
        engine._active_step_agent = agent
        try:
            repeat = engine.start_conversation("alice", "bob", "再聊咖啡")
        finally:
            engine._active_step_agent = None
        impressions = engine.memory_for("alice").grep(
            "",
            category="impression",
            metadata_filters={
                "source": "town_conversation",
                "partner_npc_id": "bob",
            },
        )

        snapshot = {
            "conversation_result": result.model_dump(),
            "impression_metadata": impressions[0].metadata if impressions else {},
            "relationship_cues": context.extra["town"]["relationship_cues"],
            "cooldown_rejection": engine.action_log[-1],
            "repeat_status": repeat.status,
            "repeat_reason": repeat.reason,
        }

        print("TOWN RELATIONSHIP CUES SMOKE")
        print("=" * 30)
        print(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str))
        print()

        checks = {
            "conversation impression has relationship metadata": bool(impressions)
            and impressions[0].metadata.get("conversation_session_id") == session.id
            and impressions[0].metadata.get("partner_npc_id") == "bob"
            and impressions[0].metadata.get("close_reason") == session.close_reason,
            "later context includes relationship cue": bool(
                context.extra["town"]["relationship_cues"]
            )
            and context.extra["town"]["relationship_cues"][0]["partner_npc_id"] == "bob",
            "cooldown rejection is logged": repeat.status == "failed"
            and repeat.reason == "recent_conversation_cooldown"
            and engine.action_log[-1]["status"] == "failed",
        }
        for label, ok in checks.items():
            print(f"{'PASS' if ok else 'FAIL'} {label}")
        return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

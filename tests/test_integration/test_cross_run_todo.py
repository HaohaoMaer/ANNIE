"""Integration test: cross-run todo persistence via plan_todo.

Scenario:
  Run 1 — adds a todo via plan_todo(add).
  Run 2 — <todo> in the Executor system prompt contains the item; completes it.
  Run 3 — <todo> shows (none).
"""
from __future__ import annotations

import chromadb
import pytest
from langchain_core.messages import AIMessage, BaseMessage

from annie.npc.agent import NPCAgent
from annie.npc.state import NPCProfile
from annie.world_engine import DefaultWorldEngine


class _StubLLM:
    """Round-robin canned AIMessage responses."""

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list[list[BaseMessage]] = []

    def invoke(self, messages, **_):
        self.calls.append(list(messages))
        if not self._responses:
            return AIMessage(content="")
        nxt = self._responses.pop(0)
        if isinstance(nxt, AIMessage):
            return nxt
        return AIMessage(content=str(nxt))

    def bind_tools(self, tools):  # noqa: ARG002
        return self


@pytest.fixture
def tmp_chroma(tmp_path):
    return chromadb.PersistentClient(path=str(tmp_path / "vs"))


def test_todo_persists_across_runs(tmp_path, tmp_chroma):
    """Full three-run cycle: add → visible in run2 → complete → invisible in run3."""
    we = DefaultWorldEngine(chroma_client=tmp_chroma, history_dir=tmp_path / "hist")
    we.register_profile("npc1", NPCProfile(name="NPC1"))

    # ------------------------------------------------------------------ Run 1
    # Executor calls plan_todo(add), then gives a final answer.
    add_todo_ai = AIMessage(
        content="",
        tool_calls=[{
            "name": "plan_todo",
            "args": {"op": "add", "content": "去厨房找匕首"},
            "id": "call_add",
        }],
    )
    llm1 = _StubLLM([
        '{"skip": true}',  # planner
        add_todo_ai,        # executor: add todo
        "NPC1 nods.",       # executor: final answer
        "REFLECTION: r1.\nFACTS: []\nRELATIONSHIP_NOTES: []",
    ])
    ctx1 = we.build_context("npc1", event="Event 1.")
    resp1 = NPCAgent(llm=llm1).run(ctx1)
    we.handle_response("npc1", resp1)

    # Retrieve the assigned todo_id from memory so we can complete it in run2.
    open_todos = we.memory_for("npc1").grep(
        "", category="todo", metadata_filters={"status": "open"}, k=10,
    )
    assert len(open_todos) == 1, "run1 should have stored exactly one open todo"
    todo_id = open_todos[0].metadata["todo_id"]

    # ------------------------------------------------------------------ Run 2
    # Executor completes the todo, then gives a final answer.
    complete_todo_ai = AIMessage(
        content="",
        tool_calls=[{
            "name": "plan_todo",
            "args": {"op": "complete", "todo_id": todo_id},
            "id": "call_complete",
        }],
    )
    llm2 = _StubLLM([
        '{"skip": true}',
        complete_todo_ai,
        "NPC1 found the dagger.",
        "REFLECTION: r2.\nFACTS: []\nRELATIONSHIP_NOTES: []",
    ])
    ctx2 = we.build_context("npc1", event="Event 2.")
    resp2 = NPCAgent(llm=llm2).run(ctx2)
    we.handle_response("npc1", resp2)

    # The executor system prompt in run2 should contain the open todo.
    system_content_run2 = llm2.calls[1][0].content
    assert "去厨房找匕首" in system_content_run2, (
        "<todo> section in run2 should list the open todo from run1"
    )
    assert todo_id in system_content_run2

    # ------------------------------------------------------------------ Run 3
    # After completion, <todo> should be (none).
    llm3 = _StubLLM([
        '{"skip": true}',
        "NPC1 relaxes.",
        "REFLECTION: r3.\nFACTS: []\nRELATIONSHIP_NOTES: []",
    ])
    ctx3 = we.build_context("npc1", event="Event 3.")
    NPCAgent(llm=llm3).run(ctx3)

    system_content_run3 = llm3.calls[1][0].content
    assert "去厨房找匕首" not in system_content_run3, (
        "completed todo should not appear in run3 <todo> section"
    )
    # The todo block should render as (none)
    assert "(none)" in system_content_run3

"""Unit tests for run-scoped recall dedup.

The ``_recall_seen_ids`` set in ``AgentContext.extra`` prevents records shown
in ``<working_memory>`` from appearing again in tool call responses.
"""

from __future__ import annotations

from annie.npc.context import AgentContext
from annie.npc.memory.interface import MemoryRecord
from annie.npc.sub_agents.memory_agent import MemoryAgent
from annie.npc.tools.base_tool import ToolContext
from annie.npc.tools.builtin import MemoryGrepTool, MemoryRecallTool


# ---------------------------------------------------------------------------
# Stub memory that returns a fixed list of records
# ---------------------------------------------------------------------------

class _StubMemory:
    def __init__(self, records: list[MemoryRecord]) -> None:
        self._records = records

    def recall(self, query, categories=None, k=5):
        return list(self._records[:k])

    def grep(self, pattern, category=None, metadata_filters=None, k=20):
        return list(self._records[:k])

    def remember(self, content, category="semantic", metadata=None):
        pass

    def build_context(self, query):
        # Simulate: join all contents
        return "\n".join(f"- {r.content}" for r in self._records) or "No relevant memories."


def _records(*contents: str) -> list[MemoryRecord]:
    return [MemoryRecord(content=c, category="semantic") for c in contents]


def _make_ctx(memory, seen_ids):
    agent_ctx = AgentContext(
        npc_id="test",
        input_event="event",
        memory=memory,
        extra={"_recall_seen_ids": seen_ids},
    )
    return ToolContext(agent_context=agent_ctx)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_build_context_populates_seen_ids():
    """After build_context, recall should return no new results for same contents."""
    recs = _records("fact A", "fact B")
    mem = _StubMemory(recs)
    seen: set[str] = set()

    agent = MemoryAgent(mem)
    agent.build_context("query", seen_ids=seen)

    # seen_ids must now contain the contents surfaced by build_context
    assert "fact A" in seen
    assert "fact B" in seen


def test_recall_tool_filters_seen_ids():
    """memory_recall returns only records not already in seen_ids."""
    recs = _records("fact A", "fact B", "fact C")
    mem = _StubMemory(recs)
    seen: set[str] = {"fact A"}  # "fact A" already shown in working_memory

    tool = MemoryRecallTool()
    ctx = _make_ctx(mem, seen)
    result = tool.call({"query": "anything", "k": 10}, ctx)

    returned_contents = {r["content"] for r in result["records"]}
    assert "fact A" not in returned_contents, "fact A was in seen_ids and must be filtered"
    assert "fact B" in returned_contents
    assert "fact C" in returned_contents


def test_recall_tool_registers_new_records():
    """After a tool call, new records are added to seen_ids."""
    recs = _records("fact X", "fact Y")
    mem = _StubMemory(recs)
    seen: set[str] = set()

    tool = MemoryRecallTool()
    ctx = _make_ctx(mem, seen)
    tool.call({"query": "anything", "k": 10}, ctx)

    assert "fact X" in seen
    assert "fact Y" in seen


def test_grep_tool_filters_seen_ids():
    """memory_grep also filters already-seen records."""
    recs = _records("grep hit 1", "grep hit 2")
    mem = _StubMemory(recs)
    seen: set[str] = {"grep hit 1"}

    tool = MemoryGrepTool()
    ctx = _make_ctx(mem, seen)
    result = tool.call({"pattern": "grep"}, ctx)

    returned = {r["content"] for r in result["records"]}
    assert "grep hit 1" not in returned
    assert "grep hit 2" in returned


def test_no_seen_ids_passes_through():
    """When _recall_seen_ids is absent, all records are returned (no dedup)."""
    recs = _records("fact A", "fact B")
    mem = _StubMemory(recs)
    agent_ctx = AgentContext(npc_id="test", input_event="e", memory=mem, extra={})
    ctx = ToolContext(agent_context=agent_ctx)

    tool = MemoryRecallTool()
    result = tool.call({"query": "anything", "k": 10}, ctx)
    returned = {r["content"] for r in result["records"]}
    assert "fact A" in returned
    assert "fact B" in returned

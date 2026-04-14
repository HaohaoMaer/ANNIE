"""Roundtrip test for the memory_grep built-in tool."""

from __future__ import annotations

from annie.npc.context import AgentContext
from annie.npc.memory.interface import MemoryRecord
from annie.npc.tools.base_tool import ToolContext
from annie.npc.tools.builtin import MemoryGrepTool, default_builtin_tools


class _FakeMemory:
    def __init__(self, records):
        self._records = records
        self.last_call: dict = {}

    def grep(self, pattern, category=None, metadata_filters=None, k=20):
        self.last_call = dict(
            pattern=pattern, category=category, metadata_filters=metadata_filters, k=k,
        )
        return self._records

    def recall(self, query, categories=None, k=5):
        return []

    def remember(self, content, category="semantic", metadata=None):
        return None

    def build_context(self, query):
        return ""


def test_default_builtin_tools_includes_memory_grep():
    names = [t.name for t in default_builtin_tools()]
    assert "memory_grep" in names


def test_memory_grep_roundtrip():
    fake = _FakeMemory([
        MemoryRecord(content="李四在餐车", category="episodic", relevance_score=1.0),
    ])
    agent_ctx = AgentContext(npc_id="x", input_event="e", memory=fake)
    ctx = ToolContext(agent_context=agent_ctx)
    tool = MemoryGrepTool()
    result = tool.safe_call(
        {"pattern": "李四", "category": "episodic", "k": 10}, ctx,
    )
    assert result["success"] is True
    assert result["tool"] == "memory_grep"
    assert result["result"]["pattern"] == "李四"
    assert len(result["result"]["records"]) == 1
    assert fake.last_call == {
        "pattern": "李四",
        "category": "episodic",
        "metadata_filters": None,
        "k": 10,
    }

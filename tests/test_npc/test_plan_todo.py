"""Unit tests for the plan_todo built-in tool.

Covers: add→list contains; complete→list excludes; double-complete idempotent;
completing one todo doesn't affect others; missing-arg error paths.
"""
from __future__ import annotations

from annie.npc.context import AgentContext
from annie.npc.memory.interface import MemoryRecord
from annie.npc.tools.base_tool import ToolContext
from annie.npc.tools.builtin import PlanTodoTool


# ---------------------------------------------------------------------------
# In-memory fake MemoryInterface that correctly handles empty-pattern grep
# ---------------------------------------------------------------------------

class _FakeMemory:
    """Minimal in-memory MemoryInterface for unit tests."""

    def __init__(self):
        self._records: list[MemoryRecord] = []

    def remember(self, content, category="semantic", metadata=None):
        self._records.append(
            MemoryRecord(content=content, category=category, metadata=metadata or {})
        )

    def grep(self, pattern, category=None, metadata_filters=None, k=20):
        """Returns newest-first; empty pattern skips substring matching."""
        results: list[MemoryRecord] = []
        for r in reversed(self._records):  # newest first
            if category is not None and r.category != category:
                continue
            if metadata_filters:
                if not all(r.metadata.get(key) == val for key, val in metadata_filters.items()):
                    continue
            # Empty pattern = filter only, no substring check
            if pattern and pattern.casefold() not in r.content.casefold():
                continue
            results.append(r)
            if len(results) >= k:
                break
        return results

    def recall(self, query, categories=None, k=5):
        return []

    def build_context(self, query):
        return ""


def _ctx(mem: _FakeMemory) -> ToolContext:
    agent_ctx = AgentContext(npc_id="test", input_event="e", memory=mem)
    return ToolContext(agent_context=agent_ctx)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_add_then_list_contains_item():
    mem = _FakeMemory()
    tool = PlanTodoTool()
    ctx = _ctx(mem)

    res = tool.call({"op": "add", "content": "去厨房找匕首"}, ctx)
    assert res["success"] is True
    todo_id = res["todo_id"]
    assert todo_id  # non-empty

    list_res = tool.call({"op": "list"}, ctx)
    todos = list_res["todos"]
    assert len(todos) == 1
    assert todos[0]["todo_id"] == todo_id
    assert "匕首" in todos[0]["content"]


def test_complete_removes_from_list():
    mem = _FakeMemory()
    tool = PlanTodoTool()
    ctx = _ctx(mem)

    add_res = tool.call({"op": "add", "content": "任务A"}, ctx)
    todo_id = add_res["todo_id"]

    comp_res = tool.call({"op": "complete", "todo_id": todo_id}, ctx)
    assert comp_res["success"] is True

    list_res = tool.call({"op": "list"}, ctx)
    assert list_res["todos"] == []


def test_double_complete_second_fails():
    """Second complete on the same id should fail since it's no longer open."""
    mem = _FakeMemory()
    tool = PlanTodoTool()
    ctx = _ctx(mem)

    add_res = tool.call({"op": "add", "content": "任务B"}, ctx)
    todo_id = add_res["todo_id"]

    res1 = tool.call({"op": "complete", "todo_id": todo_id}, ctx)
    res2 = tool.call({"op": "complete", "todo_id": todo_id}, ctx)

    assert res1["success"] is True
    assert res2["success"] is False  # already closed — must fail
    assert "already closed" in res2["error"] or "not found" in res2["error"]

    list_res = tool.call({"op": "list"}, ctx)
    assert list_res["todos"] == []


def test_complete_only_removes_target():
    mem = _FakeMemory()
    tool = PlanTodoTool()
    ctx = _ctx(mem)

    res_a = tool.call({"op": "add", "content": "任务A"}, ctx)
    res_b = tool.call({"op": "add", "content": "任务B"}, ctx)
    id_a = res_a["todo_id"]
    id_b = res_b["todo_id"]

    tool.call({"op": "complete", "todo_id": id_a}, ctx)

    list_res = tool.call({"op": "list"}, ctx)
    ids = {t["todo_id"] for t in list_res["todos"]}
    assert id_a not in ids
    assert id_b in ids


def test_add_missing_content_returns_error():
    mem = _FakeMemory()
    tool = PlanTodoTool()
    ctx = _ctx(mem)

    res = tool.call({"op": "add"}, ctx)
    assert res["success"] is False
    assert "content" in res["error"]


def test_complete_missing_todo_id_returns_error():
    mem = _FakeMemory()
    tool = PlanTodoTool()
    ctx = _ctx(mem)

    res = tool.call({"op": "complete"}, ctx)
    assert res["success"] is False
    assert "todo_id" in res["error"]


def test_list_empty_when_no_todos():
    mem = _FakeMemory()
    tool = PlanTodoTool()
    ctx = _ctx(mem)

    res = tool.call({"op": "list"}, ctx)
    assert res["success"] is True
    assert res["todos"] == []


def test_complete_unknown_id_returns_failure():
    """Completing a nonexistent todo_id returns success=False with clear error."""
    mem = _FakeMemory()
    tool = PlanTodoTool()
    ctx = _ctx(mem)

    res = tool.call({"op": "complete", "todo_id": "deadbeef"}, ctx)
    assert res["success"] is False
    assert "deadbeef" in res["error"] or "not found" in res["error"]


def test_list_returns_timestamp_field():
    """list() response includes timestamp for each todo."""
    mem = _FakeMemory()
    tool = PlanTodoTool()
    ctx = _ctx(mem)

    tool.call({"op": "add", "content": "Do something"}, ctx)
    list_res = tool.call({"op": "list"}, ctx)

    todos = list_res["todos"]
    assert len(todos) == 1
    assert "timestamp" in todos[0]
    assert todos[0]["timestamp"] != "?"  # created_at was set


def test_list_returns_newest_first():
    """Multiple todos are returned newest-first (by timestamp)."""
    import time

    mem = _FakeMemory()
    tool = PlanTodoTool()
    ctx = _ctx(mem)

    tool.call({"op": "add", "content": "First todo"}, ctx)
    time.sleep(0.01)  # ensure distinct timestamps
    tool.call({"op": "add", "content": "Second todo"}, ctx)

    list_res = tool.call({"op": "list"}, ctx)
    todos = list_res["todos"]
    assert len(todos) == 2
    # Newest (Second todo) must appear first
    assert todos[0]["content"] == "Second todo"
    assert todos[1]["content"] == "First todo"

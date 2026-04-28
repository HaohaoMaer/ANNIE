"""Default world-engine tools."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from collections.abc import Callable
from typing import Any, Literal, TypeVar, cast

from pydantic import BaseModel, Field

from annie.npc.memory.interface import MEMORY_CATEGORY_TODO
from annie.npc.response import ActionRequest, ActionResult
from annie.npc.tools.base_tool import ToolContext, ToolDef

_T = TypeVar("_T", bound=BaseModel)


def _coerce(input_data: BaseModel | dict, model: type[_T]) -> _T:
    if isinstance(input_data, model):
        return input_data
    return model(**cast(dict, input_data))


class PlanTodoInput(BaseModel):
    op: Literal["add", "complete", "list"] = Field(
        ..., description="Operation: add a new todo, complete by id, or list open todos.",
    )
    content: str | None = Field(None, description="Todo content for op='add'.")
    todo_id: str | None = Field(None, description="Target todo id for op='complete'.")


class PlanTodoTool(ToolDef):
    name = "plan_todo"
    description = (
        "Manage cross-run goals as category='todo' memories. "
        "'add' creates an open todo, 'complete' appends a close event, "
        "and 'list' returns currently-open todos."
    )
    input_schema = PlanTodoInput
    is_read_only = False

    def call(self, input: BaseModel | dict, ctx: ToolContext) -> Any:
        inp = _coerce(input, PlanTodoInput)
        memory = ctx.agent_context.memory

        if inp.op == "add":
            if not inp.content:
                return {"success": False, "error": "content required for op='add'"}
            todo_id = uuid.uuid4().hex[:8]
            created_at = datetime.now(UTC).isoformat()
            memory.remember(
                inp.content,
                category=MEMORY_CATEGORY_TODO,
                metadata={"status": "open", "todo_id": todo_id, "created_at": created_at},
            )
            return {"success": True, "op": "add", "todo_id": todo_id}

        if inp.op == "complete":
            if not inp.todo_id:
                return {"success": False, "error": "todo_id required for op='complete'"}
            existing = memory.grep(
                "",
                category=MEMORY_CATEGORY_TODO,
                metadata_filters={"todo_id": inp.todo_id, "status": "open"},
                k=1,
            )
            already_closed = memory.grep(
                "",
                category=MEMORY_CATEGORY_TODO,
                metadata_filters={"closes": inp.todo_id, "status": "closed"},
                k=1,
            )
            if not existing or already_closed:
                return {
                    "success": False,
                    "error": f"todo '{inp.todo_id}' not found or already closed",
                }
            memory.remember(
                f"[DONE] {inp.todo_id}",
                category=MEMORY_CATEGORY_TODO,
                metadata={"status": "closed", "closes": inp.todo_id},
            )
            return {"success": True, "op": "complete", "todo_id": inp.todo_id}

        todos = render_open_todos(memory)
        return {"success": True, "op": "list", "todos": todos}


class WorldActionInput(BaseModel):
    type: str = Field(..., description="Verb-style world action label, e.g. move, search, take.")
    payload: dict[str, Any] = Field(default_factory=dict)


class WorldActionTool(ToolDef):
    name = "world_action"
    description = (
        "Attempt one world action immediately. The world engine checks state, "
        "rules, and permissions, then returns an ActionResult observation. Use "
        "the returned observation before choosing the next action. Continue "
        "requesting follow-up world actions until the current objective is "
        "completed or the observations show it is impossible."
    )
    input_schema = WorldActionInput
    is_read_only = False

    def __init__(
        self,
        npc_id: str,
        execute_action: Callable[[str, ActionRequest], ActionResult],
    ) -> None:
        self._npc_id = npc_id
        self._execute_action = execute_action

    def call(self, input: BaseModel | dict, ctx: ToolContext) -> Any:
        inp = _coerce(input, WorldActionInput)
        action = ActionRequest(type=inp.type, payload=inp.payload)
        result = self._execute_action(self._npc_id, action)
        ctx.runtime.setdefault("action_results", []).append(result)
        return result.model_dump()


def render_todo_text(memory: Any) -> str:
    todos = render_open_todos(memory)
    if not todos:
        return "(none)"
    return "\n".join(f"- [{t['todo_id']}] {t['content']}" for t in todos)


def render_open_todos(memory: Any) -> list[dict[str, Any]]:
    opens = memory.grep(
        "", category=MEMORY_CATEGORY_TODO,
        metadata_filters={"status": "open"}, k=50,
    )
    closeds = memory.grep(
        "", category=MEMORY_CATEGORY_TODO,
        metadata_filters={"status": "closed"}, k=50,
    )
    closed_ids = {r.metadata.get("closes") for r in closeds}
    alive = [
        {
            "todo_id": r.metadata.get("todo_id"),
            "content": r.content,
            "timestamp": r.metadata.get("created_at", "?"),
        }
        for r in opens
        if r.metadata.get("todo_id") not in closed_ids
    ]
    alive.sort(key=lambda t: t["timestamp"], reverse=True)
    return alive

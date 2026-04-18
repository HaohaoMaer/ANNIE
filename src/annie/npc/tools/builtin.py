"""Built-in NPC Agent tools.

Three universal tools every world engine gets for free:

* ``memory_recall`` — MemoryInterface.recall wrapper (category list filter)
* ``memory_store`` — MemoryInterface.remember wrapper
* ``inner_monologue`` — lets the LLM emit non-dialogue reasoning

All built-ins follow the ToolDef contract and reach MemoryInterface via
``ToolContext.agent_context.memory`` (never via ctor injection).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal, TypeVar, cast

from pydantic import BaseModel, Field

from annie.npc.memory.interface import (
    MEMORY_CATEGORY_SEMANTIC,
    MEMORY_CATEGORY_TODO,
    MemoryRecord,
)
from annie.npc.tools.base_tool import ToolContext, ToolDef

_T = TypeVar("_T", bound=BaseModel)


def _coerce(input_data: BaseModel | dict, model: type[_T]) -> _T:
    if isinstance(input_data, model):
        return input_data
    return model(**cast(dict, input_data))


def _dedup_filter(
    records: list[MemoryRecord],
    extra: dict[str, Any],
) -> list[MemoryRecord]:
    """Filter out records already shown in <working_memory> this run.

    Uses ``extra["_recall_seen_ids"]`` (a ``set[str]`` of content strings).
    New records are added to the set so subsequent calls won't return them.
    If the key is absent (e.g. unit tests without agent scaffolding), pass through.
    """
    seen: set[str] | None = extra.get("_recall_seen_ids")
    if seen is None:
        return records
    out: list[MemoryRecord] = []
    for r in records:
        if r.content in seen:
            continue
        seen.add(r.content)
        out.append(r)
    return out


class MemoryRecallInput(BaseModel):
    query: str = Field(..., description="Natural-language query to search memory.")
    categories: list[str] | None = Field(
        None,
        description="Optional category filter (e.g. ['episodic', 'impression']). None = all.",
    )
    k: int = Field(5, description="Max number of records.")


class MemoryRecallTool(ToolDef):
    name = "memory_recall"
    description = "Retrieve NPC long-term memory relevant to a query."
    input_schema = MemoryRecallInput
    is_read_only = True

    def call(self, input: BaseModel | dict, ctx: ToolContext) -> Any:
        inp = _coerce(input, MemoryRecallInput)
        records = ctx.agent_context.memory.recall(
            inp.query, categories=inp.categories, k=inp.k,
        )
        records = _dedup_filter(records, ctx.agent_context.extra)
        return {
            "query": inp.query,
            "records": [r.model_dump() for r in records],
        }


class MemoryGrepInput(BaseModel):
    pattern: str = Field(..., description="Case-insensitive substring to match against memory content.")
    category: str | None = Field(
        None,
        description="Optional single-category filter (e.g. 'episodic'). None = all categories.",
    )
    metadata_filters: dict[str, Any] | None = Field(
        None,
        description="Optional metadata equality filters (e.g. {'person': '李四'}).",
    )
    k: int = Field(20, description="Max number of records.")


class MemoryGrepTool(ToolDef):
    name = "memory_grep"
    description = (
        "Literal/metadata search over NPC long-term memory. "
        "Use this for proper-name lookups or exact-phrase recall where vector "
        "similarity is unreliable. Complements memory_recall (semantic)."
    )
    input_schema = MemoryGrepInput
    is_read_only = True

    def call(self, input: BaseModel | dict, ctx: ToolContext) -> Any:
        inp = _coerce(input, MemoryGrepInput)
        records = ctx.agent_context.memory.grep(
            inp.pattern,
            category=inp.category,
            metadata_filters=inp.metadata_filters,
            k=inp.k,
        )
        records = _dedup_filter(records, ctx.agent_context.extra)
        return {
            "pattern": inp.pattern,
            "records": [r.model_dump() for r in records],
        }


class MemoryStoreInput(BaseModel):
    content: str = Field(..., description="The content of the memory to store.")
    category: str = Field(MEMORY_CATEGORY_SEMANTIC, description="Memory category label.")
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryStoreTool(ToolDef):
    name = "memory_store"
    description = "Persist a new long-term memory entry for this NPC."
    input_schema = MemoryStoreInput
    is_read_only = False

    def call(self, input: BaseModel | dict, ctx: ToolContext) -> Any:
        inp = _coerce(input, MemoryStoreInput)
        ctx.agent_context.memory.remember(
            inp.content, category=inp.category, metadata=inp.metadata,
        )
        return {"stored": True, "category": inp.category}


class UseSkillInput(BaseModel):
    skill_name: str = Field(..., description="Name of the skill to activate.")
    args: dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form args; serialized as JSON into the skill prompt.",
    )


class UseSkillTool(ToolDef):
    name = "use_skill"
    description = (
        "Activate a skill: appends the skill's guidance prompt as a SystemMessage "
        "and temporarily unlocks the skill's extra_tools for the rest of this "
        "Executor loop. Pick a skill by name from <available_skills>."
    )
    input_schema = UseSkillInput
    is_read_only = False

    def call(self, input: BaseModel | dict, ctx: ToolContext) -> Any:
        inp = _coerce(input, UseSkillInput)
        extra = ctx.agent_context.extra
        skill_agent = extra.get("_skill_agent")
        tool_registry = extra.get("_tool_registry")
        messages = extra.get("_messages")
        if skill_agent is None or tool_registry is None or messages is None:
            return {
                "activated": False,
                "error": "use_skill invoked outside an Executor tool loop",
            }
        try:
            frame_id = skill_agent.activate(
                inp.skill_name, inp.args, messages, tool_registry,
            )
        except ValueError as e:
            return {"activated": False, "error": str(e)}
        extra.setdefault("_skill_frames", []).append(frame_id)
        return {
            "activated": True,
            "skill": inp.skill_name,
            "frame_id": frame_id,
        }


class InnerMonologueInput(BaseModel):
    thought: str = Field(..., description="Internal thought the NPC wants to record.")


class InnerMonologueTool(ToolDef):
    name = "inner_monologue"
    description = (
        "Record a private inner thought. Use this to reason aloud without producing dialogue."
    )
    input_schema = InnerMonologueInput
    is_read_only = True

    def call(self, input: BaseModel | dict, ctx: ToolContext) -> Any:
        inp = _coerce(input, InnerMonologueInput)
        thoughts = ctx.agent_context.extra.setdefault("_inner_thoughts", [])
        thoughts.append(inp.thought)
        return {"thought": inp.thought}


class PlanTodoInput(BaseModel):
    op: Literal["add", "complete", "list"] = Field(
        ..., description="Operation: add a new todo, complete by id, or list open todos.",
    )
    content: str | None = Field(
        None, description="Todo content (required for op='add').",
    )
    todo_id: str | None = Field(
        None, description="Target todo id (required for op='complete').",
    )


class PlanTodoTool(ToolDef):
    name = "plan_todo"
    description = (
        "Manage cross-run goals as category='todo' memories. "
        "'add' creates a new open todo (returns todo_id). "
        "'complete' closes a todo by id. "
        "'list' returns all currently-open todos."
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
            # Verify: open record exists.
            existing = memory.grep(
                "",
                category=MEMORY_CATEGORY_TODO,
                metadata_filters={"todo_id": inp.todo_id, "status": "open"},
                k=1,
            )
            if not existing:
                return {
                    "success": False,
                    "error": f"todo '{inp.todo_id}' not found or already closed",
                }
            # Verify: no closed record already recorded (event-stream model).
            already_closed = memory.grep(
                "",
                category=MEMORY_CATEGORY_TODO,
                metadata_filters={"closes": inp.todo_id, "status": "closed"},
                k=1,
            )
            if already_closed:
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

        # op == "list"
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
        # Newest first: sort by timestamp descending (ISO8601 sorts lexicographically).
        alive.sort(key=lambda t: t["timestamp"], reverse=True)
        return {"success": True, "op": "list", "todos": alive}


def default_builtin_tools() -> list[ToolDef]:
    """Return a fresh list of built-in ToolDef instances."""
    return [
        MemoryRecallTool(),
        MemoryGrepTool(),
        MemoryStoreTool(),
        InnerMonologueTool(),
        UseSkillTool(),
        PlanTodoTool(),
    ]

"""Built-in NPC Agent tools.

Universal tools every world engine gets for free:

* ``memory_recall`` — MemoryInterface.recall wrapper (category list filter)
* ``memory_store`` — declare a MemoryUpdate; it does not persist directly
* ``declare_action`` — declare an ActionRequest
* ``request_action`` — submit a deferred world action and pause this run
* ``inner_monologue`` — lets the LLM emit non-dialogue reasoning

All built-ins follow the ToolDef contract and receive run-local storage via
``ToolContext.runtime``. Direct world mutation remains the World Engine's job.
"""

from __future__ import annotations

from typing import Any, TypeVar, cast

from pydantic import BaseModel, Field

from annie.npc.memory.interface import (
    MEMORY_CATEGORY_SEMANTIC,
    MemoryRecord,
)
from annie.npc.response import ActionRequest, MemoryUpdate
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

    Uses ``runtime["recall_seen_ids"]`` (a ``set[str]`` of content strings).
    New records are added to the set so subsequent calls won't return them.
    If the key is absent (e.g. unit tests without agent scaffolding), pass through.
    """
    seen: set[str] | None = extra.get("recall_seen_ids")
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
        records = _dedup_filter(records, ctx.runtime)
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
        records = _dedup_filter(records, ctx.runtime)
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
    description = "Declare a long-term memory update for the world engine to arbitrate."
    input_schema = MemoryStoreInput
    is_read_only = False

    def call(self, input: BaseModel | dict, ctx: ToolContext) -> Any:
        inp = _coerce(input, MemoryStoreInput)
        update = MemoryUpdate(
            content=inp.content,
            type=inp.category,
            metadata=inp.metadata,
        )
        ctx.runtime.setdefault("memory_updates", []).append(update)
        return {"declared": True, "category": inp.category}


class DeclareActionInput(BaseModel):
    type: str = Field(..., description="Verb-style action label, e.g. move, give, attack.")
    payload: dict[str, Any] = Field(default_factory=dict)


class DeclareActionTool(ToolDef):
    name = "declare_action"
    description = "Declare a world action intent for the world engine to arbitrate."
    input_schema = DeclareActionInput
    is_read_only = False

    def call(self, input: BaseModel | dict, ctx: ToolContext) -> Any:
        inp = _coerce(input, DeclareActionInput)
        action = ActionRequest(type=inp.type, payload=inp.payload)
        ctx.runtime.setdefault("actions", []).append(action)
        return {"declared": True, "action": action.model_dump()}


class RequestActionTool(ToolDef):
    name = "request_action"
    description = (
        "Submit one deferred world action and pause this run. Use world_action "
        "instead when you need an immediate observation inside the current "
        "Executor loop."
    )
    input_schema = DeclareActionInput
    is_read_only = False

    def call(self, input: BaseModel | dict, ctx: ToolContext) -> Any:
        inp = _coerce(input, DeclareActionInput)
        action = ActionRequest(type=inp.type, payload=inp.payload)
        ctx.runtime.setdefault("actions", []).append(action)
        ctx.runtime.setdefault("pending_action_ids", []).append(action.action_id)
        return {
            "requested": True,
            "action": action.model_dump(),
            "observation_pending": True,
        }


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
        runtime = ctx.runtime
        skill_runtime = runtime.get("skill_runtime")
        tool_registry = runtime.get("tool_registry")
        messages = runtime.get("messages")
        if skill_runtime is None or tool_registry is None or messages is None:
            return {
                "activated": False,
                "error": "use_skill invoked outside an Executor tool loop",
            }
        try:
            frame_id = skill_runtime.activate(
                inp.skill_name, inp.args, messages, tool_registry,
            )
        except ValueError as e:
            return {"activated": False, "error": str(e)}
        runtime.setdefault("skill_frames", []).append(frame_id)
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
        thoughts = ctx.runtime.setdefault("inner_thoughts", [])
        thoughts.append(inp.thought)
        return {"thought": inp.thought}


def default_builtin_tools() -> list[ToolDef]:
    """Return a fresh list of built-in ToolDef instances."""
    return [
        MemoryRecallTool(),
        MemoryGrepTool(),
        MemoryStoreTool(),
        DeclareActionTool(),
        RequestActionTool(),
        InnerMonologueTool(),
        UseSkillTool(),
    ]

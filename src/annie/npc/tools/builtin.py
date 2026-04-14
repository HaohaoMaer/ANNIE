"""Built-in NPC Agent tools.

Three universal tools every world engine gets for free:

* ``memory_recall`` — MemoryInterface.recall wrapper (category list filter)
* ``memory_store`` — MemoryInterface.remember wrapper
* ``inner_monologue`` — lets the LLM emit non-dialogue reasoning

All built-ins follow the ToolDef contract and reach MemoryInterface via
``ToolContext.agent_context.memory`` (never via ctor injection).
"""

from __future__ import annotations

from typing import Any, TypeVar, cast

from pydantic import BaseModel, Field

from annie.npc.memory.interface import MEMORY_CATEGORY_SEMANTIC
from annie.npc.tools.base_tool import ToolContext, ToolDef

_T = TypeVar("_T", bound=BaseModel)


def _coerce(input_data: BaseModel | dict, model: type[_T]) -> _T:
    if isinstance(input_data, model):
        return input_data
    return model(**cast(dict, input_data))


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


def default_builtin_tools() -> list[ToolDef]:
    """Return a fresh list of built-in ToolDef instances."""
    return [MemoryRecallTool(), MemoryGrepTool(), MemoryStoreTool(), InnerMonologueTool()]

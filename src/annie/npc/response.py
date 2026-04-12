"""AgentResponse — the sole output channel from NPCAgent.run().

Intent-declarative: the agent never mutates world state directly; it reports
dialogue, inner thoughts, action intents, optional memory-update intents,
and a reflection summary. The world engine is the authority that executes,
modifies, or rejects those intents.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ActionRequest(BaseModel):
    """An intent declaration — *not* a direct world mutation."""

    type: str = Field(..., description="Verb-style action label (e.g. 'move', 'give', 'attack').")
    payload: dict[str, Any] = Field(default_factory=dict)


class MemoryUpdate(BaseModel):
    """Optional memory write intent for the world engine to arbitrate.

    If Executor wrote through a memory_store Tool during the run, that write
    is already committed and need not be repeated here.
    """

    content: str
    type: str = "semantic"
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentResponse(BaseModel):
    dialogue: str = ""
    inner_thought: str = ""
    actions: list[ActionRequest] = Field(default_factory=list)
    memory_updates: list[MemoryUpdate] = Field(default_factory=list)
    reflection: str = ""

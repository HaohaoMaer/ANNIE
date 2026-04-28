"""AgentResponse — the sole output channel from NPCAgent.run().

Intent-declarative: the agent never mutates world state directly; it reports
dialogue, inner thoughts, action intents, optional memory-update intents,
and a reflection summary. The world engine is the authority that executes,
modifies, or rejects those intents.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


class ActionRequest(BaseModel):
    """An intent declaration — *not* a direct world mutation."""

    action_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    type: str = Field(..., description="Verb-style action label (e.g. 'move', 'give', 'attack').")
    payload: dict[str, Any] = Field(default_factory=dict)


class ActionResult(BaseModel):
    """Structured result returned by the world engine after attempting an action."""

    action_id: str
    action_type: str
    status: Literal["succeeded", "failed", "partial", "deferred"]
    reason: str | None = None
    observation: str = ""
    facts: dict[str, Any] = Field(default_factory=dict)


class MemoryUpdate(BaseModel):
    """Declarative memory write intent for the world engine to arbitrate."""

    content: str
    type: str = "semantic"
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentResponse(BaseModel):
    dialogue: str = ""
    inner_thought: str = ""
    actions: list[ActionRequest] = Field(default_factory=list)
    memory_updates: list[MemoryUpdate] = Field(default_factory=list)
    reflection: str = ""

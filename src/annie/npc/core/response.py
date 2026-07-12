"""AgentResponse — the sole output channel from NPCAgent.run().

The NPC layer is stateless and does not mutate world state directly. World
side effects happen through world-engine injected tools; their bounded
execution statuses are projected onto AgentResponse for history, feedback, and
tests.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from annie.npc.core.routes import AgentRoute


class ActionRequest(BaseModel):
    """World-engine action payload used inside engine-owned action tools."""

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


class ToolExecutionStatus(BaseModel):
    """Bounded status returned after a world-engine owned tool execution."""

    tool_name: str
    call_id: str | None = None
    status: Literal["success", "failure", "running", "rejected", "invalid"]
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    retry_hint: str | None = None
    world_state_changed: bool = False

    @classmethod
    def from_action_result(
        cls,
        result: ActionResult,
        *,
        tool_name: str,
        call_id: str | None = None,
    ) -> "ToolExecutionStatus":
        status = _action_result_status(result)
        return cls(
            tool_name=tool_name,
            call_id=call_id,
            status=status,
            message=result.observation or result.reason or status,
            payload={
                "action_id": result.action_id,
                "action_type": result.action_type,
                "reason": result.reason,
                "facts": result.facts,
            },
            retry_hint=result.reason if status in {"failure", "rejected", "invalid"} else None,
            world_state_changed=status == "success" and result.reason != "already_at_destination",
        )


class MemoryUpdate(BaseModel):
    """Declarative memory write intent for the world engine to arbitrate."""

    content: str
    type: str = "semantic"
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentResponse(BaseModel):
    route: AgentRoute = AgentRoute.ACTION
    route_id: str = ""
    dialogue: str = ""
    structured_output: str = ""
    inner_thought: str = ""
    tool_statuses: list[ToolExecutionStatus] = Field(default_factory=list)
    memory_updates: list[MemoryUpdate] = Field(default_factory=list)
    reflection: str = ""
    debug: dict[str, Any] = Field(default_factory=dict)


def _action_result_status(
    result: ActionResult,
) -> Literal["success", "failure", "running", "rejected", "invalid"]:
    if result.status == "succeeded":
        return "success"
    if result.status in {"partial", "deferred"}:
        return "running"
    if result.reason and "invalid" in result.reason:
        return "invalid"
    if result.reason in {"unsupported_action", "unreachable", "unknown_current_location"}:
        return "rejected"
    return "failure"

"""AgentContext — the sole input channel from WorldEngine into NPCAgent.

Three-tier layering per design.md D3:
- Core strong-typed fields (mechanical dependencies the Agent code touches)
- Prompt text fields (free-form strings the Agent does not parse)
- Open extension dict (world-engine metadata, passed through to tools)

Constructor will fail fast if required core fields are missing (Pydantic
``Field(...)`` with no default).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from annie.npc.memory.interface import MemoryInterface
    from annie.npc.skills.base_skill import SkillDef
    from annie.npc.tools.base_tool import ToolDef


class AgentContext(BaseModel):
    """Immutable-per-run input envelope handed to NPCAgent.run()."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=False)

    # ---- Core strong-typed fields ---------------------------------------
    npc_id: str = Field(..., description="Unique NPC identity for scoping/logging.")
    input_event: str = Field(..., description="The event triggering this run.")
    tools: list["ToolDef"] = Field(default_factory=list)
    skills: list["SkillDef"] = Field(default_factory=list)
    memory: "MemoryInterface" = Field(..., description="Per-NPC memory implementation.")

    # ---- Prompt text fields --------------------------------------------
    character_prompt: str = ""
    world_rules: str = ""
    situation: str = ""
    history: str = ""

    # ---- Open extension ------------------------------------------------
    extra: dict[str, Any] = Field(default_factory=dict)


def _rebuild() -> None:
    # Resolve forward refs to ToolDef / SkillDef / MemoryInterface.
    from annie.npc.memory.interface import MemoryInterface  # noqa: F401
    from annie.npc.skills.base_skill import SkillDef  # noqa: F401
    from annie.npc.tools.base_tool import ToolContext, ToolDef  # noqa: F401

    AgentContext.model_rebuild()
    ToolContext.model_rebuild(_types_namespace={"AgentContext": AgentContext})


_rebuild()

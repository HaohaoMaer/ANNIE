"""Run-local mutable state for NPC graph execution.

The NPC layer still passes a plain mutable mapping into tools via
``ToolContext.runtime``.  This module centralizes the keys that make up that
mapping so orchestration code does not need to remember the runtime shape.
"""

from __future__ import annotations

from typing import Any

from annie.npc.runtime.skill_runtime import SkillRuntime
from annie.npc.tools.tool_registry import ToolRegistry


def new_run_runtime(
    tool_registry: ToolRegistry,
    *,
    skill_runtime: SkillRuntime | None = None,
) -> dict[str, Any]:
    """Create the per-run runtime mapping shared by tools and graph nodes."""

    runtime: dict[str, Any] = {
        "tool_registry": tool_registry,
        "recall_seen_ids": set(),
        "inner_thoughts": [],
        "memory_updates": [],
        "action_results": [],
        "tool_statuses": [],
        "skill_frames": [],
    }
    if skill_runtime is not None:
        runtime["skill_runtime"] = skill_runtime
    return runtime

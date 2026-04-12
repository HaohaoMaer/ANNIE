"""Main NPC Agent — will be fully rewritten in Phase 3 of decouple refactor.

After Phase 1 deletions this module is intentionally broken; Phase 3 replaces
it with a stateless NPCAgent driven by AgentContext / AgentResponse.
"""

from __future__ import annotations

# Phase 1 deletion boundary: all cognitive / social_graph / YAML-loading logic
# has been removed. The class below is a placeholder; see Phase 3 of
# openspec/changes/decouple-npc-world-engine/tasks.md.


class NPCAgent:  # noqa: D401 - placeholder during refactor
    """Placeholder. Implemented by Phase 3 against AgentContext."""

    def __init__(self, *args, **kwargs) -> None:  # pragma: no cover
        raise NotImplementedError(
            "NPCAgent is being rewritten (decouple-npc-world-engine). "
            "Use the Phase-3 AgentContext-based constructor once available."
        )

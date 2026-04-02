"""Social Agent - Queries relationship data for social context.

Phase 1: Wraps RelationshipMemory (local NPC state).
Phase 2: Delegates to PerceptionBuilder when available.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from annie.npc.memory.relationship import RelationshipMemory

if TYPE_CHECKING:
    from annie.social_graph.perception.perception_builder import PerceptionBuilder


class SocialAgent:
    """Provides social/relationship context to other components."""

    def __init__(
        self,
        relationship_memory: RelationshipMemory,
        perception_builder: PerceptionBuilder | None = None,
        npc_name: str = "",
    ):
        self.relationship_memory = relationship_memory
        self._perception_builder = perception_builder
        self._npc_name = npc_name

    def get_relationship_context(self, target_name: str) -> str:
        """Get relationship info about a specific NPC."""
        rel = self.relationship_memory.get_relationship(target_name)
        if rel:
            return f"Relationship with {rel.target}: {rel.type} (intensity={rel.intensity:.1f})"
        return f"No known relationship with {target_name}."

    def get_all_context(self) -> str:
        """Get summary of all relationships.

        In Phase 2 mode, returns the full social context from the
        Perception Pipeline (relationships + events + unresolved concerns).
        """
        if self._perception_builder is not None:
            return self._perception_builder.build_social_context(self._npc_name)

        rels = self.relationship_memory.get_all_relationships()
        if not rels:
            return "No known relationships."
        lines = [f"- {r.target}: {r.type} (intensity={r.intensity:.1f})" for r in rels]
        return "Relationships:\n" + "\n".join(lines)

    # ------------------------------------------------------------------
    # Phase 2 additions
    # ------------------------------------------------------------------

    def get_knowledge_about(self, event_id: str) -> str | None:
        """What does this NPC know about a specific event?"""
        if self._perception_builder is None:
            return None
        events = self._perception_builder.build_perceived_events(self._npc_name)
        for e in events:
            if e["event_id"] == event_id:
                return f"[{e['belief_status'].upper()}] {e['summary']}"
        return None

    def get_belief_conflicts(self) -> list[dict]:
        """Return unresolved belief conflicts for this NPC."""
        if self._perception_builder is None:
            return []
        events = self._perception_builder.build_perceived_events(self._npc_name)
        return [e for e in events if e["belief_status"] in ("skeptical", "doubted")]

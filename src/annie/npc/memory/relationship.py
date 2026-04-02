"""Relationship Memory - NPC's subjective perception of other characters.

Phase 1 mode: in-memory dict loaded from NPC YAML relationships.
Phase 2 mode: delegates to the Perception Pipeline (PerceptionBuilder)
when a ``perception_builder`` is provided.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from annie.npc.state import RelationshipDef

if TYPE_CHECKING:
    from annie.social_graph.perception.perception_builder import PerceptionBuilder


class RelationshipMemory:
    """Stores and retrieves relationship data for an NPC.

    When ``perception_builder`` is provided (Phase 2), queries are delegated
    to the Perception Pipeline which returns the NPC's subjective view.
    When absent, falls back to the Phase 1 in-memory dict.
    """

    def __init__(
        self,
        npc_name: str,
        initial_relationships: list[RelationshipDef] | None = None,
        perception_builder: PerceptionBuilder | None = None,
    ):
        self._npc_name = npc_name
        self._perception_builder = perception_builder
        self._relationships: dict[str, RelationshipDef] = {}
        for rel in initial_relationships or []:
            self._relationships[rel.target] = rel

    def get_relationship(self, target: str) -> RelationshipDef | None:
        """Get the relationship with a specific NPC, or None if unknown."""
        if self._perception_builder is not None:
            for rel in self._perception_builder.build_perceived_relationships(self._npc_name):
                if rel.target == target:
                    return rel
            return None
        return self._relationships.get(target)

    def get_all_relationships(self) -> list[RelationshipDef]:
        """Get all known relationships."""
        if self._perception_builder is not None:
            return list(self._perception_builder.build_perceived_relationships(self._npc_name))
        return list(self._relationships.values())

    def update_relationship(self, target: str, rel_type: str, intensity: float) -> None:
        """Update or create a relationship entry.

        In Phase 2 mode, this still updates the local cache.  Graph-level
        updates should be done via ``SocialGraph.apply_deltas()``.
        """
        self._relationships[target] = RelationshipDef(
            target=target, type=rel_type, intensity=max(0.0, min(1.0, intensity))
        )

    def describe(self) -> str:
        """Return a human-readable summary of all relationships."""
        rels = self.get_all_relationships()
        if not rels:
            return "No known relationships."
        lines = []
        for rel in rels:
            lines.append(f"{rel.target}: {rel.type} (intensity={rel.intensity:.1f})")
        return "; ".join(lines)

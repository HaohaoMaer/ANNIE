"""Relationship Memory - NPC's subjective perception of other characters.

Phase 1 implementation: in-memory dict loaded from NPC YAML relationships.
Phase 2 will integrate with the Social Graph layer.
"""

from __future__ import annotations

from annie.npc.state import RelationshipDef


class RelationshipMemory:
    """Stores and retrieves relationship data for an NPC.

    In Phase 1 this is a simple in-memory store seeded from the NPC's YAML
    definition. In Phase 2 it will query the Social Graph layer.
    """

    def __init__(self, npc_name: str, initial_relationships: list[RelationshipDef] | None = None):
        self._npc_name = npc_name
        self._relationships: dict[str, RelationshipDef] = {}
        for rel in initial_relationships or []:
            self._relationships[rel.target] = rel

    def get_relationship(self, target: str) -> RelationshipDef | None:
        """Get the relationship with a specific NPC, or None if unknown."""
        return self._relationships.get(target)

    def get_all_relationships(self) -> list[RelationshipDef]:
        """Get all known relationships."""
        return list(self._relationships.values())

    def update_relationship(self, target: str, rel_type: str, intensity: float) -> None:
        """Update or create a relationship entry."""
        self._relationships[target] = RelationshipDef(
            target=target, type=rel_type, intensity=max(0.0, min(1.0, intensity))
        )

    def describe(self) -> str:
        """Return a human-readable summary of all relationships."""
        if not self._relationships:
            return "No known relationships."
        lines = []
        for rel in self._relationships.values():
            lines.append(f"{rel.target}: {rel.type} (intensity={rel.intensity:.1f})")
        return "; ".join(lines)

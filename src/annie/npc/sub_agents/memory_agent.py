"""Memory Agent - Handles memory retrieval and storage on behalf of the NPC.

Aggregates episodic, semantic, and relationship memory into a unified
context string for use by the Planner, Executor, and Reflector.
"""

from __future__ import annotations

from datetime import UTC, datetime

from annie.npc.memory.episodic import EpisodicMemory
from annie.npc.memory.relationship import RelationshipMemory
from annie.npc.memory.semantic import SemanticMemory


class MemoryAgent:
    """Wraps all memory types and provides unified access."""

    def __init__(
        self,
        episodic: EpisodicMemory,
        semantic: SemanticMemory,
        relationship: RelationshipMemory,
    ):
        self.episodic = episodic
        self.semantic = semantic
        self.relationship = relationship

    def build_context(self, query: str, k: int = 5) -> str:
        """Retrieve from all memory types and compose a compressed context string."""
        sections = []

        # Episodic memories
        episodes = self.episodic.retrieve(query, k=k)
        if episodes:
            ep_lines = [f"- {e.content}" for e in episodes]
            sections.append("Recent experiences:\n" + "\n".join(ep_lines))

        # Semantic knowledge
        facts = self.semantic.retrieve(query, k=k)
        if facts:
            fact_lines = [f"- {f.content}" for f in facts]
            sections.append("Known facts:\n" + "\n".join(fact_lines))

        # Relationships
        rels = self.relationship.get_all_relationships()
        if rels:
            rel_lines = [f"- {r.target}: {r.type} (intensity={r.intensity:.1f})" for r in rels]
            sections.append("Relationships:\n" + "\n".join(rel_lines))

        return "\n\n".join(sections) if sections else "No relevant memories."

    def store_episodic(
        self,
        event: str,
        timestamp: datetime | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Store an episodic event. Returns the document ID."""
        return self.episodic.store(
            event, timestamp=timestamp or datetime.now(UTC), metadata=metadata
        )

    def store_semantic(self, fact: str, category: str = "general") -> str:
        """Store a semantic fact. Returns the document ID."""
        return self.semantic.store(fact, category=category)

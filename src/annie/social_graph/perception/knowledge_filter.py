"""Knowledge Filter — Level 1 of the Perception Pipeline.

Pure data filtering: extracts what an NPC knows from the SocialGraph's
knowledge store.  No judgment logic — just "what did this NPC hear?"
"""

from __future__ import annotations

from annie.social_graph.graph import SocialGraph
from annie.social_graph.models import KnowledgeItem, RelationshipEdge


class KnowledgeFilter:
    """Filters the SocialGraph's knowledge store for a single NPC."""

    def __init__(self, graph: SocialGraph) -> None:
        self._graph = graph

    def get_known_events(self, npc_name: str) -> list[KnowledgeItem]:
        """Return all KnowledgeItems for *npc_name*, sorted by learned_at."""
        items = self._graph.get_knowledge(npc_name)
        return sorted(items, key=lambda ki: ki.learned_at)

    def get_known_relationships(self, npc_name: str) -> list[RelationshipEdge]:
        """Return relationship edges that *npc_name* has cognizance of.

        An NPC knows about an edge when:
        - They are the source or target of the edge, OR
        - They know at least one event in the edge's ``shared_history``.
        """
        all_edges = self._graph.get_edges_for(npc_name)
        known: list[RelationshipEdge] = []

        for edge in all_edges:
            # NPC is directly involved — always aware.
            if edge.source == npc_name or edge.target == npc_name:
                known.append(edge)
                continue

            # NPC knows about a shared-history event.
            if any(
                self._graph.npc_knows_event(npc_name, eid)
                for eid in edge.shared_history
            ):
                known.append(edge)

        return known

    def knows_about(self, npc_name: str, event_id: str) -> bool:
        """Check whether *npc_name* has any knowledge of *event_id*."""
        return self._graph.npc_knows_event(npc_name, event_id)

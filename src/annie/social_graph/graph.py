"""Social Graph - Global truth store for NPC relationships.

Nodes = NPCs, Edges = typed relationships with intensity and status.
NPCs never own this data; they query it via the Perception Pipeline.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import networkx as nx

from annie.social_graph.knowledge_manager import KnowledgeManager, SharedKnowledge
from annie.social_graph.models import GraphDelta, KnowledgeItem, RelationshipEdge

_CLAMP_RANGES: dict[str, tuple[float, float]] = {
    "intensity": (0.0, 1.0),
    "trust": (0.0, 1.0),
    "familiarity": (0.0, 1.0),
    "emotional_valence": (-1.0, 1.0),
}


class SocialGraph:
    """God's-eye-view relationship network.

    Stores objective truth about NPC relationships and tracks which NPCs
    know about which events (via KnowledgeItem records).  No subjective
    transformation is performed here — that is the Perception Pipeline's job.
    """

    def __init__(self) -> None:
        self._graph: nx.DiGraph = nx.DiGraph()
        self._knowledge: dict[str, list[KnowledgeItem]] = defaultdict(list)
        self._knowledge_manager: KnowledgeManager = KnowledgeManager()

    # ------------------------------------------------------------------
    # Node management
    # ------------------------------------------------------------------

    def add_npc(self, name: str, metadata: dict | None = None) -> None:
        """Register an NPC node. Idempotent — re-adding merges metadata."""
        self._graph.add_node(name, **(metadata or {}))

    def remove_npc(self, name: str) -> None:
        """Remove an NPC and all its edges."""
        if name in self._graph:
            self._graph.remove_node(name)
        self._knowledge.pop(name, None)

    def get_all_npcs(self) -> list[str]:
        """Return all NPC names, sorted for determinism."""
        return sorted(self._graph.nodes)

    def has_npc(self, name: str) -> bool:
        return name in self._graph

    # ------------------------------------------------------------------
    # Edge management (god's-eye truth)
    # ------------------------------------------------------------------

    def set_edge(self, edge: RelationshipEdge) -> None:
        """Create or overwrite a directed edge.

        Both source and target are auto-registered as nodes if absent.
        """
        if not self._graph.has_node(edge.source):
            self.add_npc(edge.source)
        if not self._graph.has_node(edge.target):
            self.add_npc(edge.target)
        self._graph.add_edge(edge.source, edge.target, edge=edge)

    def get_edge(self, source: str, target: str) -> RelationshipEdge | None:
        """Get the edge from *source* to *target*, or ``None``."""
        data = self._graph.get_edge_data(source, target)
        if data is None:
            return None
        return data["edge"]

    def get_edges_for(self, npc_name: str) -> list[RelationshipEdge]:
        """Return all edges where *npc_name* is source or target."""
        edges: list[RelationshipEdge] = []
        # outgoing
        for _, tgt, data in self._graph.out_edges(npc_name, data=True):
            edges.append(data["edge"])
        # incoming
        for src, _, data in self._graph.in_edges(npc_name, data=True):
            edges.append(data["edge"])
        return edges

    def get_outgoing_edges(self, npc_name: str) -> list[RelationshipEdge]:
        """Return edges where *npc_name* is the source."""
        if npc_name not in self._graph:
            return []
        return [data["edge"] for _, _, data in self._graph.out_edges(npc_name, data=True)]

    # ------------------------------------------------------------------
    # Graph deltas
    # ------------------------------------------------------------------

    def apply_deltas(self, deltas: list[GraphDelta]) -> None:
        """Apply a batch of numeric changes, clamping values to valid ranges."""
        for d in deltas:
            edge = self.get_edge(d.source, d.target)
            if edge is None:
                # Create a default edge so the delta has something to modify.
                edge = RelationshipEdge(source=d.source, target=d.target)
                self.set_edge(edge)

            if d.field not in _CLAMP_RANGES:
                continue  # skip unknown fields silently

            old_val = getattr(edge, d.field)
            lo, hi = _CLAMP_RANGES[d.field]
            new_val = max(lo, min(hi, old_val + d.delta))
            # Pydantic models are mutable by default; update in-place.
            setattr(edge, d.field, new_val)

    # ------------------------------------------------------------------
    # Knowledge tracking
    # ------------------------------------------------------------------

    def record_knowledge(self, item: KnowledgeItem) -> None:
        """Store a KnowledgeItem for the given knower."""
        self._knowledge[item.knower].append(item)

    def get_knowledge(
        self, npc_name: str, event_id: str | None = None
    ) -> list[KnowledgeItem]:
        """Get knowledge items for an NPC, optionally filtered by event."""
        items = self._knowledge.get(npc_name, [])
        if event_id is not None:
            items = [i for i in items if i.event_id == event_id]
        return items

    def npc_knows_event(self, npc_name: str, event_id: str) -> bool:
        """Check whether *npc_name* has any knowledge of *event_id*."""
        return any(i.event_id == event_id for i in self._knowledge.get(npc_name, []))

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize the graph to a plain dict (for persistence / debugging)."""
        nodes = self.get_all_npcs()
        edges = []
        for src, tgt, data in self._graph.edges(data=True):
            edges.append(data["edge"].model_dump())
        knowledge = {
            npc: [ki.model_dump() for ki in items]
            for npc, items in self._knowledge.items()
        }
        return {"nodes": nodes, "edges": edges, "knowledge": knowledge}

    @classmethod
    def from_dict(cls, data: dict) -> SocialGraph:
        """Restore a SocialGraph from a dict produced by ``to_dict``."""
        g = cls()
        for name in data.get("nodes", []):
            g.add_npc(name)
        for edge_data in data.get("edges", []):
            g.set_edge(RelationshipEdge(**edge_data))
        for npc, items in data.get("knowledge", {}).items():
            for ki_data in items:
                g.record_knowledge(KnowledgeItem(**ki_data))
        return g

    def add_shared_knowledge(self, knowledge: SharedKnowledge) -> None:
        """Add shared knowledge to the graph.

        Args:
            knowledge: The shared knowledge to add.
        """
        self._knowledge_manager.add_shared_knowledge(knowledge)

    def get_shared_knowledge(self, npc_name: str | None = None) -> list[SharedKnowledge]:
        """Get shared knowledge visible to an NPC.

        Args:
            npc_name: Name of the NPC (None = all public knowledge).

        Returns:
            List of visible shared knowledge.
        """
        return self._knowledge_manager.get_shared_knowledge(npc_name)

    def grant_shared_knowledge(self, npc_name: str, knowledge_id: str) -> bool:
        """Grant shared knowledge to an NPC.

        Args:
            npc_name: Name of the NPC.
            knowledge_id: ID of the knowledge.

        Returns:
            True if granted, False if not found.
        """
        return self._knowledge_manager.grant_knowledge(npc_name, knowledge_id)

    def get_knowledge_manager(self) -> KnowledgeManager:
        """Get the knowledge manager instance.

        Returns:
            The knowledge manager.
        """
        return self._knowledge_manager

"""Tests for SocialGraph."""

from datetime import UTC, datetime

import pytest

from annie.social_graph.graph import SocialGraph
from annie.social_graph.models import GraphDelta, KnowledgeItem, RelationshipEdge


@pytest.fixture
def graph() -> SocialGraph:
    g = SocialGraph()
    g.add_npc("Elder")
    g.add_npc("Gareth")
    g.add_npc("Lina")
    return g


@pytest.fixture
def seeded_graph(graph: SocialGraph) -> SocialGraph:
    """Graph with initial edges."""
    graph.set_edge(RelationshipEdge(
        source="Elder", target="Gareth", type="trusted_ally",
        intensity=0.8, trust=0.7, familiarity=0.9, emotional_valence=0.4,
    ))
    graph.set_edge(RelationshipEdge(
        source="Elder", target="Lina", type="trade_partner",
        intensity=0.6, trust=0.5, familiarity=0.6,
    ))
    graph.set_edge(RelationshipEdge(
        source="Gareth", target="Lina", type="acquaintance",
        intensity=0.3, trust=0.2, familiarity=0.4, emotional_valence=-0.1,
    ))
    return graph


# ------------------------------------------------------------------
# Node management
# ------------------------------------------------------------------


class TestNodes:
    def test_add_and_list(self, graph):
        assert graph.get_all_npcs() == ["Elder", "Gareth", "Lina"]

    def test_has_npc(self, graph):
        assert graph.has_npc("Elder")
        assert not graph.has_npc("Nobody")

    def test_add_idempotent(self, graph):
        graph.add_npc("Elder", {"role": "leader"})
        assert graph.has_npc("Elder")
        assert len(graph.get_all_npcs()) == 3

    def test_remove_npc(self, seeded_graph):
        seeded_graph.remove_npc("Lina")
        assert not seeded_graph.has_npc("Lina")
        assert seeded_graph.get_edge("Elder", "Lina") is None

    def test_remove_nonexistent(self, graph):
        graph.remove_npc("Nobody")  # should not raise


# ------------------------------------------------------------------
# Edge management
# ------------------------------------------------------------------


class TestEdges:
    def test_set_and_get(self, seeded_graph):
        edge = seeded_graph.get_edge("Elder", "Gareth")
        assert edge is not None
        assert edge.type == "trusted_ally"
        assert edge.trust == 0.7

    def test_get_nonexistent(self, graph):
        assert graph.get_edge("Elder", "Gareth") is None

    def test_auto_register_nodes(self):
        g = SocialGraph()
        g.set_edge(RelationshipEdge(source="A", target="B"))
        assert g.has_npc("A")
        assert g.has_npc("B")

    def test_get_edges_for(self, seeded_graph):
        edges = seeded_graph.get_edges_for("Elder")
        # Elder->Gareth, Elder->Lina (outgoing) + none incoming in this fixture
        assert len(edges) == 2

    def test_get_edges_for_includes_incoming(self, seeded_graph):
        edges = seeded_graph.get_edges_for("Lina")
        # incoming: Elder->Lina, Gareth->Lina
        assert len(edges) == 2

    def test_get_outgoing_edges(self, seeded_graph):
        out = seeded_graph.get_outgoing_edges("Elder")
        assert len(out) == 2
        targets = {e.target for e in out}
        assert targets == {"Gareth", "Lina"}

    def test_get_outgoing_nonexistent(self, graph):
        assert graph.get_outgoing_edges("Nobody") == []

    def test_overwrite_edge(self, seeded_graph):
        seeded_graph.set_edge(RelationshipEdge(
            source="Elder", target="Gareth", type="enemy", intensity=0.1,
        ))
        edge = seeded_graph.get_edge("Elder", "Gareth")
        assert edge.type == "enemy"
        assert edge.intensity == 0.1


# ------------------------------------------------------------------
# Deltas
# ------------------------------------------------------------------


class TestDeltas:
    def test_apply_single_delta(self, seeded_graph):
        seeded_graph.apply_deltas([
            GraphDelta(source="Elder", target="Gareth", field="trust", delta=0.2),
        ])
        edge = seeded_graph.get_edge("Elder", "Gareth")
        assert edge.trust == pytest.approx(0.9)

    def test_clamp_upper(self, seeded_graph):
        seeded_graph.apply_deltas([
            GraphDelta(source="Elder", target="Gareth", field="trust", delta=0.5),
        ])
        edge = seeded_graph.get_edge("Elder", "Gareth")
        assert edge.trust == 1.0

    def test_clamp_lower(self, seeded_graph):
        seeded_graph.apply_deltas([
            GraphDelta(source="Gareth", target="Lina", field="trust", delta=-0.5),
        ])
        edge = seeded_graph.get_edge("Gareth", "Lina")
        assert edge.trust == 0.0

    def test_clamp_valence(self, seeded_graph):
        seeded_graph.apply_deltas([
            GraphDelta(source="Gareth", target="Lina", field="emotional_valence", delta=-1.5),
        ])
        edge = seeded_graph.get_edge("Gareth", "Lina")
        assert edge.emotional_valence == -1.0

    def test_delta_creates_edge_if_missing(self, graph):
        graph.apply_deltas([
            GraphDelta(source="Elder", target="Gareth", field="trust", delta=0.3),
        ])
        edge = graph.get_edge("Elder", "Gareth")
        assert edge is not None
        assert edge.trust == pytest.approx(0.8)  # default 0.5 + 0.3

    def test_unknown_field_ignored(self, seeded_graph):
        seeded_graph.apply_deltas([
            GraphDelta(source="Elder", target="Gareth", field="nonexistent", delta=0.1),
        ])
        # should not raise

    def test_multiple_deltas(self, seeded_graph):
        seeded_graph.apply_deltas([
            GraphDelta(source="Elder", target="Gareth", field="trust", delta=0.1),
            GraphDelta(source="Elder", target="Gareth", field="emotional_valence", delta=-0.2),
        ])
        edge = seeded_graph.get_edge("Elder", "Gareth")
        assert edge.trust == pytest.approx(0.8)
        assert edge.emotional_valence == pytest.approx(0.2)


# ------------------------------------------------------------------
# Knowledge tracking
# ------------------------------------------------------------------


class TestKnowledge:
    def test_record_and_get(self, graph):
        ki = KnowledgeItem(event_id="e1", knower="Elder", summary="saw it")
        graph.record_knowledge(ki)
        items = graph.get_knowledge("Elder")
        assert len(items) == 1
        assert items[0].event_id == "e1"

    def test_filter_by_event(self, graph):
        graph.record_knowledge(KnowledgeItem(event_id="e1", knower="Elder", summary="a"))
        graph.record_knowledge(KnowledgeItem(event_id="e2", knower="Elder", summary="b"))
        items = graph.get_knowledge("Elder", event_id="e1")
        assert len(items) == 1
        assert items[0].summary == "a"

    def test_npc_knows_event(self, graph):
        graph.record_knowledge(KnowledgeItem(event_id="e1", knower="Elder", summary="x"))
        assert graph.npc_knows_event("Elder", "e1")
        assert not graph.npc_knows_event("Elder", "e2")
        assert not graph.npc_knows_event("Gareth", "e1")

    def test_empty_knowledge(self, graph):
        assert graph.get_knowledge("Elder") == []
        assert not graph.npc_knows_event("Elder", "e1")


# ------------------------------------------------------------------
# Serialization
# ------------------------------------------------------------------


class TestSerialization:
    def test_roundtrip(self, seeded_graph):
        ki = KnowledgeItem(event_id="e1", knower="Elder", summary="test")
        seeded_graph.record_knowledge(ki)

        data = seeded_graph.to_dict()
        restored = SocialGraph.from_dict(data)

        assert restored.get_all_npcs() == seeded_graph.get_all_npcs()
        edge = restored.get_edge("Elder", "Gareth")
        assert edge is not None
        assert edge.type == "trusted_ally"
        assert restored.npc_knows_event("Elder", "e1")

    def test_empty_graph_roundtrip(self):
        g = SocialGraph()
        data = g.to_dict()
        restored = SocialGraph.from_dict(data)
        assert restored.get_all_npcs() == []

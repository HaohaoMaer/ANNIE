"""Tests for KnowledgeFilter (Perception Pipeline Level 1)."""

import pytest

from annie.social_graph.graph import SocialGraph
from annie.social_graph.models import KnowledgeItem, RelationshipEdge
from annie.social_graph.perception.knowledge_filter import KnowledgeFilter


@pytest.fixture
def graph() -> SocialGraph:
    g = SocialGraph()
    g.set_edge(RelationshipEdge(
        source="Elder", target="Gareth", type="trusted_ally",
        shared_history=["e1"],
    ))
    g.set_edge(RelationshipEdge(
        source="Elder", target="Lina", type="trade_partner",
    ))
    g.set_edge(RelationshipEdge(
        source="Gareth", target="Lina", type="acquaintance",
        shared_history=["e2"],
    ))
    # Record knowledge
    g.record_knowledge(KnowledgeItem(event_id="e1", knower="Elder", summary="saw e1"))
    g.record_knowledge(KnowledgeItem(event_id="e1", knower="Gareth", summary="saw e1"))
    g.record_knowledge(KnowledgeItem(event_id="e2", knower="Lina", summary="heard e2", source_npc="Gareth"))
    return g


@pytest.fixture
def kf(graph) -> KnowledgeFilter:
    return KnowledgeFilter(graph)


class TestGetKnownEvents:
    def test_elder_events(self, kf):
        items = kf.get_known_events("Elder")
        assert len(items) == 1
        assert items[0].event_id == "e1"

    def test_lina_events(self, kf):
        items = kf.get_known_events("Lina")
        assert len(items) == 1
        assert items[0].event_id == "e2"

    def test_unknown_npc(self, kf):
        assert kf.get_known_events("Nobody") == []

    def test_sorted_by_time(self, graph):
        from datetime import UTC, datetime, timedelta
        t1 = datetime(2025, 1, 1, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, tzinfo=UTC)
        graph.record_knowledge(KnowledgeItem(event_id="late", knower="Elder", summary="late", learned_at=t2))
        graph.record_knowledge(KnowledgeItem(event_id="early", knower="Elder", summary="early", learned_at=t1))
        kf = KnowledgeFilter(graph)
        items = kf.get_known_events("Elder")
        # e1 (default time) may vary, but early < late
        event_ids = [i.event_id for i in items]
        assert event_ids.index("early") < event_ids.index("late")


class TestGetKnownRelationships:
    def test_elder_knows_direct_edges(self, kf):
        rels = kf.get_known_relationships("Elder")
        targets = {
            (e.source, e.target) for e in rels
        }
        # Elder is source/target of Elder->Gareth and Elder->Lina
        assert ("Elder", "Gareth") in targets
        assert ("Elder", "Lina") in targets

    def test_lina_knows_gareth_edge_via_shared_history(self, kf, graph):
        """Lina knows event e2 which is in Gareth->Lina shared_history."""
        rels = kf.get_known_relationships("Lina")
        pairs = {(e.source, e.target) for e in rels}
        assert ("Gareth", "Lina") in pairs
        assert ("Elder", "Lina") in pairs

    def test_npc_without_edges(self, graph):
        graph.add_npc("Hermit")
        kf = KnowledgeFilter(graph)
        assert kf.get_known_relationships("Hermit") == []


class TestKnowsAbout:
    def test_elder_knows_e1(self, kf):
        assert kf.knows_about("Elder", "e1")

    def test_elder_doesnt_know_e2(self, kf):
        assert not kf.knows_about("Elder", "e2")

    def test_lina_knows_e2(self, kf):
        assert kf.knows_about("Lina", "e2")

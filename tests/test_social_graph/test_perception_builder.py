"""Tests for PerceptionBuilder (Perception Pipeline Level 3)."""

import pytest

from annie.social_graph.graph import SocialGraph
from annie.social_graph.models import (
    BeliefStatus,
    KnowledgeItem,
    RelationshipEdge,
)
from annie.social_graph.perception.belief_evaluator import BeliefEvaluator
from annie.social_graph.perception.knowledge_filter import KnowledgeFilter
from annie.social_graph.perception.perception_builder import PerceptionBuilder


@pytest.fixture
def graph() -> SocialGraph:
    g = SocialGraph()
    g.set_edge(RelationshipEdge(
        source="Elder", target="Gareth", type="trusted_ally",
        intensity=0.8, trust=0.7, familiarity=0.9, emotional_valence=0.4,
    ))
    g.set_edge(RelationshipEdge(
        source="Elder", target="Lina", type="trade_partner",
        intensity=0.6, trust=0.5, familiarity=0.6, emotional_valence=0.1,
    ))
    # Knowledge
    g.record_knowledge(KnowledgeItem(
        event_id="e1", knower="Elder", summary="Gareth accused the carpenter",
        source_npc=None,
    ))
    g.record_knowledge(KnowledgeItem(
        event_id="e2", knower="Elder",
        summary="Reportedly, trade goods were tampered with",
        source_npc="Lina", distortion=0.15,
    ))
    return g


@pytest.fixture
def builder(graph) -> PerceptionBuilder:
    kf = KnowledgeFilter(graph)
    be = BeliefEvaluator(graph)
    return PerceptionBuilder(kf, be)


class TestPerceivedRelationships:
    def test_elder_sees_two_relationships(self, builder):
        rels = builder.build_perceived_relationships("Elder")
        targets = {r.target for r in rels}
        assert targets == {"Gareth", "Lina"}

    def test_enriched_fields(self, builder):
        rels = builder.build_perceived_relationships("Elder")
        gareth_rel = next(r for r in rels if r.target == "Gareth")
        assert gareth_rel.trust == 0.7
        assert gareth_rel.emotional_valence == 0.4
        assert gareth_rel.status == "active"

    def test_npc_with_no_relationships(self, graph):
        graph.add_npc("Hermit")
        kf = KnowledgeFilter(graph)
        be = BeliefEvaluator(graph)
        builder = PerceptionBuilder(kf, be)
        assert builder.build_perceived_relationships("Hermit") == []


class TestPerceivedEvents:
    def test_elder_sees_two_events(self, builder):
        events = builder.build_perceived_events("Elder")
        assert len(events) == 2

    def test_first_hand_accepted(self, builder):
        events = builder.build_perceived_events("Elder")
        e1 = next(e for e in events if e["event_id"] == "e1")
        assert e1["belief_status"] == "accepted"
        assert e1["source"] is None

    def test_second_hand_evaluated(self, builder):
        events = builder.build_perceived_events("Elder")
        e2 = next(e for e in events if e["event_id"] == "e2")
        # Lina: trust=0.5 → credibility=0.5 → SKEPTICAL
        assert e2["belief_status"] == "skeptical"
        assert e2["source"] == "Lina"

    def test_rejected_events_excluded(self, graph):
        """Events from enemies are REJECTED and should be excluded."""
        graph.set_edge(RelationshipEdge(
            source="Elder", target="Spy", type="enemy", trust=0.1,
        ))
        graph.record_knowledge(KnowledgeItem(
            event_id="e_spy", knower="Elder", summary="Spy lied",
            source_npc="Spy",
        ))
        kf = KnowledgeFilter(graph)
        be = BeliefEvaluator(graph)
        builder = PerceptionBuilder(kf, be)
        events = builder.build_perceived_events("Elder")
        event_ids = {e["event_id"] for e in events}
        assert "e_spy" not in event_ids


class TestSocialContext:
    def test_contains_relationships(self, builder):
        ctx = builder.build_social_context("Elder")
        assert "Relationships (my perception):" in ctx
        assert "Gareth" in ctx
        assert "trusted_ally" in ctx

    def test_contains_events(self, builder):
        ctx = builder.build_social_context("Elder")
        assert "Events I know about:" in ctx
        assert "[ACCEPTED]" in ctx

    def test_contains_unresolved(self, builder):
        ctx = builder.build_social_context("Elder")
        assert "Unresolved concerns:" in ctx
        # e2 is SKEPTICAL → should appear in unresolved
        assert "tampered" in ctx

    def test_empty_npc(self, graph):
        graph.add_npc("Hermit")
        kf = KnowledgeFilter(graph)
        be = BeliefEvaluator(graph)
        builder = PerceptionBuilder(kf, be)
        ctx = builder.build_social_context("Hermit")
        assert ctx == "No social knowledge available."

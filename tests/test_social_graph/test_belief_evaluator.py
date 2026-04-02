"""Tests for BeliefEvaluator (Perception Pipeline Level 2)."""

import pytest

from annie.social_graph.graph import SocialGraph
from annie.social_graph.models import BeliefStatus, KnowledgeItem, RelationshipEdge
from annie.social_graph.perception.belief_evaluator import BeliefEvaluator


@pytest.fixture
def graph() -> SocialGraph:
    g = SocialGraph()
    g.set_edge(RelationshipEdge(source="Elder", target="Gareth", type="trusted_ally", trust=0.8))
    g.set_edge(RelationshipEdge(source="Elder", target="Lina", type="trade_partner", trust=0.5))
    g.set_edge(RelationshipEdge(source="Elder", target="Spy", type="enemy", trust=0.1))
    g.set_edge(RelationshipEdge(source="Elder", target="Stranger", type="acquaintance", trust=0.2))
    return g


@pytest.fixture
def evaluator(graph) -> BeliefEvaluator:
    return BeliefEvaluator(graph)


class TestFirstHand:
    def test_always_accepted(self, evaluator):
        items = [KnowledgeItem(event_id="e1", knower="Elder", summary="I saw it", source_npc=None)]
        result = evaluator.evaluate("Elder", items)
        assert result[0].belief_status == BeliefStatus.ACCEPTED
        assert result[0].credibility == 1.0


class TestSourceTrust:
    def test_high_trust_source(self, evaluator):
        """Gareth: trust=0.8 → credibility=0.8 → ACCEPTED."""
        items = [KnowledgeItem(event_id="e1", knower="Elder", summary="Gareth said so", source_npc="Gareth")]
        result = evaluator.evaluate("Elder", items)
        assert result[0].credibility == pytest.approx(0.8)
        assert result[0].belief_status == BeliefStatus.ACCEPTED

    def test_medium_trust_source(self, evaluator):
        """Lina: trust=0.5 → credibility=0.5 → SKEPTICAL."""
        items = [KnowledgeItem(event_id="e1", knower="Elder", summary="Lina mentioned it", source_npc="Lina")]
        result = evaluator.evaluate("Elder", items)
        assert result[0].credibility == pytest.approx(0.5)
        assert result[0].belief_status == BeliefStatus.SKEPTICAL

    def test_low_trust_source(self, evaluator):
        """Stranger: trust=0.2 → credibility=0.2 → DOUBTED."""
        items = [KnowledgeItem(event_id="e1", knower="Elder", summary="Stranger claimed", source_npc="Stranger")]
        result = evaluator.evaluate("Elder", items)
        assert result[0].credibility == pytest.approx(0.2)
        assert result[0].belief_status == BeliefStatus.DOUBTED

    def test_enemy_source(self, evaluator):
        """Spy: enemy → credibility=0.1 → REJECTED."""
        items = [KnowledgeItem(event_id="e1", knower="Elder", summary="Spy said", source_npc="Spy")]
        result = evaluator.evaluate("Elder", items)
        assert result[0].credibility == pytest.approx(0.1)
        assert result[0].belief_status == BeliefStatus.REJECTED

    def test_unknown_source(self, evaluator):
        """No edge exists → low trust credibility."""
        items = [KnowledgeItem(event_id="e1", knower="Elder", summary="Unknown said", source_npc="Unknown")]
        result = evaluator.evaluate("Elder", items)
        assert result[0].credibility == pytest.approx(0.2)


class TestConflictDetection:
    def test_conflicting_items(self, evaluator):
        """Positive then negative about same person → conflict."""
        items = [
            KnowledgeItem(event_id="e1", knower="Elder", summary="Gareth praised the carpenter", source_npc=None),
            KnowledgeItem(event_id="e2", knower="Elder", summary="Gareth accused the carpenter of theft", source_npc="Lina"),
        ]
        result = evaluator.evaluate("Elder", items)
        # First item: first-hand → ACCEPTED.
        assert result[0].belief_status == BeliefStatus.ACCEPTED
        # Second item: conflicts with first → capped at 0.4 → SKEPTICAL.
        assert result[1].credibility <= 0.4
        assert result[1].belief_status == BeliefStatus.SKEPTICAL
        assert "e1" in result[1].conflicting_with

    def test_no_conflict_different_subjects(self, evaluator):
        """Positive and negative about different people → no conflict."""
        items = [
            KnowledgeItem(event_id="e1", knower="Elder", summary="Gareth praised the village", source_npc=None),
            KnowledgeItem(event_id="e2", knower="Elder", summary="Lina accused the merchant", source_npc="Gareth"),
        ]
        result = evaluator.evaluate("Elder", items)
        assert result[1].conflicting_with == []

    def test_no_conflict_same_polarity(self, evaluator):
        """Both negative about same person → not a conflict."""
        items = [
            KnowledgeItem(event_id="e1", knower="Elder", summary="Gareth accused the carpenter", source_npc=None),
            KnowledgeItem(event_id="e2", knower="Elder", summary="Gareth attacked the carpenter", source_npc="Lina"),
        ]
        result = evaluator.evaluate("Elder", items)
        assert result[1].conflicting_with == []


class TestGetConflicts:
    def test_returns_conflict_pairs(self, evaluator):
        items = [
            KnowledgeItem(event_id="e1", knower="Elder", summary="Gareth helped the carpenter", source_npc=None),
            KnowledgeItem(event_id="e2", knower="Elder", summary="Gareth betrayed the carpenter", source_npc="Lina"),
        ]
        pairs = evaluator.get_conflicts("Elder", items)
        assert len(pairs) == 1
        assert pairs[0][0].event_id == "e2"
        assert pairs[0][1].event_id == "e1"


class TestDoesNotMutateInput:
    def test_originals_unchanged(self, evaluator):
        original = KnowledgeItem(
            event_id="e1", knower="Elder", summary="test",
            source_npc="Lina", credibility=1.0, belief_status=BeliefStatus.ACCEPTED,
        )
        evaluator.evaluate("Elder", [original])
        # Original should not be changed.
        assert original.credibility == 1.0
        assert original.belief_status == BeliefStatus.ACCEPTED

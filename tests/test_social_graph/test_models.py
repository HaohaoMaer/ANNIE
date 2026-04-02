"""Tests for social_graph data models."""

from datetime import UTC, datetime

import pytest

from annie.social_graph.models import (
    BeliefStatus,
    EventVisibility,
    GraphDelta,
    KnowledgeItem,
    RelationshipEdge,
    SocialEvent,
)


# ---------------------------------------------------------------------------
# RelationshipEdge
# ---------------------------------------------------------------------------


class TestRelationshipEdge:
    def test_defaults(self):
        edge = RelationshipEdge(source="A", target="B")
        assert edge.type == "acquaintance"
        assert edge.intensity == 0.5
        assert edge.trust == 0.5
        assert edge.familiarity == 0.0
        assert edge.emotional_valence == 0.0
        assert edge.status == "active"
        assert edge.shared_history == []
        assert edge.last_interaction is None

    def test_full_construction(self):
        ts = datetime.now(UTC)
        edge = RelationshipEdge(
            source="Elder",
            target="Gareth",
            type="trusted_ally",
            intensity=0.8,
            trust=0.7,
            familiarity=0.9,
            emotional_valence=0.4,
            status="active",
            shared_history=["evt_001"],
            last_interaction=ts,
        )
        assert edge.source == "Elder"
        assert edge.target == "Gareth"
        assert edge.shared_history == ["evt_001"]
        assert edge.last_interaction == ts

    def test_serialization_roundtrip(self):
        edge = RelationshipEdge(source="A", target="B", type="friend", intensity=0.9)
        data = edge.model_dump()
        restored = RelationshipEdge(**data)
        assert restored == edge


# ---------------------------------------------------------------------------
# GraphDelta
# ---------------------------------------------------------------------------


class TestGraphDelta:
    def test_construction(self):
        d = GraphDelta(source="A", target="B", field="trust", delta=0.1, reason="helped")
        assert d.field == "trust"
        assert d.delta == 0.1

    def test_negative_delta(self):
        d = GraphDelta(source="A", target="B", field="emotional_valence", delta=-0.3)
        assert d.delta == -0.3
        assert d.reason == ""


# ---------------------------------------------------------------------------
# EventVisibility
# ---------------------------------------------------------------------------


class TestEventVisibility:
    def test_values(self):
        assert EventVisibility.PUBLIC == "public"
        assert EventVisibility.WITNESSED == "witnessed"
        assert EventVisibility.PRIVATE == "private"
        assert EventVisibility.SECRET == "secret"

    def test_string_comparison(self):
        assert EventVisibility.PUBLIC == "public"


# ---------------------------------------------------------------------------
# SocialEvent
# ---------------------------------------------------------------------------


class TestSocialEvent:
    def test_defaults(self):
        evt = SocialEvent(actor="A", action="greeted", description="A greeted B")
        assert evt.id  # auto-generated
        assert evt.timestamp is not None
        assert evt.target is None
        assert evt.visibility == EventVisibility.WITNESSED
        assert evt.graph_deltas == []

    def test_full_event(self):
        delta = GraphDelta(source="A", target="B", field="trust", delta=0.1)
        evt = SocialEvent(
            actor="A",
            target="B",
            action="traded",
            description="A traded with B",
            location="market",
            witnesses=["C"],
            tags=["trade"],
            visibility=EventVisibility.PUBLIC,
            graph_deltas=[delta],
        )
        assert evt.witnesses == ["C"]
        assert evt.graph_deltas[0].field == "trust"
        assert evt.visibility == EventVisibility.PUBLIC

    def test_unique_ids(self):
        e1 = SocialEvent(actor="A", action="x", description="x")
        e2 = SocialEvent(actor="A", action="x", description="x")
        assert e1.id != e2.id


# ---------------------------------------------------------------------------
# BeliefStatus
# ---------------------------------------------------------------------------


class TestBeliefStatus:
    def test_values(self):
        assert BeliefStatus.ACCEPTED == "accepted"
        assert BeliefStatus.SKEPTICAL == "skeptical"
        assert BeliefStatus.DOUBTED == "doubted"
        assert BeliefStatus.REJECTED == "rejected"


# ---------------------------------------------------------------------------
# KnowledgeItem
# ---------------------------------------------------------------------------


class TestKnowledgeItem:
    def test_first_hand_defaults(self):
        ki = KnowledgeItem(event_id="e1", knower="Elder", summary="I saw it happen")
        assert ki.source_npc is None
        assert ki.distortion == 0.0
        assert ki.belief_status == BeliefStatus.ACCEPTED
        assert ki.credibility == 1.0
        assert ki.conflicting_with == []

    def test_second_hand(self):
        ki = KnowledgeItem(
            event_id="e1",
            knower="Lina",
            source_npc="Gareth",
            distortion=0.15,
            summary="Reportedly, Gareth accused the carpenter",
            belief_status=BeliefStatus.SKEPTICAL,
            credibility=0.5,
        )
        assert ki.source_npc == "Gareth"
        assert ki.distortion == 0.15
        assert ki.belief_status == BeliefStatus.SKEPTICAL

    def test_with_conflicts(self):
        ki = KnowledgeItem(
            event_id="e2",
            knower="Elder",
            summary="Trade goods tampered",
            conflicting_with=["e1"],
        )
        assert ki.conflicting_with == ["e1"]

    def test_serialization_roundtrip(self):
        ki = KnowledgeItem(
            event_id="e1",
            knower="A",
            summary="something happened",
            belief_status=BeliefStatus.DOUBTED,
            credibility=0.3,
        )
        data = ki.model_dump()
        restored = KnowledgeItem(**data)
        assert restored == ki

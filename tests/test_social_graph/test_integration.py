"""Integration tests — end-to-end 3-NPC scenario with information asymmetry."""

from datetime import UTC, datetime, timedelta

import pytest

from annie.social_graph.event_log import SocialEventLog
from annie.social_graph.graph import SocialGraph
from annie.social_graph.models import (
    BeliefStatus,
    EventVisibility,
    KnowledgeItem,
    RelationshipEdge,
    SocialEvent,
)
from annie.social_graph.perception.belief_evaluator import BeliefEvaluator
from annie.social_graph.perception.knowledge_filter import KnowledgeFilter
from annie.social_graph.perception.perception_builder import PerceptionBuilder
from annie.social_graph.propagation import PropagationEngine

ALL_NPCS = ["Village Elder", "Blacksmith Gareth", "Merchant Lina"]


@pytest.fixture
def setup():
    """Full scenario setup: graph + events + propagation."""
    graph = SocialGraph()
    event_log = SocialEventLog()
    engine = PropagationEngine(graph, event_log)

    # --- Initial relationship edges ---
    graph.set_edge(RelationshipEdge(
        source="Village Elder", target="Blacksmith Gareth",
        type="trusted_ally", intensity=0.8, trust=0.7, familiarity=0.9, emotional_valence=0.4,
    ))
    graph.set_edge(RelationshipEdge(
        source="Village Elder", target="Merchant Lina",
        type="trade_partner", intensity=0.6, trust=0.5, familiarity=0.6, emotional_valence=0.2,
    ))
    graph.set_edge(RelationshipEdge(
        source="Blacksmith Gareth", target="Village Elder",
        type="trusted_ally", intensity=0.7, trust=0.8, familiarity=0.9, emotional_valence=0.5,
    ))
    graph.set_edge(RelationshipEdge(
        source="Blacksmith Gareth", target="Merchant Lina",
        type="acquaintance", intensity=0.3, trust=0.2, familiarity=0.4, emotional_valence=-0.1,
    ))
    graph.set_edge(RelationshipEdge(
        source="Merchant Lina", target="Village Elder",
        type="trade_partner", intensity=0.5, trust=0.4, familiarity=0.6, emotional_valence=0.1,
    ))
    graph.set_edge(RelationshipEdge(
        source="Merchant Lina", target="Blacksmith Gareth",
        type="acquaintance", intensity=0.3, trust=0.3, familiarity=0.4, emotional_valence=0.0,
    ))

    # --- Preset events ---
    now = datetime.now(UTC)

    event1 = SocialEvent(
        id="preset_1",
        actor="Blacksmith Gareth", target="Carpenter",
        action="accused",
        description="Blacksmith Gareth publicly accused the carpenter of stealing his customers",
        witnesses=["Village Elder"],
        visibility=EventVisibility.WITNESSED,
        timestamp=now - timedelta(days=7),
    )

    event2 = SocialEvent(
        id="preset_2",
        actor="Merchant Lina",
        action="discovered",
        description="Merchant Lina discovered that trade goods on the eastern route have been tampered with",
        visibility=EventVisibility.PRIVATE,
        timestamp=now - timedelta(days=3),
    )

    event_log.load_preset_events([event1, event2])

    # Propagate preset events.
    engine.propagate_event(event1, ALL_NPCS)
    engine.propagate_event(event2, ALL_NPCS)

    return graph, event_log, engine


class TestInitialInformationAsymmetry:
    """After preset events + propagation, verify who knows what."""

    def test_elder_knows_accusation(self, setup):
        graph, _, _ = setup
        assert graph.npc_knows_event("Village Elder", "preset_1")

    def test_gareth_knows_accusation(self, setup):
        graph, _, _ = setup
        assert graph.npc_knows_event("Blacksmith Gareth", "preset_1")

    def test_lina_may_know_accusation_via_propagation(self, setup):
        graph, _, _ = setup
        # Elder->Lina: trust=0.5, willingness(trade_partner)=0.5 → prob=0.25 > 0.15
        # So Lina should learn about it.
        assert graph.npc_knows_event("Merchant Lina", "preset_1")

    def test_only_lina_knows_tampering(self, setup):
        graph, _, _ = setup
        assert graph.npc_knows_event("Merchant Lina", "preset_2")
        assert not graph.npc_knows_event("Village Elder", "preset_2")
        assert not graph.npc_knows_event("Blacksmith Gareth", "preset_2")


class TestPerceptionPipelineDifferences:
    """Each NPC sees a different subjective worldview."""

    def _make_builder(self, graph):
        kf = KnowledgeFilter(graph)
        be = BeliefEvaluator(graph)
        return PerceptionBuilder(kf, be)

    def test_elder_subjective_events(self, setup):
        graph, _, _ = setup
        builder = self._make_builder(graph)
        events = builder.build_perceived_events("Village Elder")
        event_ids = {e["event_id"] for e in events}
        assert "preset_1" in event_ids
        assert "preset_2" not in event_ids

    def test_lina_subjective_events(self, setup):
        graph, _, _ = setup
        builder = self._make_builder(graph)
        events = builder.build_perceived_events("Merchant Lina")
        event_ids = {e["event_id"] for e in events}
        assert "preset_2" in event_ids
        # Lina also knows preset_1 via propagation, but with distortion.
        if "preset_1" in event_ids:
            e1 = next(e for e in events if e["event_id"] == "preset_1")
            assert e1["source"] is not None  # second-hand

    def test_social_context_differs(self, setup):
        graph, _, _ = setup
        builder = self._make_builder(graph)
        elder_ctx = builder.build_social_context("Village Elder")
        lina_ctx = builder.build_social_context("Merchant Lina")
        # Elder doesn't know about tampering.
        assert "tampered" not in elder_ctx
        # Lina knows about tampering.
        assert "tampered" in lina_ctx


class TestTriggerEvent:
    """After a PUBLIC trigger event, all NPCs learn it with different beliefs."""

    def test_public_event_reaches_everyone(self, setup):
        graph, event_log, engine = setup

        trigger = SocialEvent(
            id="trigger_1",
            actor="Traveling Merchant",
            action="announced",
            description="A traveling merchant announces Gareth's metalwork is praised in the capital, but also mentions rumors of trade goods tampering in the village",
            visibility=EventVisibility.PUBLIC,
            tags=["trade", "praise", "rumor"],
        )
        event_log.append(trigger)
        created = engine.propagate_event(trigger, ALL_NPCS)
        knowers = {ki.knower for ki in created}
        assert knowers == set(ALL_NPCS)

    def test_lina_has_corroborating_knowledge(self, setup):
        graph, event_log, engine = setup
        trigger = SocialEvent(
            id="trigger_1",
            actor="Traveling Merchant",
            action="announced",
            description="A traveling merchant announces Gareth's metalwork is praised in the capital, but also mentions rumors of trade goods tampering in the village",
            visibility=EventVisibility.PUBLIC,
        )
        event_log.append(trigger)
        engine.propagate_event(trigger, ALL_NPCS)

        # Lina already knows about tampering (preset_2) + now hears the rumor (trigger_1).
        builder = self._make_builder(graph)
        events = builder.build_perceived_events("Merchant Lina")
        assert len(events) >= 2
        event_ids = {e["event_id"] for e in events}
        assert "preset_2" in event_ids
        assert "trigger_1" in event_ids

    def _make_builder(self, graph):
        kf = KnowledgeFilter(graph)
        be = BeliefEvaluator(graph)
        return PerceptionBuilder(kf, be)


class TestGossipFlow:
    """Lina gossips about tampering → Elder learns."""

    def test_gossip_spreads_private_info(self, setup):
        graph, event_log, engine = setup
        # Initially Elder doesn't know about tampering.
        assert not graph.npc_knows_event("Village Elder", "preset_2")

        # Lina gossips to Elder.
        created = engine.propagate_gossip(
            "Merchant Lina", "preset_2", recipients=["Village Elder"],
        )
        assert len(created) == 1
        assert created[0].knower == "Village Elder"
        assert created[0].source_npc == "Merchant Lina"
        assert created[0].distortion > 0

        # Now Elder knows.
        assert graph.npc_knows_event("Village Elder", "preset_2")

    def test_gossip_belief_evaluation(self, setup):
        graph, event_log, engine = setup
        engine.propagate_gossip(
            "Merchant Lina", "preset_2", recipients=["Village Elder"],
        )
        # Elder->Lina trust=0.5 → medium trust → SKEPTICAL
        builder = PerceptionBuilder(KnowledgeFilter(graph), BeliefEvaluator(graph))
        events = builder.build_perceived_events("Village Elder")
        e2 = next((e for e in events if e["event_id"] == "preset_2"), None)
        assert e2 is not None
        assert e2["belief_status"] == "skeptical"


class TestGraphDeltasFromEvents:
    """Verify graph deltas from events update edges."""

    def test_deltas_applied(self, setup):
        from annie.social_graph.models import GraphDelta

        graph, event_log, engine = setup
        old_trust = graph.get_edge("Village Elder", "Blacksmith Gareth").trust

        graph.apply_deltas([
            GraphDelta(
                source="Village Elder", target="Blacksmith Gareth",
                field="trust", delta=0.1, reason="praised in capital",
            ),
        ])
        new_trust = graph.get_edge("Village Elder", "Blacksmith Gareth").trust
        assert new_trust == pytest.approx(old_trust + 0.1)

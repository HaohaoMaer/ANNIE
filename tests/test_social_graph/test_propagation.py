"""Tests for PropagationEngine."""

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
from annie.social_graph.propagation import PropagationEngine


@pytest.fixture
def graph() -> SocialGraph:
    """Three-NPC graph matching the demo scenario."""
    g = SocialGraph()
    g.set_edge(RelationshipEdge(
        source="Elder", target="Gareth", type="trusted_ally",
        intensity=0.8, trust=0.7, familiarity=0.9,
    ))
    g.set_edge(RelationshipEdge(
        source="Elder", target="Lina", type="trade_partner",
        intensity=0.6, trust=0.5, familiarity=0.6,
    ))
    g.set_edge(RelationshipEdge(
        source="Gareth", target="Elder", type="trusted_ally",
        intensity=0.7, trust=0.8, familiarity=0.9,
    ))
    g.set_edge(RelationshipEdge(
        source="Gareth", target="Lina", type="acquaintance",
        intensity=0.3, trust=0.2, familiarity=0.4,
    ))
    g.set_edge(RelationshipEdge(
        source="Lina", target="Elder", type="trade_partner",
        intensity=0.5, trust=0.4, familiarity=0.6,
    ))
    g.set_edge(RelationshipEdge(
        source="Lina", target="Gareth", type="acquaintance",
        intensity=0.3, trust=0.3, familiarity=0.4,
    ))
    return g


@pytest.fixture
def event_log() -> SocialEventLog:
    return SocialEventLog()


@pytest.fixture
def engine(graph, event_log) -> PropagationEngine:
    return PropagationEngine(graph, event_log)


ALL_NPCS = ["Elder", "Gareth", "Lina"]


# ------------------------------------------------------------------
# PUBLIC events
# ------------------------------------------------------------------


class TestPublicEvent:
    def test_all_npcs_learn(self, engine, event_log):
        evt = SocialEvent(
            actor="Merchant", action="announced", description="Big news",
            visibility=EventVisibility.PUBLIC,
        )
        event_log.append(evt)
        created = engine.propagate_event(evt, ALL_NPCS)
        knowers = {ki.knower for ki in created}
        assert knowers == {"Elder", "Gareth", "Lina"}

    def test_first_hand_no_distortion(self, engine, event_log):
        evt = SocialEvent(
            actor="Merchant", action="announced", description="Big news",
            visibility=EventVisibility.PUBLIC,
        )
        event_log.append(evt)
        created = engine.propagate_event(evt, ALL_NPCS)
        for ki in created:
            assert ki.distortion == 0.0
            assert ki.source_npc is None
            assert ki.credibility == 1.0


# ------------------------------------------------------------------
# WITNESSED events
# ------------------------------------------------------------------


class TestWitnessedEvent:
    def test_actor_and_witnesses_learn(self, engine, event_log):
        evt = SocialEvent(
            actor="Gareth", target="Carpenter", action="accused",
            description="Gareth accused carpenter",
            witnesses=["Elder"],
            visibility=EventVisibility.WITNESSED,
        )
        event_log.append(evt)
        created = engine.propagate_event(evt, ALL_NPCS)
        knowers = {ki.knower for ki in created}
        # Gareth (actor) + Elder (witness) know first-hand.
        assert "Gareth" in knowers
        assert "Elder" in knowers

    def test_bfs_propagation(self, engine, event_log, graph):
        """Elder witnesses event → may propagate to Lina via trust chain."""
        evt = SocialEvent(
            actor="Gareth", target="Carpenter", action="accused",
            description="Gareth accused carpenter",
            witnesses=["Elder"],
            visibility=EventVisibility.WITNESSED,
        )
        event_log.append(evt)
        created = engine.propagate_event(evt, ALL_NPCS)
        knowers = {ki.knower for ki in created}

        # Elder->Lina: trust=0.5, willingness(trade_partner)=0.5
        # probability = 0.5 * 0.5 = 0.25 → above 0.15 threshold
        # Gareth->Lina: trust=0.2, willingness(acquaintance)=0.3
        # probability = 0.2 * 0.3 = 0.06 → below threshold, won't propagate from Gareth
        # So Lina should learn from Elder.
        assert "Lina" in knowers

    def test_propagation_adds_distortion(self, engine, event_log):
        evt = SocialEvent(
            actor="Gareth", target="Carpenter", action="accused",
            description="Gareth accused carpenter",
            witnesses=["Elder"],
            visibility=EventVisibility.WITNESSED,
        )
        event_log.append(evt)
        created = engine.propagate_event(evt, ALL_NPCS)
        lina_ki = [ki for ki in created if ki.knower == "Lina"]
        assert len(lina_ki) == 1
        assert lina_ki[0].distortion > 0
        assert lina_ki[0].source_npc is not None
        assert lina_ki[0].summary.startswith("Reportedly, ")

    def test_low_trust_blocks_propagation(self, engine, event_log, graph):
        """If trust is too low, propagation stops."""
        # Override Gareth->Lina to be enemy with low trust.
        graph.set_edge(RelationshipEdge(
            source="Gareth", target="Lina", type="enemy",
            trust=0.05,  # very low
        ))
        # Remove Elder->Lina so only path is Gareth->Lina.
        graph.set_edge(RelationshipEdge(
            source="Elder", target="Lina", type="trade_partner",
            trust=0.01,  # block this path too
        ))
        evt = SocialEvent(
            actor="Gareth", action="trained",
            description="Gareth trained alone",
            visibility=EventVisibility.WITNESSED,
        )
        event_log.append(evt)
        created = engine.propagate_event(evt, ALL_NPCS)
        knowers = {ki.knower for ki in created}
        assert "Lina" not in knowers

    def test_hostile_extra_distortion(self, engine, event_log, graph):
        """Enemy/rival edges add extra distortion."""
        graph.set_edge(RelationshipEdge(
            source="Elder", target="Lina", type="rival",
            trust=0.9,  # high trust, rival type (0.9*0.2=0.18 > 0.15)
        ))
        evt = SocialEvent(
            actor="Gareth", action="did something",
            description="Something happened",
            witnesses=["Elder"],
            visibility=EventVisibility.WITNESSED,
        )
        event_log.append(evt)
        created = engine.propagate_event(evt, ALL_NPCS)
        lina_ki = [ki for ki in created if ki.knower == "Lina"]
        assert len(lina_ki) == 1
        # Normal distortion 0.15 + hostile extra 0.3 = 0.45
        assert lina_ki[0].distortion == pytest.approx(0.45)


# ------------------------------------------------------------------
# PRIVATE events
# ------------------------------------------------------------------


class TestPrivateEvent:
    def test_only_principals_learn(self, engine, event_log):
        evt = SocialEvent(
            actor="Lina", action="discovered",
            description="Lina discovered tampering",
            visibility=EventVisibility.PRIVATE,
        )
        event_log.append(evt)
        created = engine.propagate_event(evt, ALL_NPCS)
        knowers = {ki.knower for ki in created}
        assert knowers == {"Lina"}

    def test_private_with_target(self, engine, event_log):
        evt = SocialEvent(
            actor="Lina", target="Gareth", action="whispered",
            description="Lina whispered to Gareth",
            visibility=EventVisibility.PRIVATE,
        )
        event_log.append(evt)
        created = engine.propagate_event(evt, ALL_NPCS)
        knowers = {ki.knower for ki in created}
        assert knowers == {"Lina", "Gareth"}
        assert "Elder" not in knowers


# ------------------------------------------------------------------
# SECRET events
# ------------------------------------------------------------------


class TestSecretEvent:
    def test_only_principals(self, engine, event_log):
        evt = SocialEvent(
            actor="Elder", target="Gareth", action="confided",
            description="Elder confided a secret",
            visibility=EventVisibility.SECRET,
        )
        event_log.append(evt)
        created = engine.propagate_event(evt, ALL_NPCS)
        knowers = {ki.knower for ki in created}
        assert knowers == {"Elder", "Gareth"}


# ------------------------------------------------------------------
# Gossip
# ------------------------------------------------------------------


class TestGossip:
    def test_explicit_gossip(self, engine, event_log, graph):
        evt = SocialEvent(
            actor="Lina", action="discovered",
            description="Trade goods tampered",
            visibility=EventVisibility.PRIVATE,
        )
        event_log.append(evt)
        engine.propagate_event(evt, ALL_NPCS)
        # Lina decides to gossip to Elder.
        created = engine.propagate_gossip("Lina", evt.id, recipients=["Elder"])
        assert len(created) == 1
        assert created[0].knower == "Elder"
        assert created[0].source_npc == "Lina"
        assert created[0].distortion > 0

    def test_gossip_unknown_event(self, engine):
        created = engine.propagate_gossip("Lina", "nonexistent")
        assert created == []

    def test_gossip_spreader_doesnt_know(self, engine, event_log):
        evt = SocialEvent(
            actor="Gareth", action="did something",
            description="Something",
            visibility=EventVisibility.PRIVATE,
        )
        event_log.append(evt)
        engine.propagate_event(evt, ALL_NPCS)
        # Lina doesn't know this event.
        created = engine.propagate_gossip("Lina", evt.id)
        assert created == []

    def test_gossip_no_duplicate(self, engine, event_log):
        evt = SocialEvent(
            actor="Gareth", action="x", description="x",
            visibility=EventVisibility.PRIVATE,
        )
        event_log.append(evt)
        engine.propagate_event(evt, ALL_NPCS)
        engine.propagate_gossip("Gareth", evt.id, recipients=["Elder"])
        # Gossip again — Elder already knows, should not duplicate.
        created = engine.propagate_gossip("Gareth", evt.id, recipients=["Elder"])
        assert created == []

    def test_gossip_default_recipients(self, engine, event_log, graph):
        """Default recipients = trusted contacts."""
        evt = SocialEvent(
            actor="Elder", action="saw", description="Saw something",
            visibility=EventVisibility.PRIVATE,
        )
        event_log.append(evt)
        engine.propagate_event(evt, ALL_NPCS)
        # Elder's outgoing edges: Gareth (trust=0.7), Lina (trust=0.5)
        # Both above 0.3 threshold → both should receive.
        created = engine.propagate_gossip("Elder", evt.id)
        knowers = {ki.knower for ki in created}
        assert "Gareth" in knowers
        assert "Lina" in knowers


# ------------------------------------------------------------------
# Tick
# ------------------------------------------------------------------


class TestTick:
    def test_tick_propagates_further(self, engine, event_log, graph):
        # Add a fourth NPC reachable only from Lina.
        graph.set_edge(RelationshipEdge(
            source="Lina", target="Scout", type="friend", trust=0.8,
        ))
        evt = SocialEvent(
            actor="Gareth", action="x", description="event",
            witnesses=["Elder"],
            visibility=EventVisibility.WITNESSED,
        )
        event_log.append(evt)
        # Initial propagation: Gareth, Elder know first-hand; Lina learns via BFS.
        engine.propagate_event(evt, ALL_NPCS + ["Scout"])

        assert graph.npc_knows_event("Lina", evt.id)
        # Scout may or may not know yet depending on depth. Let's tick.
        created = engine.tick(ALL_NPCS + ["Scout"])
        # After tick, Lina->Scout (trust=0.8, friend willingness=0.8) should fire.
        assert graph.npc_knows_event("Scout", evt.id)


# ------------------------------------------------------------------
# Idempotency
# ------------------------------------------------------------------


class TestIdempotency:
    def test_double_propagate_no_duplicates(self, engine, event_log):
        evt = SocialEvent(
            actor="Elder", action="x", description="x",
            visibility=EventVisibility.PUBLIC,
        )
        event_log.append(evt)
        first = engine.propagate_event(evt, ALL_NPCS)
        second = engine.propagate_event(evt, ALL_NPCS)
        assert len(first) == 3
        assert len(second) == 0  # all already know

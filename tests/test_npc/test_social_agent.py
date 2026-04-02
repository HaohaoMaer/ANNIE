"""Tests for SocialAgent."""

import pytest

from annie.npc.memory.relationship import RelationshipMemory
from annie.npc.state import RelationshipDef
from annie.npc.sub_agents.social_agent import SocialAgent


@pytest.fixture
def relationship_memory():
    return RelationshipMemory(
        "Elder",
        initial_relationships=[
            RelationshipDef(target="NPC_B", type="friend", intensity=0.7),
            RelationshipDef(target="NPC_C", type="rival", intensity=0.4),
        ],
    )


@pytest.fixture
def social_agent(relationship_memory):
    return SocialAgent(relationship_memory)


class TestSocialAgent:
    def test_get_relationship_context_known(self, social_agent):
        ctx = social_agent.get_relationship_context("NPC_B")
        assert "friend" in ctx
        assert "0.7" in ctx

    def test_get_relationship_context_unknown(self, social_agent):
        ctx = social_agent.get_relationship_context("Unknown_NPC")
        assert "No known relationship" in ctx

    def test_get_all_context(self, social_agent):
        ctx = social_agent.get_all_context()
        assert "NPC_B" in ctx
        assert "NPC_C" in ctx
        assert "friend" in ctx
        assert "rival" in ctx

    def test_get_all_context_empty(self):
        empty_memory = RelationshipMemory("Loner")
        agent = SocialAgent(empty_memory)
        ctx = agent.get_all_context()
        assert ctx == "No known relationships."

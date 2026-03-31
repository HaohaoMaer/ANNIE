"""Tests for MemoryAgent."""

import uuid

import chromadb
import pytest

from annie.npc.memory.episodic import EpisodicMemory
from annie.npc.memory.relationship import RelationshipMemory
from annie.npc.memory.semantic import SemanticMemory
from annie.npc.state import RelationshipDef
from annie.npc.sub_agents.memory_agent import MemoryAgent


@pytest.fixture
def memory_agent():
    client = chromadb.EphemeralClient()
    uid = uuid.uuid4().hex[:8]
    episodic = EpisodicMemory("test", client=client, collection_name=f"ep_{uid}")
    semantic = SemanticMemory("test", client=client, collection_name=f"sem_{uid}")
    relationship = RelationshipMemory(
        "test",
        initial_relationships=[
            RelationshipDef(target="Bob", type="friend", intensity=0.8)
        ],
    )
    return MemoryAgent(episodic, semantic, relationship)


class TestMemoryAgent:
    def test_build_context_no_episodic_or_semantic(self, memory_agent):
        ctx = memory_agent.build_context("anything")
        # Has relationships but no episodic/semantic memories
        assert "Relationships:" in ctx
        assert "Recent experiences:" not in ctx
        assert "Known facts:" not in ctx

    def test_build_context_truly_empty(self):
        import uuid
        import chromadb
        client = chromadb.EphemeralClient()
        uid = uuid.uuid4().hex[:8]
        from annie.npc.memory.episodic import EpisodicMemory
        from annie.npc.memory.semantic import SemanticMemory
        from annie.npc.memory.relationship import RelationshipMemory
        agent = MemoryAgent(
            EpisodicMemory("t", client=client, collection_name=f"ep_{uid}"),
            SemanticMemory("t", client=client, collection_name=f"sem_{uid}"),
            RelationshipMemory("t"),
        )
        ctx = agent.build_context("anything")
        assert "No relevant memories" in ctx

    def test_build_context_with_relationships(self, memory_agent):
        ctx = memory_agent.build_context("Bob")
        assert "Relationships:" in ctx
        assert "Bob" in ctx
        assert "friend" in ctx

    def test_store_and_build_context_episodic(self, memory_agent):
        memory_agent.store_episodic("Met a trader at the gate.")
        ctx = memory_agent.build_context("trader")
        assert "Recent experiences:" in ctx
        assert "trader" in ctx

    def test_store_and_build_context_semantic(self, memory_agent):
        memory_agent.store_semantic("Iron is expensive this season.", category="economy")
        ctx = memory_agent.build_context("iron prices")
        assert "Known facts:" in ctx
        assert "Iron" in ctx

    def test_store_episodic_returns_id(self, memory_agent):
        doc_id = memory_agent.store_episodic("Something happened.")
        assert isinstance(doc_id, str)
        assert len(doc_id) > 0

    def test_store_semantic_returns_id(self, memory_agent):
        doc_id = memory_agent.store_semantic("A new fact.")
        assert isinstance(doc_id, str)
        assert len(doc_id) > 0

    def test_build_context_aggregates_all_types(self, memory_agent):
        memory_agent.store_episodic("Saw wolves near the forest.")
        memory_agent.store_semantic("Wolves are dangerous predators.")
        ctx = memory_agent.build_context("wolves danger")
        assert "Recent experiences:" in ctx
        assert "Known facts:" in ctx
        assert "Relationships:" in ctx

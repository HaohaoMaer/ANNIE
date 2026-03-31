"""Tests for Relationship Memory."""

import pytest

from annie.npc.memory.relationship import RelationshipMemory
from annie.npc.state import RelationshipDef


@pytest.fixture
def relationship_memory():
    rels = [
        RelationshipDef(target="NPC_B", type="friend", intensity=0.7),
        RelationshipDef(target="NPC_C", type="rival", intensity=0.4),
    ]
    return RelationshipMemory("test_npc", initial_relationships=rels)


class TestRelationshipMemory:
    def test_get_relationship(self, relationship_memory):
        rel = relationship_memory.get_relationship("NPC_B")
        assert rel is not None
        assert rel.type == "friend"
        assert rel.intensity == 0.7

    def test_get_relationship_unknown(self, relationship_memory):
        rel = relationship_memory.get_relationship("NPC_Z")
        assert rel is None

    def test_get_all_relationships(self, relationship_memory):
        rels = relationship_memory.get_all_relationships()
        assert len(rels) == 2
        targets = {r.target for r in rels}
        assert targets == {"NPC_B", "NPC_C"}

    def test_empty_init(self):
        mem = RelationshipMemory("lonely_npc")
        assert mem.get_all_relationships() == []

    def test_update_relationship(self, relationship_memory):
        relationship_memory.update_relationship("NPC_B", "enemy", 0.9)
        rel = relationship_memory.get_relationship("NPC_B")
        assert rel.type == "enemy"
        assert rel.intensity == 0.9

    def test_update_clamps_intensity(self, relationship_memory):
        relationship_memory.update_relationship("NPC_D", "friend", 1.5)
        rel = relationship_memory.get_relationship("NPC_D")
        assert rel.intensity == 1.0

        relationship_memory.update_relationship("NPC_E", "enemy", -0.3)
        rel = relationship_memory.get_relationship("NPC_E")
        assert rel.intensity == 0.0

    def test_describe(self, relationship_memory):
        desc = relationship_memory.describe()
        assert "NPC_B" in desc
        assert "friend" in desc
        assert "NPC_C" in desc
        assert "rival" in desc

    def test_describe_empty(self):
        mem = RelationshipMemory("lonely_npc")
        assert mem.describe() == "No known relationships."

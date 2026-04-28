"""Tests for world-engine-owned NPC profiles."""

import pytest

from annie.world_engine.profile import NPCProfile, load_npc_profile


class TestNPCProfile:
    def test_load_example_npc(self):
        profile = load_npc_profile("data/npcs/example_npc.yaml")
        assert isinstance(profile, NPCProfile)
        assert profile.name == "Example NPC"
        assert "calm" in profile.personality.traits
        assert "rational" in profile.personality.traits
        assert "logic" in profile.personality.values

    def test_relationships(self):
        profile = load_npc_profile("data/npcs/example_npc.yaml")
        assert len(profile.relationships) == 1
        rel = profile.relationships[0]
        assert rel.target == "NPC_B"
        assert rel.type == "friend"
        assert rel.intensity == 0.7

    def test_memory_seed(self):
        profile = load_npc_profile("data/npcs/example_npc.yaml")
        assert "Initial important memory" in profile.memory_seed

    def test_skills_and_tools_defaults_and_values(self):
        profile = load_npc_profile("data/npcs/example_npc.yaml")
        assert profile.skills == []
        assert profile.tools == []

        profile = NPCProfile(
            name="Test",
            skills=["negotiation", "storytelling"],
            tools=["inspect_item"],
        )
        assert profile.skills == ["negotiation", "storytelling"]
        assert profile.tools == ["inspect_item"]

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError, match="NPC definition file not found"):
            load_npc_profile("nonexistent/npc.yaml")

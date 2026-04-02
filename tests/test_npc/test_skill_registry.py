"""Tests for SkillRegistry two-tier loading."""

import pytest

from annie.npc.skills.base_skill import SkillRegistry


class TestSkillRegistryTwoTier:
    def test_loads_base_skills(self):
        registry = SkillRegistry("data/skills")
        skills = registry.list_skills()
        assert "conversation" in skills
        assert "observation" in skills
        assert "reasoning" in skills

    def test_base_only_when_no_npc_skills(self):
        registry = SkillRegistry("data/skills")
        skills = registry.list_skills()
        assert "negotiation" not in skills
        assert "storytelling" not in skills

    def test_loads_personalized_skills(self):
        registry = SkillRegistry("data/skills", npc_skill_names=["negotiation"])
        skills = registry.list_skills()
        # Base skills present
        assert "conversation" in skills
        assert "observation" in skills
        # Requested personalized skill present
        assert "negotiation" in skills
        # Unrequested personalized skill absent
        assert "storytelling" not in skills

    def test_loads_multiple_personalized_skills(self):
        registry = SkillRegistry(
            "data/skills", npc_skill_names=["negotiation", "storytelling"]
        )
        assert "negotiation" in registry.list_skills()
        assert "storytelling" in registry.list_skills()

    def test_nonexistent_personalized_skill_ignored(self):
        registry = SkillRegistry(
            "data/skills", npc_skill_names=["nonexistent_skill"]
        )
        # Should still have base skills, no error
        assert "conversation" in registry.list_skills()
        assert "nonexistent_skill" not in registry.list_skills()

    def test_empty_npc_skills_loads_base_only(self):
        registry = SkillRegistry("data/skills", npc_skill_names=[])
        skills = registry.list_skills()
        assert "conversation" in skills
        assert "negotiation" not in skills

    def test_fallback_flat_directory(self):
        """When base/ subdir doesn't exist, falls back to flat loading."""
        registry = SkillRegistry("data/skills/base")
        # data/skills/base has no base/ subdir, so it loads flat
        assert "conversation" in registry.list_skills()

    def test_nonexistent_directory(self):
        registry = SkillRegistry("nonexistent/dir")
        assert registry.list_skills() == []

    def test_get_descriptions_includes_all(self):
        registry = SkillRegistry("data/skills", npc_skill_names=["negotiation"])
        descs = registry.get_descriptions()
        assert "conversation" in descs
        assert "negotiation" in descs
        assert "Negotiation" in descs["negotiation"]

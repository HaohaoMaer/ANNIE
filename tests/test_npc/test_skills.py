"""Tests for the Skill System."""

import pytest

from annie.npc.skills.base_skill import BaseSkill, SkillRegistry
from annie.npc.state import NPCProfile, Personality


@pytest.fixture
def example_skill():
    return BaseSkill("data/skills/example_skill")


@pytest.fixture
def conversation_skill():
    return BaseSkill("data/skills/base/conversation")


@pytest.fixture
def mock_npc_profile():
    return NPCProfile(
        name="Test NPC",
        personality=Personality(traits=["brave", "curious"], values=["honor"]),
    )


class TestBaseSkill:
    def test_load_from_directory(self, example_skill):
        assert example_skill.name == "example_skill"
        assert "Example Skill" in example_skill.description

    def test_description_loaded(self, example_skill):
        assert "Template for defining a new NPC skill" in example_skill.description

    def test_execute(self, example_skill):
        result = example_skill.execute({"key": "value"})
        assert isinstance(result, dict)

    def test_render_prompt(self, example_skill, mock_npc_profile):
        rendered = example_skill.render_prompt(mock_npc_profile)
        assert "Test NPC" in rendered

    def test_nonexistent_directory(self):
        with pytest.raises(FileNotFoundError):
            BaseSkill("nonexistent/skill")

    def test_conversation_skill_execute(self, conversation_skill):
        result = conversation_skill.execute({"task": "greet", "npc_name": "Elder"})
        assert result["skill_type"] == "conversation"
        assert result["npc_name"] == "Elder"

    def test_conversation_skill_render(self, conversation_skill, mock_npc_profile):
        rendered = conversation_skill.render_prompt(mock_npc_profile)
        assert "Test NPC" in rendered


class TestSkillRegistry:
    def test_loads_skills_from_directory(self):
        registry = SkillRegistry("data/skills")
        assert "conversation" in registry.list_skills()

    def test_get_skill(self):
        registry = SkillRegistry("data/skills")
        skill = registry.get("conversation")
        assert skill is not None
        assert skill.name == "conversation"

    def test_get_nonexistent_skill(self):
        registry = SkillRegistry("data/skills")
        assert registry.get("nonexistent") is None

    def test_list_skills(self):
        registry = SkillRegistry("data/skills")
        skills = registry.list_skills()
        assert isinstance(skills, list)
        assert len(skills) >= 1

    def test_get_descriptions(self):
        registry = SkillRegistry("data/skills")
        descs = registry.get_descriptions()
        assert isinstance(descs, dict)
        assert "conversation" in descs
        assert "Conversation" in descs["conversation"]

    def test_nonexistent_directory(self):
        registry = SkillRegistry("nonexistent/dir")
        assert registry.list_skills() == []

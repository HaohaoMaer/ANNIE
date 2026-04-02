"""Tests for SkillAgent."""

from unittest.mock import MagicMock

import pytest

from annie.npc.skills.base_skill import SkillRegistry
from annie.npc.state import NPCProfile, Personality
from annie.npc.sub_agents.skill_agent import SkillAgent, _meaningful_words
from annie.npc.tracing import EventType, Tracer


@pytest.fixture
def skill_registry():
    return SkillRegistry("data/skills")


@pytest.fixture
def skill_agent(skill_registry):
    return SkillAgent(skill_registry)


@pytest.fixture
def npc_profile():
    return NPCProfile(
        name="Elder",
        personality=Personality(traits=["wise", "cautious"], values=["safety"]),
    )


class TestMeaningfulWords:
    def test_filters_stop_words(self):
        words = _meaningful_words("the quick brown fox is in the forest")
        assert "the" not in words
        assert "quick" in words
        assert "brown" in words

    def test_filters_short_words(self):
        words = _meaningful_words("go to me")
        assert words == set()

    def test_lowercases(self):
        words = _meaningful_words("Quick Brown Fox")
        assert "quick" in words


class TestSkillAgent:
    def test_select_skill_conversation(self, skill_agent):
        result = skill_agent.select_skill(
            "speak with the stranger and greet them with dialogue"
        )
        assert result == "conversation"

    def test_select_skill_observation(self, skill_agent):
        result = skill_agent.select_skill(
            "observe the surroundings and analyze the environment carefully"
        )
        assert result == "observation"

    def test_select_skill_none_for_vague(self, skill_agent):
        result = skill_agent.select_skill("do something")
        assert result is None

    def test_invoke_existing_skill(self, skill_agent, npc_profile):
        result = skill_agent.invoke(
            "conversation",
            {"task": "greet", "npc_name": "Elder"},
            npc_profile,
        )
        assert result["skill_type"] == "conversation"

    def test_invoke_nonexistent_skill(self, skill_agent, npc_profile):
        result = skill_agent.invoke("nonexistent", {}, npc_profile)
        assert result == {}

    def test_try_skill_returns_string(self, skill_agent, npc_profile):
        result = skill_agent.try_skill(
            "speak with the stranger and greet them with dialogue",
            npc_profile,
        )
        assert result is not None
        assert "conversation" in result

    def test_try_skill_returns_none_for_no_match(self, skill_agent, npc_profile):
        result = skill_agent.try_skill("xyz", npc_profile)
        assert result is None

    def test_try_skill_traces(self, skill_agent, npc_profile):
        tracer = Tracer("Elder")
        skill_agent.try_skill(
            "speak with the stranger and greet them with dialogue",
            npc_profile,
            tracer=tracer,
        )
        skill_events = [
            e for e in tracer.events if e.event_type == EventType.SKILL_INVOKE
        ]
        assert len(skill_events) == 1
        assert "conversation" in skill_events[0].output_summary

    def test_empty_registry(self, npc_profile):
        registry = SkillRegistry("nonexistent/dir")
        agent = SkillAgent(registry)
        assert agent.select_skill("anything") is None
        assert agent.try_skill("anything", npc_profile) is None

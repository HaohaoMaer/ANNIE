"""Tests for Reflector node."""

from unittest.mock import MagicMock

import pytest

from annie.npc.reflector import Reflector
from annie.npc.state import AgentState, NPCProfile, Personality
from annie.npc.tracing import EventType, Tracer


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    response = MagicMock()
    response.content = (
        'REFLECTION: The encounter with the stranger was unsettling but informative.\n'
        'FACTS: ["The stranger wore a merchant guild emblem", "Traders are arriving from the east"]'
    )
    llm.invoke.return_value = response
    return llm


@pytest.fixture
def mock_memory_agent():
    agent = MagicMock()
    agent.store_episodic.return_value = "doc123"
    agent.store_semantic.return_value = "doc456"
    return agent


@pytest.fixture
def npc_profile():
    return NPCProfile(
        name="Elder",
        personality=Personality(traits=["wise", "cautious"], values=["safety"]),
    )


@pytest.fixture
def reflector(mock_llm, mock_memory_agent):
    return Reflector(mock_llm, mock_memory_agent)


class TestReflector:
    def test_returns_reflection(self, reflector, npc_profile):
        tracer = Tracer("Elder")
        state: AgentState = {
            "npc_profile": npc_profile,
            "input_event": "A stranger approaches.",
            "execution_results": [
                {"task_description": "Observe stranger", "action": "Watched carefully."},
            ],
            "tracer": tracer,
        }
        result = reflector(state)
        assert "reflection" in result
        assert "unsettling" in result["reflection"]

    def test_stores_episodic_memory(self, reflector, npc_profile, mock_memory_agent):
        tracer = Tracer("Elder")
        state: AgentState = {
            "npc_profile": npc_profile,
            "input_event": "A stranger approaches.",
            "execution_results": [
                {"task_description": "Observe", "action": "Watched."},
            ],
            "tracer": tracer,
        }
        reflector(state)
        mock_memory_agent.store_episodic.assert_called_once()
        stored = mock_memory_agent.store_episodic.call_args[0][0]
        assert "stranger" in stored

    def test_stores_semantic_facts(self, reflector, npc_profile, mock_memory_agent):
        tracer = Tracer("Elder")
        state: AgentState = {
            "npc_profile": npc_profile,
            "input_event": "A stranger approaches.",
            "execution_results": [
                {"task_description": "Observe", "action": "Watched."},
            ],
            "tracer": tracer,
        }
        reflector(state)
        assert mock_memory_agent.store_semantic.call_count == 2
        calls = [c[0][0] for c in mock_memory_agent.store_semantic.call_args_list]
        assert "merchant guild emblem" in calls[0]
        assert "Traders are arriving" in calls[1]

    def test_tracing_events(self, reflector, npc_profile):
        tracer = Tracer("Elder")
        state: AgentState = {
            "npc_profile": npc_profile,
            "input_event": "Event",
            "execution_results": [
                {"task_description": "Task", "action": "Action."},
            ],
            "tracer": tracer,
        }
        reflector(state)
        event_types = [e.event_type for e in tracer.events]
        assert EventType.NODE_ENTER in event_types
        assert EventType.NODE_EXIT in event_types
        assert EventType.LLM_CALL in event_types
        assert EventType.LLM_RESPONSE in event_types
        assert EventType.MEMORY_WRITE in event_types

    def test_works_without_tracer(self, reflector, npc_profile):
        state: AgentState = {
            "npc_profile": npc_profile,
            "input_event": "Event",
            "execution_results": [
                {"task_description": "Task", "action": "Action."},
            ],
        }
        result = reflector(state)
        assert "reflection" in result

    def test_handles_no_facts(self, npc_profile, mock_memory_agent):
        llm = MagicMock()
        response = MagicMock()
        response.content = "REFLECTION: Nothing much happened."
        llm.invoke.return_value = response
        reflector = Reflector(llm, mock_memory_agent)
        tracer = Tracer("Elder")
        state: AgentState = {
            "npc_profile": npc_profile,
            "input_event": "Event",
            "execution_results": [
                {"task_description": "Task", "action": "Action."},
            ],
            "tracer": tracer,
        }
        result = reflector(state)
        assert result["reflection"] == "Nothing much happened."
        mock_memory_agent.store_semantic.assert_not_called()

    def test_handles_plain_text_response(self, npc_profile, mock_memory_agent):
        llm = MagicMock()
        response = MagicMock()
        response.content = "The elder feels uneasy about the encounter."
        llm.invoke.return_value = response
        reflector = Reflector(llm, mock_memory_agent)
        state: AgentState = {
            "npc_profile": npc_profile,
            "input_event": "Event",
            "execution_results": [
                {"task_description": "Task", "action": "Action."},
            ],
        }
        result = reflector(state)
        assert "uneasy" in result["reflection"]

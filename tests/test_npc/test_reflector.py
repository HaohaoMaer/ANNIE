"""Tests for Reflector node."""

from unittest.mock import MagicMock
from types import SimpleNamespace

import pytest

from annie.npc.reflector import Reflector
from annie.npc.context import AgentContext
from annie.npc.state import AgentState
from annie.npc.tracing import EventType, Tracer


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    response = MagicMock()
    response.content = (
        '{"reflection":"The encounter with the stranger was unsettling but informative.",'
        '"facts":["The stranger wore a merchant guild emblem","Traders are arriving from the east"],'
        '"relationship_notes":[]}'
    )
    llm.invoke.return_value = response
    return llm


@pytest.fixture
def npc_profile():
    return SimpleNamespace(
        name="Elder",
        personality=SimpleNamespace(traits=["wise", "cautious"], values=["safety"]),
    )


@pytest.fixture
def reflector(mock_llm):
    return Reflector(mock_llm)


def _ctx(profile) -> AgentContext:
    return AgentContext(
        npc_id=profile.name,
        input_event="",
        memory=MagicMock(),
        character_prompt=f"Traits: {', '.join(profile.personality.traits)}",
    )


class TestReflector:
    def test_returns_reflection(self, reflector, npc_profile):
        tracer = Tracer("Elder")
        state: AgentState = {
            "agent_context": _ctx(npc_profile),
            "input_event": "A stranger approaches.",
            "execution_results": [
                {"task_description": "Observe stranger", "action": "Watched carefully."},
            ],
            "tracer": tracer,
        }
        result = reflector(state)
        assert "reflection" in result
        assert "unsettling" in result["reflection"]

    def test_declares_reflection_memory(self, reflector, npc_profile):
        tracer = Tracer("Elder")
        state: AgentState = {
            "agent_context": _ctx(npc_profile),
            "input_event": "A stranger approaches.",
            "execution_results": [
                {"task_description": "Observe", "action": "Watched."},
            ],
            "tracer": tracer,
        }
        result = reflector(state)
        assert result["memory_updates"][0].type == "reflection"
        assert "stranger" in result["memory_updates"][0].content

    def test_declares_semantic_facts(self, reflector, npc_profile):
        tracer = Tracer("Elder")
        state: AgentState = {
            "agent_context": _ctx(npc_profile),
            "input_event": "A stranger approaches.",
            "execution_results": [
                {"task_description": "Observe", "action": "Watched."},
            ],
            "tracer": tracer,
        }
        result = reflector(state)
        calls = [u.content for u in result["memory_updates"] if u.type == "semantic"]
        assert len(calls) == 2
        assert "merchant guild emblem" in calls[0]
        assert "Traders are arriving" in calls[1]

    def test_tracing_events(self, reflector, npc_profile):
        tracer = Tracer("Elder")
        state: AgentState = {
            "agent_context": _ctx(npc_profile),
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
            "agent_context": _ctx(npc_profile),
            "input_event": "Event",
            "execution_results": [
                {"task_description": "Task", "action": "Action."},
            ],
        }
        result = reflector(state)
        assert "reflection" in result

    def test_handles_no_facts(self, npc_profile):
        llm = MagicMock()
        response = MagicMock()
        response.content = '{"reflection":"Nothing much happened.","facts":[],"relationship_notes":[]}'
        llm.invoke.return_value = response
        reflector = Reflector(llm)
        tracer = Tracer("Elder")
        state: AgentState = {
            "agent_context": _ctx(npc_profile),
            "input_event": "Event",
            "execution_results": [
                {"task_description": "Task", "action": "Action."},
            ],
            "tracer": tracer,
        }
        result = reflector(state)
        assert result["reflection"] == "Nothing much happened."
        assert [u for u in result["memory_updates"] if u.type == "semantic"] == []

    def test_handles_plain_text_response(self, npc_profile):
        llm = MagicMock()
        response = MagicMock()
        response.content = "The elder feels uneasy about the encounter."
        llm.invoke.return_value = response
        reflector = Reflector(llm)
        state: AgentState = {
            "agent_context": _ctx(npc_profile),
            "input_event": "Event",
            "execution_results": [
                {"task_description": "Task", "action": "Action."},
            ],
        }
        result = reflector(state)
        assert "uneasy" in result["reflection"]
        assert [u for u in result["memory_updates"] if u.type == "semantic"] == []

    def test_declares_relationship_notes(self, npc_profile):
        llm = MagicMock()
        response = MagicMock()
        response.content = (
            '{"reflection":"I learned how Bob handled pressure.",'
            '"facts":[],'
            '"relationship_notes":[{"person":"Bob","observation":"Bob stayed calm."}]}'
        )
        llm.invoke.return_value = response
        result = Reflector(llm)({
            "agent_context": _ctx(npc_profile),
            "input_event": "Event",
            "execution_results": [
                {"task_description": "Task", "action": "Action."},
            ],
        })
        notes = [u for u in result["memory_updates"] if u.metadata.get("person") == "Bob"]
        assert len(notes) == 1
        assert notes[0].content == "Bob stayed calm."

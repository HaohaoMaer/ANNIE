"""Tests for Planner node."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from annie.npc.planner import Planner
from annie.npc.state import AgentState, Task
from annie.npc.tracing import EventType, Tracer


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    response = MagicMock()
    response.content = json.dumps({
        "decision": "plan",
        "reason": "needs ordered checks",
        "tasks": [
            {"description": "Observe the stranger carefully", "priority": 8},
            {"description": "Recall past encounters with travelers", "priority": 6},
        ],
    })
    llm.invoke.return_value = response
    return llm


@pytest.fixture
def ctx():
    return SimpleNamespace(
        npc_id="Elder",
        character_prompt="Traits: wise, cautious",
        world_rules="Protect village continuity.",
        situation="At the village gate.",
        input_event="A stranger approaches the village.",
        todo="",
    )


@pytest.fixture
def planner(mock_llm):
    return Planner(mock_llm)


class TestPlanner:
    def test_returns_tasks(self, planner, ctx):
        tracer = Tracer("Elder")
        state: AgentState = {
            "agent_context": ctx,
            "input_event": "A stranger approaches the village.",
            "tracer": tracer,
        }
        result = planner(state)
        assert "tasks" in result
        assert len(result["tasks"]) == 2
        assert all(isinstance(t, Task) for t in result["tasks"])

    def test_task_descriptions(self, planner, ctx):
        tracer = Tracer("Elder")
        state: AgentState = {
            "agent_context": ctx,
            "input_event": "A stranger approaches.",
            "tracer": tracer,
        }
        result = planner(state)
        descriptions = [t.description for t in result["tasks"]]
        assert "Observe the stranger carefully" in descriptions

    def test_task_priorities(self, planner, ctx):
        tracer = Tracer("Elder")
        state: AgentState = {
            "agent_context": ctx,
            "input_event": "A stranger approaches.",
            "tracer": tracer,
        }
        result = planner(state)
        assert result["tasks"][0].priority == 8
        assert result["tasks"][1].priority == 6

    def test_tracing_events(self, planner, ctx):
        tracer = Tracer("Elder")
        state: AgentState = {
            "agent_context": ctx,
            "input_event": "A stranger approaches.",
            "tracer": tracer,
        }
        planner(state)
        event_types = [e.event_type for e in tracer.events]
        assert EventType.NODE_ENTER in event_types
        assert EventType.NODE_EXIT in event_types
        assert EventType.LLM_CALL in event_types
        assert EventType.LLM_RESPONSE in event_types
        assert EventType.TASK_CREATED in event_types

    def test_llm_called_with_messages(self, planner, ctx, mock_llm):
        tracer = Tracer("Elder")
        state: AgentState = {
            "agent_context": ctx,
            "input_event": "A stranger approaches.",
            "tracer": tracer,
        }
        planner(state)
        mock_llm.invoke.assert_called_once()
        messages = mock_llm.invoke.call_args[0][0]
        assert len(messages) == 2  # system + human

    def test_skip_json_returns_no_tasks(self, ctx):
        llm = MagicMock()
        response = MagicMock()
        response.content = '{"decision":"skip","reason":"simple","tasks":[]}'
        llm.invoke.return_value = response
        planner = Planner(llm)
        tracer = Tracer("Elder")
        state: AgentState = {
            "agent_context": ctx,
            "input_event": "Event",
            "tracer": tracer,
        }
        result = planner(state)
        assert result["tasks"] == []

    def test_handles_invalid_json_without_creating_task(self, ctx):
        llm = MagicMock()
        response = MagicMock()
        response.content = "I think the NPC should do something"
        llm.invoke.return_value = response
        planner = Planner(llm)
        tracer = Tracer("Elder")
        state: AgentState = {
            "agent_context": ctx,
            "input_event": "Event",
            "tracer": tracer,
        }
        result = planner(state)
        assert result["tasks"] == []
        assert result["planner_error"] == "invalid JSON"
        assert result["loop_reason"] == "planner parse failed"

    def test_malformed_plan_without_creating_task(self, ctx):
        llm = MagicMock()
        response = MagicMock()
        response.content = '{"decision":"plan","reason":"bad","tasks":[]}'
        llm.invoke.return_value = response
        result = Planner(llm)({"agent_context": ctx, "input_event": "Event"})
        assert result["tasks"] == []
        assert result["planner_error"] == "plan decision requires non-empty tasks"

    def test_plan_task_missing_priority_without_creating_task(self, ctx):
        llm = MagicMock()
        response = MagicMock()
        response.content = (
            '{"decision":"plan","reason":"bad",'
            '"tasks":[{"description":"Do something"}]}'
        )
        llm.invoke.return_value = response
        result = Planner(llm)({"agent_context": ctx, "input_event": "Event"})
        assert result["tasks"] == []
        assert result["planner_error"] == "task priority must be an integer from 0 to 10"

    def test_works_without_tracer(self, planner, ctx):
        state: AgentState = {
            "agent_context": ctx,
            "input_event": "A stranger approaches.",
        }
        result = planner(state)
        assert len(result["tasks"]) == 2

    def test_includes_memory_context(self, planner, ctx, mock_llm):
        tracer = Tracer("Elder")
        state: AgentState = {
            "agent_context": ctx,
            "input_event": "A stranger approaches.",
            "working_memory": "Previously encountered bandits.",
            "tracer": tracer,
        }
        planner(state)
        messages = mock_llm.invoke.call_args[0][0]
        assert "bandits" in messages[1].content

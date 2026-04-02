"""Tests for ToolAgent."""

import pytest

from annie.npc.sub_agents.tool_agent import ToolAgent
from annie.npc.tools.tool_registry import ToolRegistry
from annie.npc.tracing import EventType, Tracer


@pytest.fixture
def tool_registry():
    return ToolRegistry()


@pytest.fixture
def tool_agent(tool_registry):
    return ToolAgent(tool_registry)


class TestToolAgent:
    def test_select_tool_perception(self, tool_agent):
        result = tool_agent.select_tool(
            "observe the environment and categorize entities nearby"
        )
        assert result == "perception"

    def test_select_tool_memory(self, tool_agent):
        result = tool_agent.select_tool(
            "query memory for relevant context about the stranger"
        )
        assert result == "memory_query"

    def test_select_tool_none_for_vague(self, tool_agent):
        result = tool_agent.select_tool("do something")
        assert result is None

    def test_invoke_existing_tool(self, tool_agent):
        result = tool_agent.invoke(
            "perception",
            {"task": "A stranger approaches."},
        )
        assert result["tool"] == "perception"
        assert "stranger" in result["entities"]

    def test_invoke_nonexistent_tool(self, tool_agent):
        result = tool_agent.invoke("nonexistent", {})
        assert result == {}

    def test_try_tool_returns_string(self, tool_agent):
        result = tool_agent.try_tool(
            "observe the environment and categorize entities nearby",
            "Elder",
        )
        assert result is not None
        assert "perception" in result

    def test_try_tool_returns_none_for_no_match(self, tool_agent):
        result = tool_agent.try_tool("xyz", "Elder")
        assert result is None

    def test_try_tool_traces(self, tool_agent):
        tracer = Tracer("Elder")
        tool_agent.try_tool(
            "observe the environment and categorize entities nearby",
            "Elder",
            tracer=tracer,
        )
        tool_events = [
            e for e in tracer.events if e.event_type == EventType.TOOL_INVOKE
        ]
        assert len(tool_events) == 1
        assert "perception" in tool_events[0].output_summary

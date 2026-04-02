"""Tests for Tool System."""

from unittest.mock import MagicMock

import pytest

from annie.npc.tools.base_tool import BaseTool
from annie.npc.tools.memory_query import MemoryQueryTool
from annie.npc.tools.perception import PerceptionTool
from annie.npc.tools.tool_registry import ToolRegistry


class TestBaseTool:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            BaseTool()


class TestPerceptionTool:
    def test_basic_perception(self):
        tool = PerceptionTool()
        result = tool.execute({"task": "A stranger approaches the village."})
        assert result["tool"] == "perception"
        assert "stranger" in result["entities"]
        assert result["threat_level"] == "low"

    def test_threat_detection_medium(self):
        tool = PerceptionTool()
        result = tool.execute({"task": "A stranger with a weapon appears."})
        assert result["threat_level"] == "medium"

    def test_threat_detection_high(self):
        tool = PerceptionTool()
        result = tool.execute({"task": "The enemy attacks with a weapon!"})
        assert result["threat_level"] == "high"

    def test_multiple_entities(self):
        tool = PerceptionTool()
        result = tool.execute({"task": "A merchant and a guard arrive."})
        assert "merchant" in result["entities"]
        assert "guard" in result["entities"]

    def test_no_entities(self):
        tool = PerceptionTool()
        result = tool.execute({"task": "The wind blows."})
        assert result["entities"] == []

    def test_uses_event_field(self):
        tool = PerceptionTool()
        result = tool.execute({"task": "look around", "event": "A traveler is nearby."})
        assert "traveler" in result["entities"]


class TestMemoryQueryTool:
    def test_without_memory_agent(self):
        tool = MemoryQueryTool()
        result = tool.execute({"query": "test"})
        assert "not available" in result["results"]

    def test_with_memory_agent(self):
        tool = MemoryQueryTool()
        mock_agent = MagicMock()
        mock_agent.build_context.return_value = "Found: a stranger arrived yesterday."
        tool.set_memory_agent(mock_agent)

        result = tool.execute({"query": "stranger"})
        assert result["tool"] == "memory_query"
        assert "stranger arrived yesterday" in result["results"]
        mock_agent.build_context.assert_called_once_with("stranger")

    def test_uses_task_as_fallback_query(self):
        tool = MemoryQueryTool()
        mock_agent = MagicMock()
        mock_agent.build_context.return_value = "context"
        tool.set_memory_agent(mock_agent)

        tool.execute({"task": "recall past events"})
        mock_agent.build_context.assert_called_once_with("recall past events")


class TestToolRegistry:
    def test_base_tools_loaded(self):
        registry = ToolRegistry()
        tools = registry.list_tools()
        assert "perception" in tools
        assert "memory_query" in tools

    def test_get_tool(self):
        registry = ToolRegistry()
        tool = registry.get("perception")
        assert tool is not None
        assert isinstance(tool, PerceptionTool)

    def test_get_nonexistent_tool(self):
        registry = ToolRegistry()
        assert registry.get("nonexistent") is None

    def test_get_descriptions(self):
        registry = ToolRegistry()
        descs = registry.get_descriptions()
        assert "perception" in descs
        assert "memory_query" in descs

    def test_personalized_tools_empty_list(self):
        registry = ToolRegistry(npc_tool_names=[])
        # Still has base tools
        assert "perception" in registry.list_tools()

    def test_unknown_personalized_tool_ignored(self):
        registry = ToolRegistry(npc_tool_names=["nonexistent"])
        assert "nonexistent" not in registry.list_tools()
        assert "perception" in registry.list_tools()

"""Tool registry with base + personalized two-tier loading.

Base tools are always available to every NPC.
Personalized tools are loaded per NPC based on their YAML definition.
"""

from __future__ import annotations

from annie.npc.tools.base_tool import BaseTool
from annie.npc.tools.memory_query import MemoryQueryTool
from annie.npc.tools.perception import PerceptionTool

# Mapping of personalized tool names to their classes.
# Extend this dict when adding new personalized tools.
_PERSONALIZED_TOOL_CLASSES: dict[str, type[BaseTool]] = {}


class ToolRegistry:
    """Manages base + personalized tools for an NPC."""

    def __init__(self, npc_tool_names: list[str] | None = None):
        self.tools: dict[str, BaseTool] = {}
        self._register_base_tools()
        if npc_tool_names:
            self._register_personalized_tools(npc_tool_names)

    def _register_base_tools(self) -> None:
        """Register tools available to all NPCs."""
        perception = PerceptionTool()
        memory_query = MemoryQueryTool()
        self.tools[perception.name] = perception
        self.tools[memory_query.name] = memory_query

    def _register_personalized_tools(self, names: list[str]) -> None:
        """Register additional tools by name from the personalized mapping."""
        for name in names:
            cls = _PERSONALIZED_TOOL_CLASSES.get(name)
            if cls is not None:
                tool = cls()
                self.tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        """Get a tool by name."""
        return self.tools.get(name)

    def list_tools(self) -> list[str]:
        """Return all available tool names."""
        return list(self.tools.keys())

    def get_descriptions(self) -> dict[str, str]:
        """Return {name: description} for all tools."""
        return {name: tool.description for name, tool in self.tools.items()}

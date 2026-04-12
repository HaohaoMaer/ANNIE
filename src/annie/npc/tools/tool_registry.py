"""Tool registry — Phase 1 cleanup.

PerceptionTool removed. Phase 3 rewrites this to support merging built-in
ToolDef + AgentContext-injected ToolDef under a unified interface.
"""

from __future__ import annotations

import logging

from annie.npc.tools.base_tool import BaseTool
from annie.npc.tools.memory_query import MemoryQueryTool

logger = logging.getLogger(__name__)

_PERSONALIZED_TOOL_CLASSES: dict[str, type[BaseTool]] = {}


class ToolRegistry:
    """Manages base + personalized tools for an NPC."""

    def __init__(
        self,
        npc_tool_names: list[str] | None = None,
        injected: list[BaseTool] | None = None,
    ):
        self.tools: dict[str, BaseTool] = {}
        self._register_base_tools()
        if npc_tool_names:
            self._register_personalized_tools(npc_tool_names)
        if injected:
            for t in injected:
                if t.name in self.tools:
                    logger.warning(
                        "Tool name conflict for %s: built-in takes precedence", t.name,
                    )
                    continue
                self.tools[t.name] = t

    def _register_base_tools(self) -> None:
        self.tools[MemoryQueryTool().name] = MemoryQueryTool()

    def _register_personalized_tools(self, names: list[str]) -> None:
        for name in names:
            cls = _PERSONALIZED_TOOL_CLASSES.get(name)
            if cls is not None:
                tool = cls()
                self.tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self.tools.get(name)

    def list_tools(self) -> list[str]:
        return list(self.tools.keys())

    def get_descriptions(self) -> dict[str, str]:
        return {name: tool.description for name, tool in self.tools.items()}

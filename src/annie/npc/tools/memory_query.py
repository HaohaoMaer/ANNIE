"""Memory Query Tool - Targeted memory retrieval for the Executor."""

from __future__ import annotations

from typing import TYPE_CHECKING

from annie.npc.tools.base_tool import BaseTool

if TYPE_CHECKING:
    from annie.npc.sub_agents.memory_agent import MemoryAgent


class MemoryQueryTool(BaseTool):
    """Wraps MemoryAgent to allow targeted memory queries.

    The MemoryAgent dependency is injected after construction via
    ``set_memory_agent()`` to avoid circular initialization issues.
    """

    name = "memory_query"
    description = "Queries NPC memory for relevant context about a topic or entity."

    def __init__(self) -> None:
        self._memory_agent: MemoryAgent | None = None

    def set_memory_agent(self, memory_agent: MemoryAgent) -> None:
        """Inject the MemoryAgent dependency after construction."""
        self._memory_agent = memory_agent

    def execute(self, context: dict) -> dict:
        query = context.get("query", context.get("task", ""))
        if not self._memory_agent:
            return {"tool": self.name, "results": "Memory agent not available."}

        results = self._memory_agent.build_context(query)
        return {
            "tool": self.name,
            "query": query,
            "results": results,
        }

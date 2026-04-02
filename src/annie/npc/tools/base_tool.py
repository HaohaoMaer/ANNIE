"""Base tool interface for NPC tool use.

Tools are external interfaces that NPCs use to interact with systems
outside themselves (perception, memory queries, APIs, etc.).
Unlike skills (file-based cognitive capabilities), tools are Python
classes registered programmatically.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseTool(ABC):
    """Abstract base class for all NPC tools."""

    name: str
    description: str

    @abstractmethod
    def execute(self, context: dict) -> dict:
        """Execute the tool with the given context.

        Args:
            context: Dict with at least 'task' and 'npc_name' keys.

        Returns:
            A result dict with tool-specific output.
        """

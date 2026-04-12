"""Tool Agent - Selects and executes tools from the tool registry."""

from __future__ import annotations

import logging
from typing import Any

from annie.npc.tools.tool_registry import ToolRegistry
from annie.npc.tracing import EventType

logger = logging.getLogger(__name__)

# Common stop words filtered out during keyword matching
_STOP_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "and",
        "but",
        "or",
        "nor",
        "not",
        "so",
        "yet",
        "both",
        "either",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "i",
        "you",
        "he",
        "she",
        "we",
        "they",
        "me",
        "him",
        "her",
        "us",
        "them",
        "my",
        "your",
    }
)


def _meaningful_words(text: str) -> set[str]:
    """Extract meaningful (non-stop) words from text, stripping punctuation."""
    import re

    words = re.findall(r"[a-z]+", text.lower())
    return {w for w in words if w not in _STOP_WORDS and len(w) > 2}


class ToolAgent:
    """Selects and executes tools from the tool registry."""

    def __init__(self, tool_registry: ToolRegistry):
        self.tool_registry = tool_registry

    def select_tool(self, task_description: str) -> str | None:
        """Return the name of the best-matching tool, or None."""
        descs = self.tool_registry.get_descriptions()
        if not descs:
            return None

        task_words = _meaningful_words(task_description)
        if not task_words:
            return None

        best_tool = None
        best_overlap = 0

        for name, desc in descs.items():
            desc_words = _meaningful_words(desc)
            overlap = len(task_words & desc_words)
            if overlap > best_overlap:
                best_overlap = overlap
                best_tool = name

        return best_tool if best_tool and best_overlap >= 2 else None

    def invoke(self, tool_name: str, context: dict) -> dict:
        """Execute the named tool using safe_execute (validates inputs, catches errors)."""
        tool = self.tool_registry.get(tool_name)
        if not tool:
            return {}
        return tool.safe_execute(context)

    def try_tool(
        self,
        task_description: str,
        npc_name: str,
        tracer: Any | None = None,
    ) -> str | None:
        """Select + invoke a tool, returning the result string or None."""
        tool_name = self.select_tool(task_description)
        if not tool_name:
            return None

        if tracer:
            tracer.trace(
                "tool_agent",
                EventType.TOOL_INVOKE,
                output_summary=f"tool={tool_name}",
                metadata={"tool": tool_name},
            )

        result = self.invoke(
            tool_name,
            {"task": task_description, "npc_name": npc_name},
        )
        return str(result) if result else None

"""ToolRegistry — merges built-in ToolDefs with AgentContext-injected ones.

Conflict policy: **built-in wins**. A warning is logged when a world-engine-
injected tool would shadow a built-in, and the injected one is dropped.
"""

from __future__ import annotations

import logging

from annie.npc.tools.base_tool import ToolDef
from annie.npc.tools.builtin import default_builtin_tools

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Unified registry exposed to the Executor / LLM."""

    def __init__(
        self,
        injected: list[ToolDef] | None = None,
        builtins: list[ToolDef] | None = None,
    ) -> None:
        self.tools: dict[str, ToolDef] = {}
        for t in builtins if builtins is not None else default_builtin_tools():
            self.tools[t.name] = t
        if injected:
            for t in injected:
                if t.name in self.tools:
                    logger.warning(
                        "Tool '%s' is built-in; injected version ignored.", t.name,
                    )
                    continue
                self.tools[t.name] = t

    def get(self, name: str) -> ToolDef | None:
        return self.tools.get(name)

    def list_tools(self) -> list[str]:
        return list(self.tools.keys())

    def get_descriptions(self) -> dict[str, str]:
        return {name: tool.description for name, tool in self.tools.items()}

    def filter(self, allowed_names: list[str]) -> "ToolRegistry":
        """Return a new registry restricted to the given tool names."""
        allowed = set(allowed_names)
        sub = ToolRegistry.__new__(ToolRegistry)
        sub.tools = {n: t for n, t in self.tools.items() if n in allowed}
        return sub

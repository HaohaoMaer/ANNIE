"""ToolDispatcher — dispatches native tool_calls to ToolDef instances.

After the Executor rewrite, the LLM picks tools natively via
``llm.bind_tools(...)``. The ToolDispatcher reduces to:

* ``dispatch(tool_call, ctx)`` — look up the ToolDef by name and ``safe_call``
* Micro compression on the output path (truncate >MICRO_MAX_CHARS)
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from typing import TYPE_CHECKING, Any

from annie.npc.tools.base_tool import ToolContext
from annie.npc.tools.tool_registry import ToolRegistry

if TYPE_CHECKING:
    from annie.npc.context import AgentContext

logger = logging.getLogger(__name__)

MICRO_MAX_CHARS: int = 2000
_MICRO_HEAD_FRACTION: float = 0.4


def _micro_compress(text: str, max_chars: int = MICRO_MAX_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    head_len = int(max_chars * _MICRO_HEAD_FRACTION)
    tail_len = max_chars - head_len - len(" [... truncated ...] ")
    return f"{text[:head_len]} [... truncated ...] {text[-tail_len:]}"


class ToolDispatcher:
    """Runtime component that dispatches native tool calls to ToolDefs."""

    def __init__(self, tool_registry: ToolRegistry, runtime: dict[str, Any] | None = None):
        self.tool_registry = tool_registry
        self.runtime = runtime if runtime is not None else {}

    def dispatch(
        self,
        tool_call: dict[str, Any],
        agent_context: "AgentContext",
    ) -> str:
        """Execute one tool_call dict (LangChain-style) and return a string result.

        ``tool_call`` must have ``name`` and ``args`` keys.
        """
        return self.dispatch_result(tool_call, agent_context).content

    def dispatch_result(
        self,
        tool_call: dict[str, Any],
        agent_context: "AgentContext",
    ) -> "ToolDispatchResult":
        """Execute one tool_call and return structured dispatch metadata."""
        name = tool_call.get("name", "")
        args = tool_call.get("args", {}) or {}
        tool = self.tool_registry.get(name)
        if tool is None:
            payload = {"tool": name, "success": False, "error": "tool not found"}
        else:
            payload = tool.safe_call(
                args,
                ToolContext(agent_context=agent_context, runtime=self.runtime),
            )
        rendered = self._render(payload)
        return ToolDispatchResult(
            tool=tool,
            payload=payload,
            rendered=rendered,
            content=_micro_compress(rendered),
        )

    # ---- internals -----------------------------------------------------
    def _render(self, payload: Any) -> str:
        try:
            return json.dumps(payload, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(payload)


@dataclass(frozen=True)
class ToolDispatchResult:
    tool: Any | None
    payload: Any
    rendered: str
    content: str

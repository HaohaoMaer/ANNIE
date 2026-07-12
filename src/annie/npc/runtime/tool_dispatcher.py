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

from annie.npc.core.response import ActionResult, ToolExecutionStatus
from annie.npc.tools.base_tool import ToolContext
from annie.npc.tools.tool_registry import ToolRegistry

if TYPE_CHECKING:
    from annie.npc.core.context import AgentContext

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
        call_id = tool_call.get("id")
        action_results_before = len(self.runtime.get("action_results") or [])
        tool = self.tool_registry.get(name)
        if tool is None:
            payload = {"tool": name, "success": False, "error": "tool not found"}
        else:
            payload = tool.safe_call(
                args,
                ToolContext(agent_context=agent_context, runtime=self.runtime),
            )
            new_statuses = self._record_tool_statuses(
                tool_name=name,
                call_id=str(call_id) if call_id else None,
                action_results_before=action_results_before,
            )
            if new_statuses and isinstance(payload, dict) and payload.get("success") is True:
                payload["result"] = (
                    new_statuses[0].model_dump()
                    if len(new_statuses) == 1
                    else [status.model_dump() for status in new_statuses]
                )
        rendered = self._render(payload)
        return ToolDispatchResult(
            tool=tool,
            payload=payload,
            rendered=rendered,
            content=_micro_compress(rendered),
        )

    def _record_tool_statuses(
        self,
        *,
        tool_name: str,
        call_id: str | None,
        action_results_before: int,
    ) -> list[ToolExecutionStatus]:
        action_results = self.runtime.get("action_results") or []
        new_results = action_results[action_results_before:]
        statuses = self.runtime.setdefault("tool_statuses", [])
        added: list[ToolExecutionStatus] = []
        for result in new_results:
            if isinstance(result, ActionResult):
                status = ToolExecutionStatus.from_action_result(
                    result,
                    tool_name=tool_name,
                    call_id=call_id,
                )
                statuses.append(status)
                added.append(status)
            elif isinstance(result, dict):
                try:
                    parsed = ActionResult(**result)
                except Exception:
                    continue
                status = ToolExecutionStatus.from_action_result(
                    parsed,
                    tool_name=tool_name,
                    call_id=call_id,
                )
                statuses.append(status)
                added.append(status)
        return added

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

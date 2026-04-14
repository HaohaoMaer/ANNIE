"""ContextBudget — Emergency fold when Executor messages approach the model limit.

Owned by the Agent layer; consulted before each LLM call in the tool-use loop.
Trim / Fold live in the WorldEngine; Micro lives in ToolAgent. This module
handles the *Agent-internal* last-resort compression — fold earliest tool
turns into a single ``SystemMessage`` summary, preserving the latest 2 rounds.
"""

from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

logger = logging.getLogger(__name__)

_CHARS_PER_TOKEN: float = 2.5
_DEFAULT_MODEL_CTX_LIMIT = 128_000
_DEFAULT_RESERVE_OUTPUT = 4096
_PRESERVE_LATEST_ROUNDS = 2

_EMERGENCY_SUMMARY_PROMPT = """\
You are compressing an NPC agent's earlier tool-use trace to save context.
Summarise the earlier tool calls and their results into 3-6 short bullet points:
what was looked up, what was learned, and anything relevant to continuing the
current conversation. No preface, no repetition.
"""


def estimate_tokens(messages: list[BaseMessage]) -> int:
    total = 0
    for m in messages:
        content = m.content
        if isinstance(content, list):
            content = "".join(str(p) for p in content)
        total += len(str(content))
    return int(total / _CHARS_PER_TOKEN)


class ContextBudget:
    """Agent-internal emergency compressor over the LLM message list."""

    def __init__(
        self,
        model_ctx_limit: int = _DEFAULT_MODEL_CTX_LIMIT,
        reserve_output: int = _DEFAULT_RESERVE_OUTPUT,
    ) -> None:
        self.limit = int(model_ctx_limit * 0.9)
        self.reserve = reserve_output

    def estimate_tokens(self, messages: list[BaseMessage]) -> int:
        return estimate_tokens(messages)

    def check(
        self,
        messages: list[BaseMessage],
        llm: BaseChatModel,
    ) -> list[BaseMessage]:
        tokens = estimate_tokens(messages)
        if tokens + self.reserve <= self.limit:
            return messages
        logger.info(
            "ContextBudget: Emergency fold triggered (%d tokens > budget)", tokens,
        )
        return self._emergency_fold(messages, llm)

    # ---- internals -----------------------------------------------------
    def _emergency_fold(
        self,
        messages: list[BaseMessage],
        llm: BaseChatModel,
    ) -> list[BaseMessage]:
        system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
        non_system = [m for m in messages if not isinstance(m, SystemMessage)]

        keep_tail = self._tail_rounds(non_system, _PRESERVE_LATEST_ROUNDS)
        head = non_system[: len(non_system) - len(keep_tail)]
        if not head:
            return messages

        head_text = "\n".join(self._format_msg(m) for m in head)
        try:
            resp = llm.invoke([
                SystemMessage(content=_EMERGENCY_SUMMARY_PROMPT),
                HumanMessage(content=head_text),
            ])
            summary = resp.content
            if isinstance(summary, list):
                summary = "".join(str(p) for p in summary)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("ContextBudget: emergency fold LLM failed: %s", exc)
            return messages

        folded = SystemMessage(content=f"[earlier tool work summary]\n{summary}")
        return system_msgs + [folded] + keep_tail

    def _tail_rounds(
        self, messages: list[BaseMessage], rounds: int,
    ) -> list[BaseMessage]:
        """Return the last N Human-initiated rounds (Human → AI → ToolMessages...)."""
        if not messages:
            return []
        starts: list[int] = [
            i for i, m in enumerate(messages) if isinstance(m, HumanMessage)
        ]
        if len(starts) <= rounds:
            return list(messages)
        cut = starts[-rounds]
        return list(messages[cut:])

    def _format_msg(self, m: BaseMessage) -> str:
        role = (
            "user" if isinstance(m, HumanMessage)
            else "assistant" if isinstance(m, AIMessage)
            else "tool" if isinstance(m, ToolMessage)
            else "system"
        )
        content = m.content
        if isinstance(content, list):
            content = "".join(str(p) for p in content)
        return f"[{role}] {content}"

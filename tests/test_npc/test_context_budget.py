"""Tests for ContextBudget (Agent-internal Emergency fold)."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from annie.npc.context_budget import ContextBudget, estimate_tokens


class _StubLLM:
    def __init__(self, reply: str = "- earlier stuff happened") -> None:
        self.reply = reply
        self.calls: list[list[Any]] = []

    def invoke(self, messages, *args, **kwargs):
        self.calls.append(list(messages))
        return AIMessage(content=self.reply)


def test_check_noop_under_budget():
    budget = ContextBudget(model_ctx_limit=100_000, reserve_output=1000)
    msgs = [SystemMessage(content="sys"), HumanMessage(content="hi")]
    out = budget.check(msgs, _StubLLM())
    assert out is msgs


def test_emergency_fold_preserves_system_and_latest_rounds():
    budget = ContextBudget(model_ctx_limit=1000, reserve_output=100)
    filler = "x" * 4000

    msgs = [
        SystemMessage(content="system prompt"),
        HumanMessage(content=f"round-1 {filler}"),
        AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "c1"}]),
        ToolMessage(content=filler, tool_call_id="c1"),
        HumanMessage(content="round-2 middle"),
        AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "c2"}]),
        ToolMessage(content=filler, tool_call_id="c2"),
        HumanMessage(content="round-3 latest-input"),
        AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "c3"}]),
        ToolMessage(content="latest-tool-out", tool_call_id="c3"),
    ]
    llm = _StubLLM(reply="SUMMARY of earlier rounds")
    out = budget.check(msgs, llm)
    assert out is not msgs
    assert out[0].content == "system prompt"
    assert any(
        isinstance(m, SystemMessage) and "earlier tool work summary" in m.content
        for m in out
    )
    # Latest round must survive intact.
    assert any("latest-input" in str(m.content) for m in out)
    assert any("latest-tool-out" in str(m.content) for m in out)


def test_estimate_tokens_is_positive():
    assert estimate_tokens([HumanMessage(content="abc" * 100)]) > 0

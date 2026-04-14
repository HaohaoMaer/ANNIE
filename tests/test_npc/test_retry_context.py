"""Planner <retry_context> rendering on retry."""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessage

from annie.npc.planner import Planner
from annie.npc.state import Task


class _StubLLM:
    def __init__(self):
        self.calls: list[list] = []

    def invoke(self, messages, **_):
        self.calls.append(list(messages))
        return AIMessage(content='{"skip": true, "reason": "ok"}')


def _ctx():
    return SimpleNamespace(
        character_prompt="C",
        world_rules="W",
        situation="S",
        history="old history line",
    )


def test_first_pass_has_no_retry_context():
    llm = _StubLLM()
    planner = Planner(llm)
    planner({
        "agent_context": _ctx(),
        "input_event": "something happens",
        "working_memory": "",
        "retry_count": 0,
        "last_tasks": [],
    })
    user_msg = llm.calls[-1][-1].content
    assert "<retry_context>" not in user_msg


def test_retry_pass_renders_retry_context_with_prev_tasks():
    llm = _StubLLM()
    planner = Planner(llm)
    prev = [Task(description="去厨房找匕首"), Task(description="比对指纹")]
    planner({
        "agent_context": _ctx(),
        "input_event": "something happens",
        "working_memory": "pre-fetched",
        "retry_count": 1,
        "loop_reason": "executor produced no results",
        "last_tasks": prev,
    })
    user_msg = llm.calls[-1][-1].content
    assert "<retry_context>" in user_msg and "</retry_context>" in user_msg
    assert "executor produced no results" in user_msg
    assert "去厨房找匕首" in user_msg
    assert "比对指纹" in user_msg


def test_planner_does_not_render_history_in_system():
    llm = _StubLLM()
    planner = Planner(llm)
    planner({
        "agent_context": _ctx(),
        "input_event": "something",
        "working_memory": "",
        "retry_count": 0,
        "last_tasks": [],
    })
    system_msg = llm.calls[-1][0].content
    assert "old history line" not in system_msg

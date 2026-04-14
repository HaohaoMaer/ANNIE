"""Tests for prompt helpers and Executor system prompt sections."""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import SystemMessage

from annie.npc.executor import EXECUTOR_SYSTEM_TEMPLATE, SKIP_TASK_MARKER, Executor
from annie.npc.prompts import MEMORY_CATEGORIES_BLOCK, render_identity
from annie.npc.state import Task


def test_render_identity_includes_name_and_prompt():
    ctx = SimpleNamespace(npc_id="alice", character_prompt="A curious traveller.")
    out = render_identity(ctx)
    assert out.startswith("<character>")
    assert out.rstrip().endswith("</character>")
    assert "alice" in out
    assert "curious traveller" in out


def test_render_identity_handles_missing_fields():
    ctx = SimpleNamespace()
    out = render_identity(ctx)
    assert "<character>" in out and "</character>" in out


def _make_ctx(**kw):
    defaults = dict(
        npc_id="alice",
        character_prompt="C",
        world_rules="W",
        situation="S",
        history="",
        input_event="someone waves",
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


class _NoopToolAgent:
    class _Reg:
        def list_tools(self):
            return []

        def get(self, _):
            return None

    def __init__(self):
        self.tool_registry = self._Reg()


def test_executor_system_contains_memory_categories_and_working_memory():
    ex = Executor(llm=SimpleNamespace(), tool_agent=_NoopToolAgent())
    msgs = ex._initial_messages(_make_ctx(), Task(description="do something"), working_memory="prior notes")
    sys = msgs[0]
    assert isinstance(sys, SystemMessage)
    content = sys.content
    assert "<memory_categories>" in content and "</memory_categories>" in content
    assert MEMORY_CATEGORIES_BLOCK in content
    assert "<working_memory>" in content
    assert "prior notes" in content


def test_executor_system_no_hardcoded_tool_names():
    ex = Executor(llm=SimpleNamespace(), tool_agent=_NoopToolAgent())
    msgs = ex._initial_messages(_make_ctx(), Task(description="x"), working_memory="")
    content = msgs[0].content
    assert "memory_recall" not in content
    assert "memory_grep" not in content
    assert "inner_monologue" not in content


def test_executor_working_memory_empty_renders_none():
    ex = Executor(llm=SimpleNamespace(), tool_agent=_NoopToolAgent())
    msgs = ex._initial_messages(_make_ctx(), Task(description="x"), working_memory="")
    assert "(none)" in msgs[0].content


def test_skip_marker_trigger_omits_task_section():
    ex = Executor(llm=SimpleNamespace(), tool_agent=_NoopToolAgent())
    msgs = ex._initial_messages(_make_ctx(), Task(description=SKIP_TASK_MARKER), working_memory="")
    trigger = msgs[-1].content
    assert "<input_event>" in trigger
    assert "<task>" not in trigger


def test_non_skip_trigger_includes_task_section():
    ex = Executor(llm=SimpleNamespace(), tool_agent=_NoopToolAgent())
    msgs = ex._initial_messages(_make_ctx(), Task(description="go to kitchen"), working_memory="")
    trigger = msgs[-1].content
    assert "<task>go to kitchen</task>" in trigger


def test_template_has_all_required_sections():
    assert "<character>" not in EXECUTOR_SYSTEM_TEMPLATE.split("{identity}")[0]
    for marker in (
        "{identity}",
        "<world_rules>",
        "<situation>",
        "<memory_categories>",
        "<working_memory>",
        "<available_skills>",
    ):
        assert marker in EXECUTOR_SYSTEM_TEMPLATE

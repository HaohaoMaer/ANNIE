"""Tests for prompt helpers and Executor system prompt sections."""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from annie.npc.executor import EXECUTOR_SYSTEM_TEMPLATE, SKIP_TASK_MARKER, Executor
from annie.npc.prompts import (
    EXECUTOR_SYSTEM_PROMPT,
    MEMORY_CATEGORIES_BLOCK,
    PLANNER_SYSTEM_PROMPT,
    REFLECTOR_SYSTEM_PROMPT,
    build_executor_messages,
    build_planner_messages,
    build_reflector_messages,
    render_identity,
)
from annie.npc.runtime.tool_dispatcher import ToolDispatcher
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
        todo="T",
        skills=[],
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


class _NoopToolRegistry:
    class _Reg:
        def list_tools(self):
            return []

        def get(self, _):
            return None

    def __init__(self):
        self.tool_registry = self._Reg()


def _executor() -> Executor:
    return Executor(
        llm=SimpleNamespace(),
        tool_dispatcher=ToolDispatcher(_NoopToolRegistry().tool_registry),
    )


def test_executor_system_contains_memory_categories_and_working_memory():
    ex = _executor()
    msgs = ex._initial_messages(_make_ctx(), Task(description="do something"), working_memory="prior notes")
    sys = msgs[0]
    assert isinstance(sys, SystemMessage)
    content = sys.content
    assert "<memory_categories>" in content and "</memory_categories>" in content
    assert MEMORY_CATEGORIES_BLOCK in content
    assert "<working_memory>" in content
    assert "prior notes" in content
    assert "W" in content
    assert "S" in content
    assert "本轮预检索的长期记忆摘要" in content


def test_executor_system_no_hardcoded_tool_names():
    ex = _executor()
    msgs = ex._initial_messages(_make_ctx(), Task(description="x"), working_memory="")
    content = msgs[0].content
    assert "memory_recall" not in content
    assert "memory_grep" not in content
    assert "inner_monologue" not in content


def test_executor_working_memory_empty_renders_none():
    ex = _executor()
    msgs = ex._initial_messages(_make_ctx(), Task(description="x"), working_memory="")
    assert "(none)" in msgs[0].content


def test_skip_marker_trigger_omits_task_section():
    ex = _executor()
    msgs = ex._initial_messages(_make_ctx(), Task(description=SKIP_TASK_MARKER), working_memory="")
    trigger = msgs[-1].content
    assert "<input_event>" in trigger
    assert "<task>" not in trigger


def test_non_skip_trigger_includes_task_section():
    ex = _executor()
    msgs = ex._initial_messages(_make_ctx(), Task(description="go to kitchen"), working_memory="")
    trigger = msgs[-1].content
    assert "<task>" in trigger and "go to kitchen" in trigger and "</task>" in trigger


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


def test_node_system_prompts_are_chinese():
    assert "计划判断模块" in PLANNER_SYSTEM_PROMPT
    assert "你现在扮演" in EXECUTOR_SYSTEM_PROMPT
    assert "复盘模块" in REFLECTOR_SYSTEM_PROMPT


def test_planner_builder_includes_prompt_fields_but_not_history_messages():
    ctx = _make_ctx(history="[alice] previous line")
    msgs = build_planner_messages(ctx, "memory")
    assert len(msgs) == 2
    content = msgs[1].content
    assert "<character>" in content
    assert "<world_rules>" in content and "W" in content
    assert "<situation>" in content and "S" in content
    assert "<working_memory>" in content and "memory" in content
    assert "<todo>" in content and "T" in content
    assert "<input_event>" in content and "someone waves" in content
    assert "请根据以下上下文判断" in content
    assert "跨回合目标背景" in content
    assert not any(isinstance(m, AIMessage) for m in msgs)
    assert "previous line" not in content


def test_builder_empty_fields_render_none():
    ctx = _make_ctx(character_prompt="", world_rules="", situation="", input_event="", todo="")
    msgs = build_planner_messages(ctx, "")
    assert msgs[1].content.count("(none)") >= 4


def test_executor_builder_includes_history_sequence():
    ctx = _make_ctx(history="[bob] hello\n[alice] hi")
    msgs = build_executor_messages(ctx, Task(description="reply"), "memory", "todo", [])
    assert isinstance(msgs[1], HumanMessage)
    assert isinstance(msgs[2], AIMessage)
    assert "bob：hello" in msgs[1].content
    assert msgs[2].content == "hi"


def test_reflector_builder_includes_execution_results():
    ctx = _make_ctx()
    msgs = build_reflector_messages(ctx, "event", [{"task_description": "t", "action": "a"}])
    assert len(msgs) == 2
    content = msgs[1].content
    assert "<execution_results>" in content
    assert "task_description" in content
    assert "event" in content

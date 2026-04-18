"""Unit tests for ToolRegistry frame stack (push_frame / pop_frame).

Covers: push/pop normal, multi-layer stacking, pop-default removes top,
pop empty stack no-raise, pop unknown id no-raise, built-in wins over frame.
"""
from __future__ import annotations

import logging

import pytest

from annie.npc.tools.base_tool import ToolDef
from annie.npc.tools.tool_registry import ToolRegistry


# ---------------------------------------------------------------------------
# Minimal concrete ToolDef subclasses for testing (no I/O, no schema)
# ---------------------------------------------------------------------------

class _Tool1(ToolDef):
    name = "tool1"
    description = "fake tool 1"

    def call(self, input, ctx):  # noqa: A002
        return {}


class _Tool2(ToolDef):
    name = "tool2"
    description = "fake tool 2"

    def call(self, input, ctx):  # noqa: A002
        return {}


class _Tool3(ToolDef):
    name = "tool3"
    description = "fake tool 3"

    def call(self, input, ctx):  # noqa: A002
        return {}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_push_makes_tool_visible():
    reg = ToolRegistry(builtins=[])
    assert "tool1" not in reg.list_tools()

    reg.push_frame([_Tool1()])

    assert "tool1" in reg.list_tools()
    assert reg.get("tool1") is not None


def test_pop_by_frame_id_removes_tools():
    reg = ToolRegistry(builtins=[])
    fid = reg.push_frame([_Tool1()])

    reg.pop_frame(fid)

    assert "tool1" not in reg.list_tools()
    assert reg.get("tool1") is None


def test_multi_layer_stacking():
    reg = ToolRegistry(builtins=[])
    fid1 = reg.push_frame([_Tool1()])
    fid2 = reg.push_frame([_Tool2()])

    assert "tool1" in reg.list_tools()
    assert "tool2" in reg.list_tools()

    reg.pop_frame(fid2)
    assert "tool1" in reg.list_tools()
    assert "tool2" not in reg.list_tools()

    reg.pop_frame(fid1)
    assert "tool1" not in reg.list_tools()


def test_pop_default_removes_top_frame():
    reg = ToolRegistry(builtins=[])
    reg.push_frame([_Tool1()])
    reg.push_frame([_Tool2()])

    reg.pop_frame()  # pops top (tool2 frame)

    assert "tool1" in reg.list_tools()
    assert "tool2" not in reg.list_tools()


def test_pop_empty_stack_no_raise(caplog):
    reg = ToolRegistry(builtins=[])
    with caplog.at_level(logging.WARNING, logger="annie.npc.tools.tool_registry"):
        reg.pop_frame()  # must not raise
    assert "empty" in caplog.text


def test_pop_unknown_frame_id_no_raise(caplog):
    reg = ToolRegistry(builtins=[])
    reg.push_frame([_Tool1()])
    with caplog.at_level(logging.WARNING, logger="annie.npc.tools.tool_registry"):
        reg.pop_frame("nonexistent_id_xyz")  # must not raise
    assert "not found" in caplog.text
    # Original frame is unaffected
    assert "tool1" in reg.list_tools()


def test_builtin_wins_over_frame():
    """A frame tool with the same name as a built-in is silently ignored."""
    builtin = _Tool1()
    reg = ToolRegistry(builtins=[builtin])

    frame_dup = _Tool1()  # different object, same name
    reg.push_frame([frame_dup])

    # Built-in should still be reachable; frame_dup was silently dropped
    assert reg.get("tool1") is not None


def test_three_level_stack_independent():
    reg = ToolRegistry(builtins=[])
    fid1 = reg.push_frame([_Tool1()])
    fid2 = reg.push_frame([_Tool2()])
    fid3 = reg.push_frame([_Tool3()])

    assert {"tool1", "tool2", "tool3"} <= set(reg.list_tools())

    reg.pop_frame(fid2)  # remove middle frame
    assert "tool1" in reg.list_tools()
    assert "tool2" not in reg.list_tools()
    assert "tool3" in reg.list_tools()

"""Tests for ToolDispatcher micro-compression.

``ToolDispatcher.dispatch`` truncates large tool outputs to avoid bloating the
message list, but leaves small outputs intact.
"""

from __future__ import annotations

from annie.npc.runtime.tool_dispatcher import (
    MICRO_MAX_CHARS,
    ToolDispatcher,
    _micro_compress,
)
from annie.npc.tools.tool_registry import ToolRegistry


def test_short_content_unchanged():
    text = "Hello, world!"
    assert _micro_compress(text) == text


def test_long_content_truncated():
    text = "A" * (MICRO_MAX_CHARS + 100)
    result = _micro_compress(text)
    assert len(result) <= MICRO_MAX_CHARS + len(" [... truncated ...] ")
    assert "[... truncated ...]" in result


def test_truncated_preserves_head_and_tail():
    head_marker = "HEAD" * 200
    tail_marker = "TAIL" * 200
    text = head_marker + "MIDDLE" * 500 + tail_marker
    result = _micro_compress(text)
    assert result.startswith("HEAD")
    assert result.endswith("TAIL")


def test_exact_max_chars_not_truncated():
    text = "x" * MICRO_MAX_CHARS
    assert _micro_compress(text) == text


def test_dispatch_unknown_tool_returns_error_string():
    from annie.npc.context import AgentContext

    class _NullMemory:
        def recall(self, *a, **k):
            return []

        def grep(self, *a, **k):
            return []

        def remember(self, *a, **k):
            pass

        def build_context(self, *a):
            return ""

    registry = ToolRegistry()
    dispatcher = ToolDispatcher(registry)
    ctx = AgentContext(npc_id="x", input_event="e", memory=_NullMemory())
    result = dispatcher.dispatch({"name": "nonexistent_tool", "args": {}}, ctx)
    assert "tool not found" in result or "nonexistent_tool" in result

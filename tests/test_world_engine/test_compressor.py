"""Tests for Compressor (cursor-driven fold policy)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from annie.npc.memory.interface import MEMORY_CATEGORY_IMPRESSION, MemoryRecord
from annie.world_engine.compressor import Compressor
from annie.world_engine.history import HistoryStore


class _StubLLM:
    """Minimal BaseChatModel-duck that returns a canned summary."""

    def __init__(self, reply: str = "Alice and the player discussed the poison; tone was guarded.") -> None:
        self.reply = reply
        self.calls: list[list[Any]] = []

    def invoke(self, messages, *args, **kwargs):
        self.calls.append(list(messages))
        return AIMessage(content=self.reply)


class _FakeMemory:
    def __init__(self) -> None:
        self.stored: list[tuple[str, str, dict]] = []

    def recall(self, query, categories=None, k=5):
        return []

    def remember(self, content, category="semantic", metadata=None):
        self.stored.append((content, category, dict(metadata or {})))

    def build_context(self, query):
        return ""


@pytest.fixture
def store(tmp_path: Path) -> HistoryStore:
    return HistoryStore("alice", tmp_path / "alice.jsonl")


def _fill(store: HistoryStore, n: int, content_len: int = 200) -> None:
    for i in range(n):
        store.append(
            "alice" if i % 2 == 0 else "player",
            f"turn-{i}: " + ("x" * content_len),
        )


# ---------------------------------------------------------------------------
# Basic behaviour
# ---------------------------------------------------------------------------

def test_maybe_fold_no_op_below_threshold(store: HistoryStore) -> None:
    _fill(store, 2, content_len=50)
    mem = _FakeMemory()
    comp = Compressor(store, mem, _StubLLM(), fold_threshold=10_000)
    assert comp.maybe_fold() is False
    assert mem.stored == []


def test_fold_triggers_above_threshold_and_writes_impression(store: HistoryStore) -> None:
    _fill(store, 10, content_len=400)
    mem = _FakeMemory()
    llm = _StubLLM(reply="Summary: alice and player talked.")
    comp = Compressor(store, mem, llm, fold_threshold=500, target_fold_tokens=600)

    result = comp.maybe_fold(scene="scene-1")
    assert result is True

    # Impression memory was written
    assert len(mem.stored) == 1
    content, category, meta = mem.stored[0]
    assert category == MEMORY_CATEGORY_IMPRESSION
    assert meta["source"] == "fold"
    assert meta["scene"] == "scene-1"
    assert content == "Summary: alice and player talked."

    # JSONL is NOT modified — all original entries still there
    all_entries = store.read_all()
    assert len(all_entries) == 10
    assert not any(e.is_folded for e in all_entries)

    # Cursor advanced
    cursor = store.last_folded_turn_id()
    assert cursor > 0


def test_fold_does_not_modify_jsonl(store: HistoryStore) -> None:
    """JSONL must be identical before and after fold."""
    _fill(store, 6, content_len=400)
    ids_before = [e.turn_id for e in store.read_all()]

    mem = _FakeMemory()
    comp = Compressor(store, mem, _StubLLM(), fold_threshold=100, target_fold_tokens=200)
    comp.force_fold()

    ids_after = [e.turn_id for e in store.read_all()]
    assert ids_before == ids_after, "JSONL must not be modified by folding"


# ---------------------------------------------------------------------------
# Cursor advancement: no double-fold of same turns
# ---------------------------------------------------------------------------

def test_cursor_advances_so_second_fold_skips_first_slice(store: HistoryStore) -> None:
    """After the first fold, a second fold must cover different turns."""
    _fill(store, 10, content_len=400)
    mem = _FakeMemory()
    # Use a small threshold so multiple folds can trigger
    comp = Compressor(store, mem, _StubLLM(), fold_threshold=100, target_fold_tokens=600)

    first_result = comp.force_fold()
    assert first_result is True
    cursor_after_first = store.last_folded_turn_id()

    second_result = comp.force_fold()
    assert second_result is True
    cursor_after_second = store.last_folded_turn_id()

    assert cursor_after_second > cursor_after_first, (
        "Second fold must advance cursor past first fold's position"
    )
    # Two impression entries, each for a different slice
    assert len(mem.stored) == 2


def test_no_double_fold_when_only_two_entries_left(store: HistoryStore) -> None:
    """force_fold refuses when < 2 unfolded candidates remain."""
    store.append("alice", "turn A")
    mem = _FakeMemory()
    comp = Compressor(store, mem, _StubLLM(), fold_threshold=0, target_fold_tokens=10)

    # Only 1 entry — fold must decline
    result = comp.force_fold()
    assert result is False
    assert mem.stored == []


# ---------------------------------------------------------------------------
# prune + cursor interaction
# ---------------------------------------------------------------------------

def test_prune_after_fold_cursor_still_valid(store: HistoryStore) -> None:
    """prune does not reset the cursor; next fold picks up from oldest remaining."""
    _fill(store, 10, content_len=400)
    mem = _FakeMemory()
    comp = Compressor(store, mem, _StubLLM(), fold_threshold=100, target_fold_tokens=600)

    comp.force_fold()
    cursor_before = store.last_folded_turn_id()

    # Prune the first 5 entries (turn_ids 1–5)
    deleted = store.prune(before_turn_id=6)
    assert deleted > 0

    # Cursor unchanged after prune
    assert store.last_folded_turn_id() == cursor_before

    # A subsequent fold still works (picks from whatever remains past cursor)
    result = comp.force_fold()
    # May or may not fold depending on remaining content — just must not raise
    assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Prune primitive
# ---------------------------------------------------------------------------

def test_prune_keep_last(store: HistoryStore) -> None:
    _fill(store, 8)
    n = store.prune(keep_last=3)
    assert n == 5
    assert len(store.read_all()) == 3


def test_prune_before_turn_id(store: HistoryStore) -> None:
    _fill(store, 6)
    ids = [e.turn_id for e in store.read_all()]
    pivot = ids[3]  # delete first 3
    deleted = store.prune(before_turn_id=pivot)
    assert deleted == 3
    remaining = store.read_all()
    assert all(e.turn_id >= pivot for e in remaining)


def test_prune_mutual_exclusion(store: HistoryStore) -> None:
    _fill(store, 4)
    with pytest.raises(ValueError, match="exactly one"):
        store.prune(keep_last=2, before_turn_id=3)

    with pytest.raises(ValueError, match="exactly one"):
        store.prune()

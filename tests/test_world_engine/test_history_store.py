"""Tests for HistoryStore (JSONL-backed rolling history)."""

from __future__ import annotations

from pathlib import Path

import pytest

from annie.world_engine.history import HistoryEntry, HistoryStore


@pytest.fixture
def store(tmp_path: Path) -> HistoryStore:
    return HistoryStore("alice", tmp_path / "alice.jsonl")


def test_append_and_read_last(store: HistoryStore) -> None:
    e1 = store.append("alice", "hello")
    e2 = store.append("player", "hi")
    e3 = store.append("alice", "what brings you here")

    assert e1.turn_id == 1
    assert e2.turn_id == 2
    assert e3.turn_id == 3

    last2 = store.read_last(2)
    assert [e.content for e in last2] == ["hi", "what brings you here"]

    assert len(store.read_all()) == 3


def test_read_last_zero_and_negative(store: HistoryStore) -> None:
    store.append("a", "x")
    assert store.read_last(0) == []
    assert store.read_last(-1) == []


def test_estimate_tokens_monotonic(store: HistoryStore) -> None:
    t0 = store.estimate_tokens()
    store.append("a", "x" * 100)
    t1 = store.estimate_tokens()
    assert t1 > t0


def test_replace_collapses_turns(store: HistoryStore) -> None:
    store.append("a", "1")
    store.append("b", "2")
    store.append("a", "3")
    store.append("b", "4")

    folded = HistoryEntry(
        turn_id=999,
        timestamp="2026-04-13T00:00:00+00:00",
        speaker="system",
        content="summary of 1-3",
        is_folded=True,
        folded_from=[1, 2, 3],
    )
    store.replace([1, 2, 3], folded)

    all_entries = store.read_all()
    assert len(all_entries) == 2
    assert all_entries[0].is_folded is True
    assert all_entries[0].folded_from == [1, 2, 3]
    assert all_entries[1].content == "4"


def test_replace_empty_is_noop(store: HistoryStore) -> None:
    store.append("a", "x")
    store.replace([], HistoryEntry(
        turn_id=99, timestamp="t", speaker="s", content="never",
    ))
    assert [e.content for e in store.read_all()] == ["x"]


def test_unfolded_entries_filter(store: HistoryStore) -> None:
    store.append("a", "keep1")
    store.append("a", "keep2")
    folded = HistoryEntry(
        turn_id=10, timestamp="t", speaker="sys", content="folded",
        is_folded=True, folded_from=[1],
    )
    store.replace([1], folded)
    unfolded = store.unfolded_entries()
    assert [e.content for e in unfolded] == ["keep2"]


def test_corrupt_line_is_skipped(tmp_path: Path) -> None:
    p = tmp_path / "bad.jsonl"
    p.write_text(
        '{"turn_id": 1, "timestamp": "t", "speaker": "a", "content": "ok"}\n'
        "not-valid-json\n"
        '{"turn_id": 2, "timestamp": "t", "speaker": "b", "content": "ok2"}\n',
        encoding="utf-8",
    )
    store = HistoryStore("alice", p)
    entries = store.read_all()
    assert [e.content for e in entries] == ["ok", "ok2"]


def test_persistence_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "persist.jsonl"
    s1 = HistoryStore("alice", path)
    s1.append("a", "x")
    s2 = HistoryStore("alice", path)
    assert [e.content for e in s2.read_all()] == ["x"]
    s2.append("b", "y")
    assert [e.content for e in s1.read_all()] == ["x", "y"]

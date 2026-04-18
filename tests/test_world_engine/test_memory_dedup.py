"""Unit tests for DefaultMemoryInterface dedup behaviour.

Covers:
* same (category, content) written twice → only one record recalled
* different ``person`` metadata on the same reflection content → two records
* impression / todo are NOT deduped (each write creates a new record)
"""

from __future__ import annotations

import chromadb
import pytest

from annie.world_engine.memory import DefaultMemoryInterface


@pytest.fixture
def mem(tmp_path):
    client = chromadb.PersistentClient(path=str(tmp_path / "vs"))
    return DefaultMemoryInterface("test_npc", chroma_client=client)


# ---------------------------------------------------------------------------
# semantic dedup
# ---------------------------------------------------------------------------

def test_same_semantic_written_twice_yields_one_recall(mem):
    mem.remember("Alice likes tea", category="semantic")
    mem.remember("Alice likes tea", category="semantic")

    records = mem.recall("Alice likes tea", categories=["semantic"], k=10)
    semantic_hits = [r for r in records if r.content == "Alice likes tea"]
    assert len(semantic_hits) == 1, (
        f"Expected 1 semantic record, got {len(semantic_hits)}"
    )


def test_same_reflection_written_twice_yields_one_recall(mem):
    mem.remember("The situation is tense", category="reflection")
    mem.remember("The situation is tense", category="reflection")

    records = mem.recall("situation tense", categories=["reflection"], k=10)
    hits = [r for r in records if r.content == "The situation is tense"]
    assert len(hits) == 1


# ---------------------------------------------------------------------------
# person-aware dedup: same text, different person → distinct records
# ---------------------------------------------------------------------------

def test_reflection_different_person_keeps_two_records(mem):
    mem.remember(
        "seems untrustworthy",
        category="reflection",
        metadata={"person": "Bob"},
    )
    mem.remember(
        "seems untrustworthy",
        category="reflection",
        metadata={"person": "Carol"},
    )

    bob_hits = mem.grep("seems untrustworthy", category="reflection",
                        metadata_filters={"person": "Bob"})
    carol_hits = mem.grep("seems untrustworthy", category="reflection",
                          metadata_filters={"person": "Carol"})
    assert len(bob_hits) == 1
    assert len(carol_hits) == 1


# ---------------------------------------------------------------------------
# impression and todo are NOT deduped
# ---------------------------------------------------------------------------

def test_impression_two_writes_not_deduped(mem):
    mem.remember("A long time ago things happened", category="impression")
    mem.remember("A long time ago things happened", category="impression")

    hits = mem.grep("A long time ago", category="impression")
    assert len(hits) == 2, (
        f"impression should NOT be deduped; expected 2, got {len(hits)}"
    )


def test_todo_two_writes_not_deduped(mem):
    mem.remember(
        "visit the library",
        category="todo",
        metadata={"status": "open", "todo_id": "aaaa1111"},
    )
    mem.remember(
        "visit the library",
        category="todo",
        metadata={"status": "open", "todo_id": "bbbb2222"},
    )

    hits = mem.grep("visit the library", category="todo")
    assert len(hits) == 2

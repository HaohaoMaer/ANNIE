"""Tests for MemoryInterface.grep / MemoryStore.grep_entries."""

from __future__ import annotations

import chromadb
import pytest

from annie.world_engine.memory import DefaultMemoryInterface


@pytest.fixture
def mem(tmp_path):
    client = chromadb.PersistentClient(path=str(tmp_path / "vs"))
    return DefaultMemoryInterface("npc1", chroma_client=client)


def test_substring_hit(mem):
    mem.remember("李四昨晚在餐车", category="semantic")
    mem.remember("张三喝了咖啡", category="semantic")
    hits = mem.grep("李四")
    assert len(hits) == 1
    assert "李四" in hits[0].content
    assert hits[0].relevance_score == 1.0


def test_category_filter(mem):
    mem.remember("李四昨晚在餐车", category="reflection")
    mem.remember("李四是嫌疑人", category="semantic")
    hits = mem.grep("李四", category="semantic")
    assert len(hits) == 1
    assert hits[0].category == "semantic"


def test_metadata_filters(mem):
    mem.remember("匕首有指纹", category="semantic", metadata={"scene": "S1"})
    mem.remember("匕首丢失了", category="semantic", metadata={"scene": "S2"})
    hits = mem.grep("匕首", metadata_filters={"scene": "S1"})
    assert len(hits) == 1
    assert "指纹" in hits[0].content


def test_case_insensitive(mem):
    mem.remember("Alice met BOB in the tavern.", category="semantic")
    assert len(mem.grep("alice")) == 1
    assert len(mem.grep("bob")) == 1
    assert len(mem.grep("ALICE")) == 1


def test_k_upper_bound(mem):
    for i in range(5):
        mem.remember(f"李四 event {i}", category="semantic")
    hits = mem.grep("李四", k=3)
    assert len(hits) == 3


def test_empty_pattern_returns_empty(mem):
    mem.remember("any content", category="semantic")
    assert mem.grep("") == []

"""Tests for Episodic Memory."""

import uuid
from datetime import UTC, datetime

import chromadb
import pytest

from annie.npc.memory.episodic import EpisodicEvent, EpisodicMemory


@pytest.fixture
def episodic_memory():
    client = chromadb.EphemeralClient()
    # Unique collection per test to avoid cross-test pollution
    col_name = f"test_episodic_{uuid.uuid4().hex[:8]}"
    return EpisodicMemory("test_npc", client=client, collection_name=col_name)


class TestEpisodicMemory:
    def test_store_returns_id(self, episodic_memory):
        doc_id = episodic_memory.store("Met a stranger at the gate.")
        assert isinstance(doc_id, str)
        assert len(doc_id) > 0

    def test_store_and_retrieve(self, episodic_memory):
        episodic_memory.store("Met a stranger at the village gate.")
        episodic_memory.store("Traded goods with the merchant.")
        episodic_memory.store("Watched the sunset from the hilltop.")

        results = episodic_memory.retrieve("Who did I meet?", k=2)
        assert len(results) == 2
        assert all(isinstance(e, EpisodicEvent) for e in results)
        # The stranger event should be most relevant
        assert any("stranger" in e.content for e in results)

    def test_retrieve_with_timestamp(self, episodic_memory):
        ts = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)
        episodic_memory.store("Morning training session.", timestamp=ts)

        results = episodic_memory.retrieve("training")
        assert len(results) == 1
        assert results[0].timestamp.year == 2026

    def test_retrieve_empty_collection(self, episodic_memory):
        results = episodic_memory.retrieve("anything")
        assert results == []

    def test_retrieve_relevance_score(self, episodic_memory):
        episodic_memory.store("The blacksmith forged a new sword.")
        episodic_memory.store("The baker made fresh bread.")

        results = episodic_memory.retrieve("sword forging", k=2)
        assert len(results) == 2
        # First result should have higher relevance
        assert results[0].relevance_score >= results[1].relevance_score

    def test_get_recent(self, episodic_memory):
        ts1 = datetime(2026, 1, 1, tzinfo=UTC)
        ts2 = datetime(2026, 1, 2, tzinfo=UTC)
        ts3 = datetime(2026, 1, 3, tzinfo=UTC)
        episodic_memory.store("Event one", timestamp=ts1)
        episodic_memory.store("Event two", timestamp=ts2)
        episodic_memory.store("Event three", timestamp=ts3)

        recent = episodic_memory.get_recent(n=2)
        assert len(recent) == 2
        # Should be in reverse chronological order
        assert recent[0].timestamp >= recent[1].timestamp

    def test_get_recent_empty(self, episodic_memory):
        results = episodic_memory.get_recent()
        assert results == []

    def test_store_with_metadata(self, episodic_memory):
        episodic_memory.store(
            "Found a hidden passage.",
            metadata={"location": "castle", "importance": "high"},
        )
        results = episodic_memory.retrieve("hidden passage")
        assert len(results) == 1
        assert results[0].metadata.get("location") == "castle"

    def test_k_larger_than_collection(self, episodic_memory):
        episodic_memory.store("Only event.")
        results = episodic_memory.retrieve("event", k=10)
        assert len(results) == 1

"""Tests for Semantic Memory."""

import uuid

import chromadb
import pytest

from annie.npc.memory.semantic import SemanticFact, SemanticMemory


@pytest.fixture
def semantic_memory():
    client = chromadb.EphemeralClient()
    col_name = f"test_semantic_{uuid.uuid4().hex[:8]}"
    return SemanticMemory("test_npc", client=client, collection_name=col_name)


class TestSemanticMemory:
    def test_store_returns_id(self, semantic_memory):
        doc_id = semantic_memory.store("The village has 200 inhabitants.")
        assert isinstance(doc_id, str)
        assert len(doc_id) > 0

    def test_store_and_retrieve(self, semantic_memory):
        semantic_memory.store("The village has 200 inhabitants.", category="geography")
        semantic_memory.store("Iron is mined in the northern mountains.", category="geography")
        semantic_memory.store("The king declared a new tax law.", category="politics")

        results = semantic_memory.retrieve("population of the village", k=2)
        assert len(results) == 2
        assert all(isinstance(f, SemanticFact) for f in results)
        assert any("200 inhabitants" in f.content for f in results)

    def test_retrieve_empty(self, semantic_memory):
        results = semantic_memory.retrieve("anything")
        assert results == []

    def test_retrieve_relevance_score(self, semantic_memory):
        semantic_memory.store("Wolves roam the northern forest.")
        semantic_memory.store("The baker opens at dawn.")

        results = semantic_memory.retrieve("dangerous animals in the forest", k=2)
        assert results[0].relevance_score >= results[1].relevance_score

    def test_get_by_category(self, semantic_memory):
        semantic_memory.store("The river flows south.", category="geography")
        semantic_memory.store("The mayor is corrupt.", category="politics")
        semantic_memory.store("Mountains are to the north.", category="geography")

        geo_facts = semantic_memory.get_by_category("geography")
        assert len(geo_facts) == 2
        assert all(f.category == "geography" for f in geo_facts)

    def test_get_by_category_empty(self, semantic_memory):
        semantic_memory.store("A fact.", category="general")
        results = semantic_memory.get_by_category("nonexistent")
        assert results == []

    def test_store_with_metadata(self, semantic_memory):
        semantic_memory.store(
            "The blacksmith is the strongest in the village.",
            category="people",
            metadata={"source": "observation"},
        )
        results = semantic_memory.retrieve("blacksmith strength")
        assert len(results) == 1
        assert results[0].metadata.get("source") == "observation"

    def test_k_larger_than_collection(self, semantic_memory):
        semantic_memory.store("Only fact.")
        results = semantic_memory.retrieve("fact", k=10)
        assert len(results) == 1

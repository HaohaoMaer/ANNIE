"""Semantic Memory - World knowledge and facts for a single NPC.

Uses ChromaDB as the vector store for similarity-based retrieval.
"""

from __future__ import annotations

import uuid

import chromadb
from pydantic import BaseModel, Field

from annie.npc.memory.episodic import _sanitize_collection_name


class SemanticFact(BaseModel):
    content: str
    category: str = "general"
    metadata: dict = Field(default_factory=dict)
    relevance_score: float = 0.0


class SemanticMemory:
    """Stores and retrieves factual knowledge for an NPC using ChromaDB."""

    def __init__(
        self,
        npc_name: str,
        client: chromadb.ClientAPI | None = None,
        collection_name: str | None = None,
    ):
        self._client = client or chromadb.PersistentClient(path="./data/vector_store")
        name = collection_name or _sanitize_collection_name(f"{npc_name}_semantic")
        self._collection = self._client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )
        self._npc_name = npc_name

    def store(
        self,
        fact: str,
        category: str = "general",
        metadata: dict | None = None,
    ) -> str:
        """Store a semantic fact. Returns the document ID."""
        doc_id = uuid.uuid4().hex[:12]
        meta = {
            **(metadata or {}),
            "category": category,
            "npc_name": self._npc_name,
        }
        self._collection.add(
            documents=[fact],
            ids=[doc_id],
            metadatas=[meta],
        )
        return doc_id

    def retrieve(self, query: str, k: int = 5) -> list[SemanticFact]:
        """Retrieve the most relevant facts by similarity search."""
        count = self._collection.count()
        if count == 0:
            return []
        n = min(k, count)
        results = self._collection.query(query_texts=[query], n_results=n)
        return self._parse_results(results)

    def get_by_category(self, category: str) -> list[SemanticFact]:
        """Retrieve all facts in a given category."""
        results = self._collection.get(
            where={"category": category},
            include=["documents", "metadatas"],
        )
        facts = []
        for doc, meta in zip(results["documents"], results["metadatas"]):
            facts.append(
                SemanticFact(
                    content=doc,
                    category=meta.get("category", "general"),
                    metadata={k: v for k, v in meta.items() if k != "category"},
                )
            )
        return facts

    def _parse_results(self, results: dict) -> list[SemanticFact]:
        facts = []
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        for doc, meta, dist in zip(docs, metas, distances):
            facts.append(
                SemanticFact(
                    content=doc,
                    category=meta.get("category", "general"),
                    metadata={k: v for k, v in meta.items() if k != "category"},
                    relevance_score=1.0 - dist,
                )
            )
        return facts

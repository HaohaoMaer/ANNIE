"""Episodic Memory - Timestamped event storage for a single NPC.

Uses ChromaDB as the vector store for similarity-based retrieval.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

import chromadb
from pydantic import BaseModel, Field

from annie.npc.memory.chroma_lock import ChromaWriteGuard


def _sanitize_collection_name(name: str) -> str:
    """Sanitize a string for use as a ChromaDB collection name."""
    sanitized = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
    sanitized = sanitized.strip("_.-")
    if len(sanitized) < 3:
        sanitized = sanitized + "___"[: 3 - len(sanitized)]
    return sanitized[:512]


class EpisodicEvent(BaseModel):
    content: str
    timestamp: datetime
    metadata: dict = Field(default_factory=dict)
    relevance_score: float = 0.0


class EpisodicMemory:
    """Stores and retrieves timestamped events for an NPC using ChromaDB."""

    MAX_EPISODES: int = 200  # Auto-prune when collection exceeds this size
    _PRUNE_RATIO: float = 0.2  # Remove oldest 20% when over limit

    def __init__(
        self,
        npc_name: str,
        client: chromadb.ClientAPI | None = None,
        collection_name: str | None = None,
    ):
        self._client = client or chromadb.PersistentClient(path="./data/vector_store")
        name = collection_name or _sanitize_collection_name(f"{npc_name}_episodic")
        self._collection = self._client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )
        self._npc_name = npc_name

    def store(
        self,
        event: str,
        timestamp: datetime | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Store an episodic event. Returns the document ID.

        Automatically prunes oldest episodes when MAX_EPISODES is exceeded.
        Write is protected by the module-level ChromaDB write lock.
        """
        ts = timestamp or datetime.now(UTC)
        doc_id = uuid.uuid4().hex[:12]
        meta = {
            **(metadata or {}),
            "timestamp": ts.isoformat(),
            "npc_name": self._npc_name,
        }
        with ChromaWriteGuard():
            self._collection.add(
                documents=[event],
                ids=[doc_id],
                metadatas=[meta],
            )
            # Auto-prune if over limit
            if self._collection.count() > self.MAX_EPISODES:
                self._auto_prune()
        return doc_id

    def _auto_prune(self) -> int:
        """Delete the oldest (MAX_EPISODES * _PRUNE_RATIO) episodes. Returns count deleted."""
        all_docs = self._collection.get(include=["metadatas"])
        if not all_docs["ids"]:
            return 0
        # Sort by timestamp ascending (oldest first)
        id_ts_pairs = []
        for doc_id, meta in zip(all_docs["ids"], all_docs["metadatas"]):
            ts_str = meta.get("timestamp", "2000-01-01T00:00:00+00:00")
            try:
                ts = datetime.fromisoformat(ts_str)
            except (ValueError, TypeError):
                ts = datetime.min.replace(tzinfo=UTC)
            id_ts_pairs.append((doc_id, ts))
        id_ts_pairs.sort(key=lambda x: x[1])  # oldest first
        n_delete = max(1, int(len(id_ts_pairs) * self._PRUNE_RATIO))
        ids_to_delete = [pair[0] for pair in id_ts_pairs[:n_delete]]
        self._collection.delete(ids=ids_to_delete)
        return len(ids_to_delete)

    def prune_before(self, cutoff: datetime) -> int:
        """Delete all episodic events older than cutoff. Returns count deleted."""
        all_docs = self._collection.get(include=["metadatas"])
        if not all_docs["ids"]:
            return 0
        ids_to_delete = []
        for doc_id, meta in zip(all_docs["ids"], all_docs["metadatas"]):
            ts_str = meta.get("timestamp", "2000-01-01T00:00:00+00:00")
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
            except (ValueError, TypeError):
                ts = datetime.min.replace(tzinfo=UTC)
            if ts < cutoff:
                ids_to_delete.append(doc_id)
        if ids_to_delete:
            with ChromaWriteGuard():
                self._collection.delete(ids=ids_to_delete)
        return len(ids_to_delete)

    def retrieve(self, query: str, k: int = 5) -> list[EpisodicEvent]:
        """Retrieve the most relevant events by similarity search."""
        count = self._collection.count()
        if count == 0:
            return []
        n = min(k, count)
        results = self._collection.query(query_texts=[query], n_results=n)
        return self._parse_results(results)

    def get_recent(self, n: int = 10) -> list[EpisodicEvent]:
        """Retrieve the most recent n events by timestamp."""
        count = self._collection.count()
        if count == 0:
            return []
        limit = min(n, count)
        results = self._collection.get(
            limit=limit,
            include=["documents", "metadatas"],
        )
        events = []
        for doc, meta in zip(results["documents"], results["metadatas"]):
            ts_str = meta.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(ts_str)
            except (ValueError, TypeError):
                ts = datetime.now(UTC)
            events.append(
                EpisodicEvent(
                    content=doc,
                    timestamp=ts,
                    metadata={k: v for k, v in meta.items() if k != "timestamp"},
                )
            )
        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events[:limit]

    def _parse_results(self, results: dict) -> list[EpisodicEvent]:
        events = []
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        for doc, meta, dist in zip(docs, metas, distances):
            ts_str = meta.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(ts_str)
            except (ValueError, TypeError):
                ts = datetime.now(UTC)
            events.append(
                EpisodicEvent(
                    content=doc,
                    timestamp=ts,
                    metadata={k: v for k, v in meta.items() if k != "timestamp"},
                    relevance_score=1.0 - dist,  # cosine distance -> similarity
                )
            )
        return events

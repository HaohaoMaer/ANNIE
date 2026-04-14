"""Unified per-NPC long-term memory store (ChromaDB).

Replaces the former ``EpisodicMemory`` + ``SemanticMemory`` pair with a
single collection per NPC whose entries carry a ``category`` metadata
field (``episodic`` / ``semantic`` / ``reflection`` / ``impression`` /
open string). Category-level filtering is done at query time via
Chroma's ``where={"category": {"$in": [...]}}``.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

import chromadb
from chromadb.api import ClientAPI
from pydantic import BaseModel, Field

from annie.world_engine.chroma_lock import ChromaWriteGuard

DEFAULT_IMPRESSION_WEIGHT: float = 1.2
MAX_ENTRIES: int = 2000
_PRUNE_RATIO: float = 0.1


def _sanitize_collection_name(name: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
    sanitized = sanitized.strip("_.-")
    if len(sanitized) < 3:
        sanitized = sanitized + "___"[: 3 - len(sanitized)]
    return sanitized[:512]


class MemoryEntry(BaseModel):
    """Raw entry retrieved from the store (pre-interface mapping)."""

    content: str
    category: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    relevance_score: float = 0.0


class MemoryStore:
    """Single ChromaDB collection per NPC, category kept in metadata."""

    def __init__(
        self,
        npc_id: str,
        client: ClientAPI | None = None,
        collection_name: str | None = None,
        impression_weight: float = DEFAULT_IMPRESSION_WEIGHT,
    ) -> None:
        self._npc_id = npc_id
        self._client = client or chromadb.PersistentClient(path="./data/vector_store")
        name = collection_name or _sanitize_collection_name(f"npc_memory_{npc_id}")
        self._collection = self._client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )
        self._impression_weight = impression_weight

    # ---- write ---------------------------------------------------------
    def store(
        self,
        content: str,
        category: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        doc_id = uuid.uuid4().hex[:12]
        meta: dict[str, Any] = dict(metadata or {})
        meta["category"] = category
        meta["npc_id"] = self._npc_id
        meta.setdefault("created_at", datetime.now(UTC).isoformat())
        # Chroma metadata only accepts scalar types; coerce defensively.
        meta = {k: _to_scalar(v) for k, v in meta.items()}
        with ChromaWriteGuard():
            self._collection.add(
                documents=[content],
                ids=[doc_id],
                metadatas=[meta],
            )
            if self._collection.count() > MAX_ENTRIES:
                self._auto_prune()
        return doc_id

    def _auto_prune(self) -> int:
        all_docs = self._collection.get(include=["metadatas"])
        if not all_docs["ids"]:
            return 0
        pairs: list[tuple[str, datetime]] = []
        for doc_id, meta in zip(all_docs["ids"], all_docs["metadatas"]):
            ts_str = str(meta.get("created_at", "2000-01-01T00:00:00+00:00"))
            try:
                ts = datetime.fromisoformat(ts_str)
            except (ValueError, TypeError):
                ts = datetime.min.replace(tzinfo=UTC)
            pairs.append((doc_id, ts))
        pairs.sort(key=lambda p: p[1])
        n_delete = max(1, int(len(pairs) * _PRUNE_RATIO))
        self._collection.delete(ids=[p[0] for p in pairs[:n_delete]])
        return n_delete

    # ---- read ----------------------------------------------------------
    def retrieve(
        self,
        query: str,
        categories: list[str] | None = None,
        k: int = 5,
    ) -> list[MemoryEntry]:
        count = self._collection.count()
        if count == 0:
            return []
        where: dict[str, Any] | None = None
        if categories:
            where = {"category": {"$in": list(categories)}} if len(categories) > 1 else {"category": categories[0]}
        n = min(k, count)
        results = self._collection.query(
            query_texts=[query],
            n_results=n,
            where=where,
        )
        return self._parse_results(results)

    def get_by_category(self, category: str) -> list[MemoryEntry]:
        results = self._collection.get(
            where={"category": category},
            include=["documents", "metadatas"],
        )
        out: list[MemoryEntry] = []
        for doc, meta in zip(results["documents"], results["metadatas"]):
            out.append(
                MemoryEntry(
                    content=doc,
                    category=str(meta.get("category", "semantic")),
                    metadata={k: v for k, v in meta.items() if k != "category"},
                )
            )
        return out

    def _parse_results(self, results: dict) -> list[MemoryEntry]:
        out: list[MemoryEntry] = []
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        for doc, meta, dist in zip(docs, metas, distances):
            category = str(meta.get("category", "semantic"))
            score = 1.0 - float(dist)
            if category == "impression":
                score *= self._impression_weight
            out.append(
                MemoryEntry(
                    content=doc,
                    category=category,
                    metadata={k: v for k, v in meta.items() if k != "category"},
                    relevance_score=score,
                )
            )
        out.sort(key=lambda e: e.relevance_score, reverse=True)
        return out


def _to_scalar(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return ",".join(str(v) for v in value)
    return str(value)

"""Default MemoryInterface implementation.

Backed by a single per-NPC ChromaDB collection (``MemoryStore``) whose
entries are tagged with a ``category`` metadata field. Implements the
``MemoryInterface`` protocol the NPC Agent expects.

Write policy
------------
* ``semantic`` / ``reflection``: **upsert** with stable content-hash id
  (``sha1(category|content|person)[:16]``).  Same fact written twice →
  single record (timestamp refreshed).
* All other categories (``impression``, ``todo``, …): ``add`` + uuid.
  Impression summaries cover different time windows so dedup is wrong.
"""

from __future__ import annotations

import hashlib
from typing import Any

import chromadb
from chromadb.api import ClientAPI

from annie.npc.memory.interface import (
    MEMORY_CATEGORY_SEMANTIC,
    MemoryInterface,
    MemoryRecord,
)
from annie.world_engine.store import MemoryStore

# Categories that use upsert + stable id (dedup by content + person).
_DEDUP_CATEGORIES = {"semantic", "reflection"}

_MIN_RELEVANCE = 0.35
_BUILD_CONTEXT_MAX_CHARS = 1500
_BUILD_CONTEXT_K = 8

_CATEGORY_LABELS: dict[str, str] = {
    "episodic": "Recent experiences",
    "semantic": "Known facts",
    "reflection": "Prior reflections",
    "impression": "Impressions",
}


def _dedup_id(category: str, content: str, metadata: dict[str, Any]) -> str:
    """Stable 16-hex id for dedup-eligible categories (semantic, reflection).

    Incorporates ``person`` metadata so that the same observation written
    about two different people is stored as two separate records.
    """
    person = str(metadata.get("person", ""))
    raw = f"{category}|{content}|{person}".encode()
    return hashlib.sha1(raw).hexdigest()[:16]  # noqa: S324 — not a security hash


class DefaultMemoryInterface(MemoryInterface):
    """ChromaDB-backed default MemoryInterface (single-collection, category-tagged)."""

    def __init__(
        self,
        npc_id: str,
        chroma_client: ClientAPI | None = None,
    ) -> None:
        self._npc_id = npc_id
        self._client = chroma_client or chromadb.PersistentClient(path="./data/vector_store")
        self._store = MemoryStore(npc_id, client=self._client)

    # ---- MemoryInterface ----------------------------------------------
    def recall(
        self,
        query: str,
        categories: list[str] | None = None,
        k: int = 5,
    ) -> list[MemoryRecord]:
        entries = self._store.retrieve(query, categories=categories, k=k)
        records: list[MemoryRecord] = []
        for e in entries:
            if e.relevance_score < _MIN_RELEVANCE:
                continue
            records.append(MemoryRecord(
                content=e.content,
                category=e.category,
                metadata=e.metadata,
                relevance_score=e.relevance_score,
            ))
        return records[:k]

    def grep(
        self,
        pattern: str,
        category: str | None = None,
        metadata_filters: dict[str, Any] | None = None,
        k: int = 20,
    ) -> list[MemoryRecord]:
        clauses: list[dict[str, Any]] = []
        if category is not None:
            clauses.append({"category": category})
        if metadata_filters:
            clauses.extend({mk: mv} for mk, mv in metadata_filters.items())
        if not clauses:
            where: dict[str, Any] | None = None
        elif len(clauses) == 1:
            where = clauses[0]
        else:
            where = {"$and": clauses}
        entries = self._store.grep_entries(pattern, where=where, k=k)
        return [
            MemoryRecord(
                content=e.content,
                category=e.category,
                metadata=e.metadata,
                relevance_score=1.0,
            )
            for e in entries
        ]

    def remember(
        self,
        content: str,
        category: str = MEMORY_CATEGORY_SEMANTIC,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if category in _DEDUP_CATEGORIES:
            doc_id = _dedup_id(category, content, metadata or {})
            self._store.upsert(content, category=category, metadata=metadata, doc_id=doc_id)
        else:
            self._store.store(content, category=category, metadata=metadata)

    def build_context(self, query: str) -> str:
        entries = self._store.retrieve(query, categories=None, k=_BUILD_CONTEXT_K)
        buckets: dict[str, list[str]] = {}
        seen: set[str] = set()
        for e in entries:
            if e.relevance_score < _MIN_RELEVANCE or e.content in seen:
                continue
            seen.add(e.content)
            buckets.setdefault(e.category, []).append(f"- {e.content}")

        sections: list[str] = []
        # Stable ordering: known labels first, then any custom categories.
        ordered = list(_CATEGORY_LABELS.keys()) + [c for c in buckets if c not in _CATEGORY_LABELS]
        for cat in ordered:
            lines = buckets.get(cat)
            if not lines:
                continue
            label = _CATEGORY_LABELS.get(cat, cat.capitalize())
            sections.append(f"{label}:\n" + "\n".join(lines))

        text = "\n\n".join(sections) if sections else "No relevant memories."
        if len(text) > _BUILD_CONTEXT_MAX_CHARS:
            text = text[:_BUILD_CONTEXT_MAX_CHARS] + "\n[memory truncated]"
        return text

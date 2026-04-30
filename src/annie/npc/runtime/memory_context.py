"""MemoryContextBuilder — thin wrapper around the world-engine MemoryInterface.

This adapter exists so the Executor / Reflector can call a small, stable
surface (``build_context``, ``remember``, ``recall``) without importing the
protocol module directly. It has no state, no policy; it just forwards.

Recall dedup
------------
``build_context`` accepts an optional ``seen_ids`` set (run-scoped).  Any
record returned by the underlying ``build_context`` call has its content
registered in that set.  ``MemoryRecallTool`` and ``MemoryGrepTool`` do the
symmetric filtering on the tool side.  The "id" used here is the record
content string (stable, cheap, and exactly the thing the LLM sees).
"""

from __future__ import annotations

from typing import Any

from annie.npc.memory.interface import (
    MEMORY_CATEGORY_REFLECTION,
    MEMORY_CATEGORY_SEMANTIC,
    MemoryInterface,
    MemoryRecord,
)

_BUILD_CONTEXT_K = 8


class MemoryContextBuilder:
    """Runtime component that builds memory context from MemoryInterface."""

    def __init__(self, memory: MemoryInterface):
        self._memory = memory

    def build_context(self, query: str, seen_ids: set[str] | None = None) -> str:
        """Build working-memory string and register shown content in ``seen_ids``.

        If ``seen_ids`` is provided, every content string that appears in the
        returned digest is added to the set so that downstream tool calls can
        skip them.
        """
        text = self._memory.build_context(query)
        if seen_ids is not None and text and text not in {"No relevant memories.", "无相关记忆。"}:
            # Best-effort: register the content we know was recalled.
            # We pull the raw records to get their content strings.
            try:
                records = self._memory.recall(query, k=_BUILD_CONTEXT_K)
                for r in records:
                    seen_ids.add(r.content)
            except Exception:  # noqa: BLE001 — don't let dedup failure break the run
                pass
        return text

    def recall(
        self,
        query: str,
        categories: list[str] | None = None,
        k: int = 5,
    ) -> list[MemoryRecord]:
        return self._memory.recall(query, categories=categories, k=k)

    def remember(
        self,
        content: str,
        category: str = MEMORY_CATEGORY_SEMANTIC,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._memory.remember(content, category=category, metadata=metadata)

    # Convenience helpers used by Reflector -------------------------------
    def store_reflection(self, content: str, metadata: dict[str, Any] | None = None) -> None:
        self._memory.remember(content, category=MEMORY_CATEGORY_REFLECTION, metadata=metadata)

    def store_semantic(self, fact: str, metadata: dict[str, Any] | None = None) -> None:
        self._memory.remember(fact, category=MEMORY_CATEGORY_SEMANTIC, metadata=metadata)

    def store_relationship_note(self, person: str, observation: str) -> None:
        # Merged into reflection category per new spec (person tagged via metadata).
        self._memory.remember(
            observation,
            category=MEMORY_CATEGORY_REFLECTION,
            metadata={"person": person},
        )

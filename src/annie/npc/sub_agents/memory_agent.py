"""MemoryAgent — thin wrapper around the world-engine MemoryInterface.

This adapter exists so the Executor / Reflector can call a small, stable
surface (``build_context``, ``remember``, ``recall``) without importing the
protocol module directly. It has no state, no policy; it just forwards.
"""

from __future__ import annotations

from typing import Any

from annie.npc.memory.interface import (
    MEMORY_CATEGORY_REFLECTION,
    MEMORY_CATEGORY_SEMANTIC,
    MemoryInterface,
    MemoryRecord,
)


class MemoryAgent:
    """Thin adapter over MemoryInterface."""

    def __init__(self, memory: MemoryInterface):
        self._memory = memory

    def build_context(self, query: str) -> str:
        return self._memory.build_context(query)

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

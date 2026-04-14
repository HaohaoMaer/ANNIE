"""MemoryInterface — protocol between NPC Agent and long-term memory backends.

The NPC Agent layer must never ``import chromadb`` or touch concrete memory
classes. All long-term recall/remember operations go through this protocol,
implemented by the world-engine layer (default: ChromaDB-backed).

``category`` is an open string — world engines may register any categories
they like. Conventional values are exported as module-level constants but
are **not** an enum.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

# --- Conventional category strings (non-exhaustive; not an enum) -----------
MEMORY_CATEGORY_EPISODIC = "episodic"
MEMORY_CATEGORY_SEMANTIC = "semantic"
MEMORY_CATEGORY_REFLECTION = "reflection"
MEMORY_CATEGORY_IMPRESSION = "impression"
MEMORY_CATEGORY_TODO = "todo"


class MemoryRecord(BaseModel):
    """Neutral record shape returned by ``recall``."""

    content: str
    category: str = MEMORY_CATEGORY_SEMANTIC
    metadata: dict[str, Any] = Field(default_factory=dict)
    relevance_score: float = 0.0


@runtime_checkable
class MemoryInterface(Protocol):
    """Protocol the world engine must satisfy to drive NPC memory."""

    def recall(
        self,
        query: str,
        categories: list[str] | None = None,
        k: int = 5,
    ) -> list[MemoryRecord]:
        """Retrieve up to *k* relevant records, optionally filtered by category list."""
        ...

    def grep(
        self,
        pattern: str,
        category: str | None = None,
        metadata_filters: dict[str, Any] | None = None,
        k: int = 20,
    ) -> list[MemoryRecord]:
        """Substring-match entry.content (case-insensitive), optionally filtered by
        category / metadata. Sorted by ``created_at`` newest first; ``relevance_score``
        is a fixed 1.0 since literal hits have no similarity meaning.
        """
        ...

    def remember(
        self,
        content: str,
        category: str = MEMORY_CATEGORY_SEMANTIC,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Persist a single record under the given category."""
        ...

    def build_context(self, query: str) -> str:
        """Return a prompt-ready free-text digest of relevant records."""
        ...

"""MemoryInterface — protocol between NPC Agent and long-term memory backends.

The NPC Agent layer must never ``import chromadb`` or touch concrete memory
classes. All long-term recall/remember operations go through this protocol,
implemented by the world-engine layer (default: ChromaDB-backed).

Type is an open string — world engines may register any types they like.
Recommended common values are exported as module-level constants but are
**not** an enum: the interface does not restrict the value set.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

# --- Conventional type strings (non-exhaustive; not an enum) ---------------
MEMORY_TYPE_SEMANTIC = "semantic"
MEMORY_TYPE_REFLECTION = "reflection"
MEMORY_TYPE_RELATIONSHIP = "relationship"


class MemoryRecord(BaseModel):
    """Neutral record shape returned by ``recall``."""

    content: str
    type: str = MEMORY_TYPE_SEMANTIC
    metadata: dict[str, Any] = Field(default_factory=dict)
    relevance_score: float = 0.0


@runtime_checkable
class MemoryInterface(Protocol):
    """Protocol the world engine must satisfy to drive NPC memory."""

    def recall(
        self,
        query: str,
        type: str | None = None,
        k: int = 5,
    ) -> list[MemoryRecord]:
        """Retrieve up to *k* relevant records, optionally filtered by type."""
        ...

    def remember(
        self,
        content: str,
        type: str = MEMORY_TYPE_SEMANTIC,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Persist a single record under the given type."""
        ...

    def build_context(self, query: str) -> str:
        """Return a prompt-ready free-text digest of relevant records."""
        ...

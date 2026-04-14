"""Module-level write lock for ChromaDB operations.

ChromaDB vector operations are read-safe for concurrent access but writes
(collection.add / collection.delete) must be serialised to avoid race
conditions when multiple NPC threads write to the same client simultaneously.

Usage:
    from annie.npc.memory.chroma_lock import ChromaWriteGuard

    with ChromaWriteGuard():
        self._collection.add(...)
"""

from __future__ import annotations

import threading

_WRITE_LOCK = threading.Lock()


class ChromaWriteGuard:
    """Context manager that acquires the module-level ChromaDB write lock."""

    def __enter__(self) -> "ChromaWriteGuard":
        _WRITE_LOCK.acquire()
        return self

    def __exit__(self, *args: object) -> None:
        _WRITE_LOCK.release()

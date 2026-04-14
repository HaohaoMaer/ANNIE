# Memory System — NPC Agent layer only exposes the MemoryInterface protocol.
from annie.npc.memory.interface import (
    MEMORY_CATEGORY_EPISODIC,
    MEMORY_CATEGORY_IMPRESSION,
    MEMORY_CATEGORY_REFLECTION,
    MEMORY_CATEGORY_SEMANTIC,
    MemoryInterface,
    MemoryRecord,
)

__all__ = [
    "MemoryInterface",
    "MemoryRecord",
    "MEMORY_CATEGORY_EPISODIC",
    "MEMORY_CATEGORY_SEMANTIC",
    "MEMORY_CATEGORY_REFLECTION",
    "MEMORY_CATEGORY_IMPRESSION",
]

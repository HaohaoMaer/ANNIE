"""Knowledge Manager - Manages shared and private knowledge.

Handles storage and retrieval of knowledge shared among NPCs.
"""

from __future__ import annotations

from datetime import datetime, UTC
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class KnowledgeCategory(str, Enum):
    """Categories of knowledge."""

    PUBLIC_EVENT = "public_event"
    BACKGROUND = "background"
    RULE = "rule"
    CLUE = "clue"
    TESTIMONY = "testimony"
    SECRET = "secret"
    FACT = "fact"


class KnowledgeVisibility(str, Enum):
    """Visibility levels of knowledge."""

    PUBLIC = "public"
    PRIVATE = "private"
    SECRET = "secret"
    CUSTOM = "custom"


class SharedKnowledge(BaseModel):
    """A piece of knowledge that can be shared."""

    id: str
    content: str
    category: KnowledgeCategory = KnowledgeCategory.FACT
    visibility: KnowledgeVisibility = KnowledgeVisibility.PUBLIC
    visible_to: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: str = ""
    importance: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)

    def is_visible_to(self, npc_name: str) -> bool:
        """Check if this knowledge is visible to an NPC.

        Args:
            npc_name: Name of the NPC.

        Returns:
            True if visible, False otherwise.
        """
        if self.visibility == KnowledgeVisibility.PUBLIC:
            return True

        if self.visibility == KnowledgeVisibility.PRIVATE:
            return False

        if self.visibility == KnowledgeVisibility.CUSTOM:
            return npc_name in self.visible_to

        return False


class KnowledgeManager:
    """Manages shared and private knowledge for NPCs."""

    def __init__(self) -> None:
        """Initialize the knowledge manager."""
        self._knowledge_store: dict[str, SharedKnowledge] = {}
        self._npc_knowledge: dict[str, list[str]] = {}
        self._category_index: dict[KnowledgeCategory, list[str]] = {}

    def add_shared_knowledge(
        self,
        knowledge: SharedKnowledge,
    ) -> None:
        """Add shared knowledge to the store.

        Args:
            knowledge: The knowledge to add.
        """
        self._knowledge_store[knowledge.id] = knowledge

        if knowledge.category not in self._category_index:
            self._category_index[knowledge.category] = []
        self._category_index[knowledge.category].append(knowledge.id)

        if knowledge.visibility == KnowledgeVisibility.PUBLIC:
            for npc_name in self._npc_knowledge:
                if knowledge.id not in self._npc_knowledge[npc_name]:
                    self._npc_knowledge[npc_name].append(knowledge.id)

    def get_shared_knowledge(
        self,
        npc_name: str | None = None,
    ) -> list[SharedKnowledge]:
        """Get shared knowledge visible to an NPC.

        Args:
            npc_name: Name of the NPC (None = all public knowledge).

        Returns:
            List of visible knowledge.
        """
        if npc_name is None:
            return [
                k for k in self._knowledge_store.values()
                if k.visibility == KnowledgeVisibility.PUBLIC
            ]

        if npc_name not in self._npc_knowledge:
            self._npc_knowledge[npc_name] = []

        visible_knowledge = []
        for kid in self._npc_knowledge[npc_name]:
            if kid in self._knowledge_store:
                visible_knowledge.append(self._knowledge_store[kid])

        for k in self._knowledge_store.values():
            if k.is_visible_to(npc_name) and k.id not in [kk.id for kk in visible_knowledge]:
                visible_knowledge.append(k)

        return visible_knowledge

    def grant_knowledge(
        self,
        npc_name: str,
        knowledge_id: str,
    ) -> bool:
        """Grant knowledge to an NPC.

        Args:
            npc_name: Name of the NPC.
            knowledge_id: ID of the knowledge.

        Returns:
            True if granted, False if not found.
        """
        if knowledge_id not in self._knowledge_store:
            return False

        if npc_name not in self._npc_knowledge:
            self._npc_knowledge[npc_name] = []

        if knowledge_id not in self._npc_knowledge[npc_name]:
            self._npc_knowledge[npc_name].append(knowledge_id)

        return True

    def revoke_knowledge(
        self,
        npc_name: str,
        knowledge_id: str,
    ) -> bool:
        """Revoke knowledge from an NPC.

        Args:
            npc_name: Name of the NPC.
            knowledge_id: ID of the knowledge.

        Returns:
            True if revoked, False if not found.
        """
        if npc_name not in self._npc_knowledge:
            return False

        if knowledge_id in self._npc_knowledge[npc_name]:
            self._npc_knowledge[npc_name].remove(knowledge_id)
            return True

        return False

    def get_knowledge_by_category(
        self,
        category: KnowledgeCategory,
        npc_name: str | None = None,
    ) -> list[SharedKnowledge]:
        """Get knowledge by category.

        Args:
            category: The category to filter by.
            npc_name: Optional NPC name for visibility filtering.

        Returns:
            List of matching knowledge.
        """
        knowledge_ids = self._category_index.get(category, [])

        knowledge_list = [
            self._knowledge_store[kid]
            for kid in knowledge_ids
            if kid in self._knowledge_store
        ]

        if npc_name:
            knowledge_list = [k for k in knowledge_list if k.is_visible_to(npc_name)]

        return knowledge_list

    def search_knowledge(
        self,
        query: str,
        npc_name: str | None = None,
    ) -> list[SharedKnowledge]:
        """Search knowledge by content.

        Args:
            query: Search query.
            npc_name: Optional NPC name for visibility filtering.

        Returns:
            List of matching knowledge.
        """
        query_lower = query.lower()
        matches = []

        for k in self._knowledge_store.values():
            if query_lower in k.content.lower():
                if npc_name is None or k.is_visible_to(npc_name):
                    matches.append(k)

        return matches

    def register_npc(self, npc_name: str) -> None:
        """Register an NPC in the knowledge system.

        Args:
            npc_name: Name of the NPC.
        """
        if npc_name not in self._npc_knowledge:
            self._npc_knowledge[npc_name] = []

            for k in self._knowledge_store.values():
                if k.visibility == KnowledgeVisibility.PUBLIC:
                    self._npc_knowledge[npc_name].append(k.id)

    def unregister_npc(self, npc_name: str) -> None:
        """Unregister an NPC from the knowledge system.

        Args:
            npc_name: Name of the NPC.
        """
        if npc_name in self._npc_knowledge:
            del self._npc_knowledge[npc_name]

    def get_npc_knowledge_ids(self, npc_name: str) -> list[str]:
        """Get all knowledge IDs known to an NPC.

        Args:
            npc_name: Name of the NPC.

        Returns:
            List of knowledge IDs.
        """
        return self._npc_knowledge.get(npc_name, []).copy()

    def detect_duplicates(self) -> list[tuple[str, str]]:
        """Detect potential duplicate knowledge entries.

        Returns:
            List of (id1, id2) pairs that may be duplicates.
        """
        duplicates = []
        knowledge_list = list(self._knowledge_store.values())

        for i, k1 in enumerate(knowledge_list):
            for k2 in knowledge_list[i + 1:]:
                if self._is_duplicate(k1, k2):
                    duplicates.append((k1.id, k2.id))

        return duplicates

    def _is_duplicate(
        self,
        k1: SharedKnowledge,
        k2: SharedKnowledge,
    ) -> bool:
        """Check if two knowledge entries are duplicates."""
        if k1.content == k2.content:
            return True

        if k1.category == k2.category:
            words1 = set(k1.content.lower().split())
            words2 = set(k2.content.lower().split())
            overlap = len(words1 & words2)
            total = len(words1 | words2)
            if total > 0 and overlap / total > 0.8:
                return True

        return False

    def remove_knowledge(self, knowledge_id: str) -> bool:
        """Remove knowledge from the system.

        Args:
            knowledge_id: ID of the knowledge to remove.

        Returns:
            True if removed, False if not found.
        """
        if knowledge_id not in self._knowledge_store:
            return False

        knowledge = self._knowledge_store[knowledge_id]

        if knowledge.category in self._category_index:
            if knowledge_id in self._category_index[knowledge.category]:
                self._category_index[knowledge.category].remove(knowledge_id)

        for npc_name in self._npc_knowledge:
            if knowledge_id in self._npc_knowledge[npc_name]:
                self._npc_knowledge[npc_name].remove(knowledge_id)

        del self._knowledge_store[knowledge_id]

        return True

    def get_knowledge_count(self) -> int:
        """Get total number of knowledge entries.

        Returns:
            Total count.
        """
        return len(self._knowledge_store)

    def get_npc_count(self, npc_name: str) -> int:
        """Get number of knowledge entries known to an NPC.

        Args:
            npc_name: Name of the NPC.

        Returns:
            Knowledge count for the NPC.
        """
        return len(self._npc_knowledge.get(npc_name, []))

    def to_dict(self) -> dict:
        """Export to dictionary.

        Returns:
            Dictionary representation.
        """
        return {
            "knowledge_store": {
                kid: k.model_dump()
                for kid, k in self._knowledge_store.items()
            },
            "npc_knowledge": self._npc_knowledge,
            "category_index": {
                cat.value: kids
                for cat, kids in self._category_index.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> KnowledgeManager:
        """Create from dictionary.

        Args:
            data: Dictionary representation.

        Returns:
            KnowledgeManager instance.
        """
        manager = cls()

        for kid, kdata in data.get("knowledge_store", {}).items():
            knowledge = SharedKnowledge(**kdata)
            manager._knowledge_store[kid] = knowledge

        manager._npc_knowledge = data.get("npc_knowledge", {})

        for cat_str, kids in data.get("category_index", {}).items():
            cat = KnowledgeCategory(cat_str)
            manager._category_index[cat] = kids

        return manager

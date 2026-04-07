"""Clue Manager - Manages clues for murder mystery games.

Handles clue storage, categorization, and revelation.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Any

from pydantic import BaseModel, Field


class Clue(BaseModel):
    """A single clue in the game."""

    id: str
    category: str
    file_name: str
    content: str
    image_path: str = ""
    discoverable_by: list[str] = Field(default_factory=list)
    discovered: bool = False
    discovered_by: str | None = None
    discovered_at: datetime | None = None
    discovered_at_turn: int | None = None
    importance: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClueManager:
    """Manages all clues in the game."""

    def __init__(self) -> None:
        """Initialize the clue manager."""
        self.clues: dict[str, Clue] = {}
        self._category_index: dict[str, list[str]] = {}
        self._discovered_count: int = 0

    def add_clue(self, clue: Clue) -> None:
        """Add a clue to the manager.

        Args:
            clue: The clue to add.
        """
        self.clues[clue.id] = clue

        if clue.category not in self._category_index:
            self._category_index[clue.category] = []
        self._category_index[clue.category].append(clue.id)

    def get_clue(self, clue_id: str) -> Clue | None:
        """Get a clue by ID.

        Args:
            clue_id: ID of the clue.

        Returns:
            The clue, or None if not found.
        """
        return self.clues.get(clue_id)

    def get_clues_by_category(self, category: str) -> list[Clue]:
        """Get all clues in a category.

        Args:
            category: Category name.

        Returns:
            List of clues in that category.
        """
        clue_ids = self._category_index.get(category, [])
        return [self.clues[cid] for cid in clue_ids if cid in self.clues]

    def get_all_categories(self) -> list[str]:
        """Get all clue categories.

        Returns:
            List of category names.
        """
        return list(self._category_index.keys())

    def reveal_clue(self, clue_id: str, npc_name: str, turn_index: int | None = None) -> bool:
        """Reveal a clue to an NPC.

        Args:
            clue_id: ID of the clue to reveal.
            npc_name: Name of the NPC discovering the clue.
            turn_index: The game turn index at which the clue was discovered.

        Returns:
            True if clue was revealed, False if not found or already discovered.
        """
        clue = self.clues.get(clue_id)
        if not clue:
            return False

        if clue.discovered:
            return False

        clue.discovered = True
        clue.discovered_by = npc_name
        clue.discovered_at = datetime.now(UTC)
        clue.discovered_at_turn = turn_index
        self._discovered_count += 1

        return True

    def get_discovered_clues(self) -> list[Clue]:
        """Get all discovered clues.

        Returns:
            List of discovered clues.
        """
        return [c for c in self.clues.values() if c.discovered]

    def get_undiscovered_clues(self) -> list[Clue]:
        """Get all undiscovered clues.

        Returns:
            List of undiscovered clues.
        """
        return [c for c in self.clues.values() if not c.discovered]

    def get_clues_discovered_by(self, npc_name: str) -> list[Clue]:
        """Get all clues discovered by a specific NPC.

        Args:
            npc_name: Name of the NPC.

        Returns:
            List of clues discovered by that NPC.
        """
        return [
            c for c in self.clues.values()
            if c.discovered and c.discovered_by == npc_name
        ]

    def get_discovered_count(self) -> int:
        """Get the number of discovered clues.

        Returns:
            Number of discovered clues.
        """
        return self._discovered_count

    def get_total_count(self) -> int:
        """Get the total number of clues.

        Returns:
            Total number of clues.
        """
        return len(self.clues)

    def get_progress(self) -> float:
        """Get the progress of clue discovery.

        Returns:
            Progress as a float between 0 and 1.
        """
        if not self.clues:
            return 0.0
        return self._discovered_count / len(self.clues)

    def search_clues(self, keyword: str) -> list[Clue]:
        """Search clues by keyword in content.

        Args:
            keyword: Keyword to search for.

        Returns:
            List of matching clues.
        """
        keyword_lower = keyword.lower()
        return [
            c for c in self.clues.values()
            if keyword_lower in c.content.lower() or
               keyword_lower in c.file_name.lower() or
               keyword_lower in c.category.lower()
        ]

    def get_clues_for_phase(self, phase_name: str) -> list[Clue]:
        """Get clues that should be available in a specific phase.

        Args:
            phase_name: Name of the phase.

        Returns:
            List of clues for that phase.
        """
        phase_lower = phase_name.lower()

        if "一" in phase_lower or "first" in phase_lower or "开场" in phase_lower:
            return self.get_clues_by_category("死者的房间")

        return list(self.clues.values())

    def reset(self) -> None:
        """Reset all clues to undiscovered state."""
        for clue in self.clues.values():
            clue.discovered = False
            clue.discovered_by = None
            clue.discovered_at = None

        self._discovered_count = 0

    def to_dict(self) -> dict:
        """Export clue manager state to a dictionary.

        Returns:
            Dictionary representation.
        """
        return {
            "clues": {
                cid: clue.model_dump()
                for cid, clue in self.clues.items()
            },
            "category_index": self._category_index,
            "discovered_count": self._discovered_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ClueManager:
        """Create a ClueManager from a dictionary.

        Args:
            data: Dictionary representation.

        Returns:
            ClueManager instance.
        """
        manager = cls()

        for cid, cdata in data.get("clues", {}).items():
            clue = Clue(**cdata)
            manager.clues[cid] = clue

        manager._category_index = data.get("category_index", {})
        manager._discovered_count = data.get("discovered_count", 0)

        return manager

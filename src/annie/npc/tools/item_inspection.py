"""Item Inspection Tool - Inspects items and discovers clues.

Used in murder mystery scenarios to examine physical objects.
"""

from __future__ import annotations

from typing import Any

from annie.npc.tools.base_tool import BaseTool


class ItemInspectionTool(BaseTool):
    """Tool for inspecting items in the game world."""

    name = "item_inspection"
    description = (
        "Inspects an item to discover its description and any hidden clues. "
        "Use this when you want to examine a physical object more closely."
    )

    def __init__(self) -> None:
        self._item_registry: dict[str, dict[str, Any]] = {}

    def set_item_registry(self, registry: dict[str, dict[str, Any]]) -> None:
        """Set the item registry for the tool."""
        self._item_registry = registry

    def execute(self, context: dict) -> dict:
        """Execute item inspection.

        Args:
            context: Dict with keys:
                - 'task': str, the task description
                - 'npc_name': str, the NPC's name
                - 'item_id': str (optional), ID of item to inspect
                - 'item_name': str (optional), name of item to inspect

        Returns:
            Dict with:
                - 'success': bool
                - 'description': str, item description
                - 'clues': list[str], discovered clues
                - 'error': str (if failed)
        """
        item_id = context.get("item_id") or context.get("item_name")

        if not item_id:
            return self._error_result("No item specified for inspection")

        item_data = self._find_item(item_id)
        if not item_data:
            return self._error_result(f"Item not found: {item_id}")

        description = item_data.get("description", "Nothing special about this item.")
        clues = item_data.get("clues", [])

        discoverable_clues = [
            clue for clue in clues
            if not clue.get("discovered", False)
        ]

        return {
            "success": True,
            "item_id": item_id,
            "description": description,
            "clues": discoverable_clues,
            "inspectable": item_data.get("inspectable", True),
        }

    def _find_item(self, item_id: str) -> dict[str, Any] | None:
        """Find item by ID or name."""
        if item_id in self._item_registry:
            return self._item_registry[item_id]

        for item_key, item_data in self._item_registry.items():
            if item_data.get("name", "").lower() == item_id.lower():
                return item_data

        return None

    def _error_result(self, error: str) -> dict[str, Any]:
        """Create an error result dict."""
        return {
            "success": False,
            "description": "",
            "clues": [],
            "error": error,
        }

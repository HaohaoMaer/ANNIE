"""Location Search Tool - Searches locations for items and NPCs.

Used in murder mystery scenarios to explore the environment.
"""

from __future__ import annotations

from typing import Any

from annie.npc.tools.base_tool import BaseTool


class LocationSearchTool(BaseTool):
    """Tool for searching locations in the game world."""

    name = "location_search"
    description = (
        "Searches a location to discover available items and NPCs present. "
        "Use this when you want to explore a room or area."
    )

    def __init__(self) -> None:
        self._location_registry: dict[str, dict[str, Any]] = {}

    def set_location_registry(self, registry: dict[str, dict[str, Any]]) -> None:
        """Set the location registry for the tool."""
        self._location_registry = registry

    def execute(self, context: dict) -> dict:
        """Execute location search.

        Args:
            context: Dict with keys:
                - 'task': str, the task description
                - 'npc_name': str, the NPC's name
                - 'location_name': str (optional), name of location to search

        Returns:
            Dict with:
                - 'success': bool
                - 'description': str, location description
                - 'items': list[str], available items
                - 'npcs': list[str], NPCs present
                - 'connections': list[str], connected locations
                - 'error': str (if failed)
        """
        location_name = context.get("location_name")

        if not location_name:
            return self._error_result("No location specified for search")

        location_data = self._find_location(location_name)
        if not location_data:
            return self._error_result(f"Location not found: {location_name}")

        return {
            "success": True,
            "location_name": location_name,
            "description": location_data.get("description", ""),
            "items": location_data.get("items", []),
            "npcs": location_data.get("npcs_present", []),
            "connections": location_data.get("connections", []),
        }

    def _find_location(self, location_name: str) -> dict[str, Any] | None:
        """Find location by name."""
        location_lower = location_name.lower()

        for loc_key, loc_data in self._item_registry.items():
            if loc_data.get("name", "").lower() == location_lower:
                return loc_data
            if loc_key.lower() == location_lower:
                return loc_data

        return None

    def _error_result(self, error: str) -> dict[str, Any]:
        """Create an error result dict."""
        return {
            "success": False,
            "description": "",
            "items": [],
            "npcs": [],
            "connections": [],
            "error": error,
        }

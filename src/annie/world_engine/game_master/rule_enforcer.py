"""Rule Enforcer - Validates actions and enforces game rules.

Ensures NPCs follow the rules of the murder mystery game.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class ViolationType(str, Enum):
    """Types of rule violations."""

    INVALID_ACTION = "invalid_action"
    NOT_YOUR_TURN = "not_your_turn"
    LOCATION_DENIED = "location_denied"
    ITEM_UNAVAILABLE = "item_unavailable"
    INFORMATION_RESTRICTED = "information_restricted"
    PHASE_RESTRICTION = "phase_restriction"
    COOLDOWN_ACTIVE = "cooldown_active"


class Violation:
    """A rule violation."""

    def __init__(
        self,
        violation_type: ViolationType,
        message: str,
        severity: str = "warning",
    ) -> None:
        self.violation_type = violation_type
        self.message = message
        self.severity = severity
        self.context: dict[str, Any] = {}

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "type": self.violation_type.value,
            "message": self.message,
            "severity": self.severity,
            "context": self.context,
        }


class RuleEnforcer:
    """Enforces game rules and validates actions."""

    def __init__(self) -> None:
        """Initialize the rule enforcer."""
        self._action_cooldowns: dict[str, dict[str, int]] = {}
        self._location_restrictions: dict[str, list[str]] = {}
        self._item_restrictions: dict[str, list[str]] = {}
        self._information_access: dict[str, list[str]] = {}
        self._violations: list[Violation] = []

    def validate_action(
        self,
        npc: str,
        action: str,
        context: dict,
    ) -> tuple[bool, Violation | None]:
        """Validate if an action is allowed.

        Args:
            npc: Name of the NPC attempting the action.
            action: Description of the action.
            context: Current game context including:
                - current_turn: name of NPC whose turn it is
                - current_phase: current game phase
                - allowed_actions: list of allowed actions
                - npc_location: current location of NPC
                - available_items: items available to NPC

        Returns:
            Tuple of (is_valid, violation_if_any).
        """
        current_turn = context.get("current_turn")
        if current_turn and current_turn != npc:
            violation = Violation(
                ViolationType.NOT_YOUR_TURN,
                f"It's {current_turn}'s turn, not {npc}'s",
                "error",
            )
            violation.context = {"current_turn": current_turn, "attempted_by": npc}
            self._violations.append(violation)
            return False, violation

        allowed_actions = context.get("allowed_actions", [])
        if allowed_actions:
            action_allowed = any(
                allowed.lower() in action.lower()
                for allowed in allowed_actions
            )
            if not action_allowed:
                violation = Violation(
                    ViolationType.PHASE_RESTRICTION,
                    f"Action '{action}' is not allowed in current phase",
                    "warning",
                )
                violation.context = {
                    "action": action,
                    "allowed_actions": allowed_actions,
                }
                self._violations.append(violation)
                return False, violation

        if self._is_on_cooldown(npc, action):
            violation = Violation(
                ViolationType.COOLDOWN_ACTIVE,
                f"Action '{action}' is on cooldown for {npc}",
                "warning",
            )
            self._violations.append(violation)
            return False, violation

        action_lower = action.lower()

        if "move" in action_lower or "go to" in action_lower:
            return self._validate_movement(npc, action, context)

        if "take" in action_lower or "pick up" in action_lower:
            return self._validate_item_action(npc, action, context)

        if "inspect" in action_lower or "examine" in action_lower:
            return self._validate_inspection(npc, action, context)

        return True, None

    def _validate_movement(
        self,
        npc: str,
        action: str,
        context: dict,
    ) -> tuple[bool, Violation | None]:
        """Validate a movement action."""
        npc_location = context.get("npc_location", "")

        if npc_location in self._location_restrictions:
            restricted = self._location_restrictions[npc_location]
            for loc in restricted:
                if loc.lower() in action.lower():
                    violation = Violation(
                        ViolationType.LOCATION_DENIED,
                        f"Cannot move to {loc} from current location",
                        "error",
                    )
                    self._violations.append(violation)
                    return False, violation

        return True, None

    def _validate_item_action(
        self,
        npc: str,
        action: str,
        context: dict,
    ) -> tuple[bool, Violation | None]:
        """Validate an item-related action."""
        available_items = context.get("available_items", [])

        for item, restricted_npcs in self._item_restrictions.items():
            if item.lower() in action.lower() and npc in restricted_npcs:
                violation = Violation(
                    ViolationType.ITEM_UNAVAILABLE,
                    f"{npc} cannot access {item}",
                    "error",
                )
                self._violations.append(violation)
                return False, violation

        return True, None

    def _validate_inspection(
        self,
        npc: str,
        action: str,
        context: dict,
    ) -> tuple[bool, Violation | None]:
        """Validate an inspection action."""
        return True, None

    def check_constraints(self, world_state: dict) -> list[str]:
        """Check all game constraints.

        Args:
            world_state: Current world state.

        Returns:
            List of constraint violation messages.
        """
        violations = []

        npc_locations = world_state.get("npc_locations", {})
        location_counts: dict[str, int] = {}
        for npc, location in npc_locations.items():
            location_counts[location] = location_counts.get(location, 0) + 1

        for location, count in location_counts.items():
            if count > 5:
                violations.append(f"Location {location} is overcrowded ({count} NPCs)")

        item_holders = world_state.get("item_holders", {})
        item_counts: dict[str, int] = {}
        for item, holder in item_holders.items():
            if holder:
                item_counts[holder] = item_counts.get(holder, 0) + 1

        for holder, count in item_counts.items():
            if count > 3:
                violations.append(f"{holder} is carrying too many items ({count})")

        return violations

    def resolve_conflict(self, conflict: dict) -> dict:
        """Resolve a conflict between NPCs or actions.

        Args:
            conflict: Dict describing the conflict with:
                - type: type of conflict
                - parties: list of involved NPCs
                - action: the contested action

        Returns:
            Resolution dict with:
                - winner: who gets to act
                - reason: explanation
        """
        conflict_type = conflict.get("type", "unknown")
        parties = conflict.get("parties", [])

        if conflict_type == "simultaneous_action":
            if parties:
                winner = parties[0]
                return {
                    "winner": winner,
                    "reason": f"{winner} acted first",
                    "action": "proceed",
                }

        if conflict_type == "resource_contention":
            if parties:
                winner = parties[0]
                return {
                    "winner": winner,
                    "reason": f"{winner} had priority",
                    "action": "proceed",
                }

        return {
            "winner": None,
            "reason": "Conflict could not be resolved",
            "action": "retry",
        }

    def set_action_cooldown(
        self,
        npc: str,
        action_type: str,
        turns: int,
    ) -> None:
        """Set a cooldown for an action type.

        Args:
            npc: Name of the NPC.
            action_type: Type of action.
            turns: Number of turns to wait.
        """
        if npc not in self._action_cooldowns:
            self._action_cooldowns[npc] = {}
        self._action_cooldowns[npc][action_type] = turns

    def _is_on_cooldown(self, npc: str, action: str) -> bool:
        """Check if an action is on cooldown for an NPC."""
        if npc not in self._action_cooldowns:
            return False

        for action_type, remaining in self._action_cooldowns[npc].items():
            if action_type.lower() in action.lower() and remaining > 0:
                return True

        return False

    def tick_cooldowns(self) -> None:
        """Reduce all cooldowns by 1 turn."""
        for npc in self._action_cooldowns:
            for action_type in self._action_cooldowns[npc]:
                self._action_cooldowns[npc][action_type] = max(
                    0,
                    self._action_cooldowns[npc][action_type] - 1,
                )

    def add_location_restriction(
        self,
        from_location: str,
        to_location: str,
    ) -> None:
        """Add a movement restriction.

        Args:
            from_location: Starting location.
            to_location: Restricted destination.
        """
        if from_location not in self._location_restrictions:
            self._location_restrictions[from_location] = []
        self._location_restrictions[from_location].append(to_location)

    def add_item_restriction(
        self,
        item: str,
        restricted_npcs: list[str],
    ) -> None:
        """Restrict item access for specific NPCs.

        Args:
            item: The item to restrict.
            restricted_npcs: NPCs who cannot access the item.
        """
        self._item_restrictions[item] = restricted_npcs

    def set_information_access(
        self,
        information_id: str,
        allowed_npcs: list[str],
    ) -> None:
        """Set which NPCs can access specific information.

        Args:
            information_id: ID of the information.
            allowed_npcs: NPCs who can access it.
        """
        self._information_access[information_id] = allowed_npcs

    def can_access_information(
        self,
        npc: str,
        information_id: str,
    ) -> bool:
        """Check if an NPC can access information.

        Args:
            npc: Name of the NPC.
            information_id: ID of the information.

        Returns:
            True if access is allowed, False otherwise.
        """
        if information_id not in self._information_access:
            return True

        return npc in self._information_access[information_id]

    def get_violations(self, limit: int = 10) -> list[Violation]:
        """Get recent violations.

        Args:
            limit: Maximum number to return.

        Returns:
            List of recent violations.
        """
        return self._violations[-limit:]

    def clear_violations(self) -> None:
        """Clear violation history."""
        self._violations.clear()

    def clear_cooldowns(self) -> None:
        """Clear all cooldowns."""
        self._action_cooldowns.clear()

    def reset(self) -> None:
        """Reset all rules and restrictions."""
        self._action_cooldowns.clear()
        self._location_restrictions.clear()
        self._item_restrictions.clear()
        self._information_access.clear()
        self._violations.clear()

    def to_dict(self) -> dict:
        """Export to dictionary.

        Returns:
            Dictionary representation.
        """
        return {
            "action_cooldowns": self._action_cooldowns,
            "location_restrictions": self._location_restrictions,
            "item_restrictions": self._item_restrictions,
            "information_access": self._information_access,
        }

"""Turn Manager - Manages NPC turn order and action queue.

Ensures NPCs act in sequence and no two NPCs act simultaneously.
"""

from __future__ import annotations

from collections import deque
from enum import Enum
from typing import Any


class TurnStatus(str, Enum):
    """Status of a turn."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class Turn:
    """Represents a single NPC's turn."""

    def __init__(self, npc_name: str, turn_number: int) -> None:
        self.npc_name = npc_name
        self.turn_number = turn_number
        self.status = TurnStatus.PENDING
        self.actions: list[str] = []
        self.metadata: dict[str, Any] = {}

    def start(self) -> None:
        """Mark turn as started."""
        self.status = TurnStatus.IN_PROGRESS

    def complete(self) -> None:
        """Mark turn as completed."""
        self.status = TurnStatus.COMPLETED

    def skip(self) -> None:
        """Mark turn as skipped."""
        self.status = TurnStatus.SKIPPED

    def add_action(self, action: str) -> None:
        """Add an action taken during this turn."""
        self.actions.append(action)


class TurnManager:
    """Manages turn order for NPCs."""

    def __init__(self, npc_names: list[str] | None = None) -> None:
        """Initialize the turn manager.

        Args:
            npc_names: List of NPC names in turn order.
        """
        self._npc_names: list[str] = npc_names or []
        self._turn_queue: deque[Turn] = deque()
        self._current_turn: Turn | None = None
        self._turn_number: int = 0
        self._round_number: int = 1
        self._turn_history: list[Turn] = []

        if self._npc_names:
            self._initialize_round()

    def _initialize_round(self) -> None:
        """Initialize a new round with turns for all NPCs."""
        for npc_name in self._npc_names:
            self._turn_number += 1
            self._turn_queue.append(Turn(npc_name, self._turn_number))

    def get_current_turn(self) -> Turn | None:
        """Get the current turn.

        Returns:
            Current turn, or None if no turn is active.
        """
        return self._current_turn

    def get_current_npc(self) -> str | None:
        """Get the name of the NPC whose turn it is.

        Returns:
            NPC name, or None if no turn is active.
        """
        if self._current_turn:
            return self._current_turn.npc_name
        return None

    def next_turn(self) -> Turn | None:
        """Advance to the next turn.

        Returns:
            The next turn, or None if round is complete.
        """
        if self._current_turn and self._current_turn.status == TurnStatus.IN_PROGRESS:
            self._current_turn.complete()
            self._turn_history.append(self._current_turn)

        if not self._turn_queue:
            self._start_new_round()
            if not self._turn_queue:
                return None

        self._current_turn = self._turn_queue.popleft()
        self._current_turn.start()
        return self._current_turn

    def _start_new_round(self) -> None:
        """Start a new round."""
        self._round_number += 1
        self._initialize_round()

    def is_npc_turn(self, npc_name: str) -> bool:
        """Check if it's a specific NPC's turn.

        Args:
            npc_name: Name of the NPC to check.

        Returns:
            True if it's their turn, False otherwise.
        """
        if not self._current_turn:
            return False
        return self._current_turn.npc_name == npc_name

    def set_order(self, order: list[str]) -> None:
        """Set a new turn order.

        Args:
            order: List of NPC names in new order.
        """
        self._npc_names = order
        self._turn_queue.clear()

        for npc_name in self._npc_names:
            self._turn_number += 1
            turn = Turn(npc_name, self._turn_number)
            self._turn_queue.append(turn)

    def skip_turn(self, npc_name: str) -> bool:
        """Skip a specific NPC's turn.

        Args:
            npc_name: Name of NPC whose turn to skip.

        Returns:
            True if skipped, False if not their turn.
        """
        if not self.is_npc_turn(npc_name):
            return False

        if self._current_turn:
            self._current_turn.skip()
            self._turn_history.append(self._current_turn)
            self._current_turn = None

        return True

    def insert_turn(self, npc_name: str, position: int = 0) -> None:
        """Insert an additional turn for an NPC.

        Args:
            npc_name: Name of NPC to add turn for.
            position: Position in queue (0 = next).
        """
        self._turn_number += 1
        turn = Turn(npc_name, self._turn_number)

        if position == 0:
            self._turn_queue.appendleft(turn)
        elif position >= len(self._turn_queue):
            self._turn_queue.append(turn)
        else:
            queue_list = list(self._turn_queue)
            queue_list.insert(position, turn)
            self._turn_queue = deque(queue_list)

    def get_queue(self) -> list[str]:
        """Get list of NPCs waiting for their turn.

        Returns:
            List of NPC names in queue order.
        """
        return [turn.npc_name for turn in self._turn_queue]

    def get_queue_length(self) -> int:
        """Get number of NPCs waiting in queue.

        Returns:
            Queue length.
        """
        return len(self._turn_queue)

    def get_round_number(self) -> int:
        """Get current round number.

        Returns:
            Round number (starts at 1).
        """
        return self._round_number

    def get_turn_number(self) -> int:
        """Get total turn count across all rounds.

        Returns:
            Total turn number.
        """
        return self._turn_number

    def get_turns_remaining_in_round(self) -> int:
        """Get number of turns remaining in current round.

        Returns:
            Number of turns left.
        """
        return len(self._turn_queue)

    def is_round_complete(self) -> bool:
        """Check if current round is complete.

        Returns:
            True if round is complete, False otherwise.
        """
        return len(self._turn_queue) == 0

    def get_turn_history(self, limit: int = 10) -> list[Turn]:
        """Get recent turn history.

        Args:
            limit: Maximum number of turns to return.

        Returns:
            List of recent turns.
        """
        return self._turn_history[-limit:]

    def get_npc_turn_count(self, npc_name: str) -> int:
        """Get number of turns an NPC has taken.

        Args:
            npc_name: Name of the NPC.

        Returns:
            Number of completed turns.
        """
        return sum(
            1 for turn in self._turn_history
            if turn.npc_name == npc_name and turn.status == TurnStatus.COMPLETED
        )

    def reset(self) -> None:
        """Reset the turn manager."""
        self._turn_queue.clear()
        self._current_turn = None
        self._turn_number = 0
        self._round_number = 1
        self._turn_history.clear()

        if self._npc_names:
            self._initialize_round()

    def add_npc(self, npc_name: str, next_turn: bool = False) -> None:
        """Add an NPC to the turn order.

        Args:
            npc_name: Name of NPC to add.
            next_turn: If True, add to front of queue.
        """
        if npc_name not in self._npc_names:
            self._npc_names.append(npc_name)

        self._turn_number += 1
        turn = Turn(npc_name, self._turn_number)

        if next_turn:
            self._turn_queue.appendleft(turn)
        else:
            self._turn_queue.append(turn)

    def remove_npc(self, npc_name: str) -> int:
        """Remove an NPC from the turn order.

        Args:
            npc_name: Name of NPC to remove.

        Returns:
            Number of turns removed from queue.
        """
        if npc_name in self._npc_names:
            self._npc_names.remove(npc_name)

        removed = 0
        new_queue = deque()
        for turn in self._turn_queue:
            if turn.npc_name != npc_name:
                new_queue.append(turn)
            else:
                removed += 1

        self._turn_queue = new_queue
        return removed

    def record_action(self, action: str) -> None:
        """Record an action for the current turn.

        Args:
            action: Description of the action.
        """
        if self._current_turn:
            self._current_turn.add_action(action)

    def get_all_npc_names(self) -> list[str]:
        """Get all NPC names in the turn order.

        Returns:
            List of NPC names.
        """
        return self._npc_names.copy()

    def to_dict(self) -> dict:
        """Export turn manager state to a dictionary.

        Returns:
            Dictionary representation.
        """
        return {
            "npc_names": self._npc_names,
            "turn_number": self._turn_number,
            "round_number": self._round_number,
            "current_npc": self.get_current_npc(),
            "queue": self.get_queue(),
        }

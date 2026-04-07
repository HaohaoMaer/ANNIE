"""Phase Controller - Manages game phases and transitions.

Controls the progression through different stages of the murder mystery.
"""

from __future__ import annotations

from datetime import timedelta
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class PhaseStatus(str, Enum):
    """Status of a game phase."""

    UPCOMING = "upcoming"
    ACTIVE = "active"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class Phase(BaseModel):
    """A game phase with specific rules and allowed actions."""

    id: str
    name: str
    description: str = ""
    allowed_actions: list[str] = Field(default_factory=list)
    duration: timedelta | None = None
    npc_order: list[str] = Field(default_factory=list)
    objectives: list[str] = Field(default_factory=list)
    status: PhaseStatus = PhaseStatus.UPCOMING
    metadata: dict[str, Any] = Field(default_factory=dict)


class PhaseController:
    """Controls game phase progression."""

    def __init__(self, phases: list[Phase] | None = None) -> None:
        """Initialize the phase controller.

        Args:
            phases: List of game phases.
        """
        self._phases: list[Phase] = phases or []
        self._current_phase_index: int = -1
        self._phase_history: list[str] = []

        if self._phases:
            self._phases[0].status = PhaseStatus.ACTIVE
            self._current_phase_index = 0

    def get_current_phase(self) -> Phase | None:
        """Get the current active phase.

        Returns:
            Current phase, or None if no phase is active.
        """
        if 0 <= self._current_phase_index < len(self._phases):
            return self._phases[self._current_phase_index]
        return None

    def get_next_phase(self) -> Phase | None:
        """Get the next phase.

        Returns:
            Next phase, or None if at the last phase.
        """
        next_index = self._current_phase_index + 1
        if 0 <= next_index < len(self._phases):
            return self._phases[next_index]
        return None

    def advance_phase(self) -> bool:
        """Advance to the next phase.

        Returns:
            True if advanced successfully, False if at the last phase.
        """
        current = self.get_current_phase()
        if current:
            current.status = PhaseStatus.COMPLETED
            self._phase_history.append(current.id)

        next_index = self._current_phase_index + 1
        if next_index < len(self._phases):
            self._current_phase_index = next_index
            self._phases[next_index].status = PhaseStatus.ACTIVE
            return True

        return False

    def is_action_allowed(self, action: str) -> bool:
        """Check if an action is allowed in the current phase.

        Args:
            action: The action to check.

        Returns:
            True if allowed, False otherwise.
        """
        current = self.get_current_phase()
        if not current:
            return False

        action_lower = action.lower()
        for allowed in current.allowed_actions:
            if allowed.lower() in action_lower or action_lower in allowed.lower():
                return True

        return False

    def get_allowed_actions(self) -> list[str]:
        """Get list of allowed actions in current phase.

        Returns:
            List of allowed action names.
        """
        current = self.get_current_phase()
        if not current:
            return []
        return current.allowed_actions

    def set_npc_order(self, npc_order: list[str]) -> None:
        """Set the NPC action order for the current phase.

        Args:
            npc_order: List of NPC names in order.
        """
        current = self.get_current_phase()
        if current:
            current.npc_order = npc_order

    def get_npc_order(self) -> list[str]:
        """Get the NPC action order for the current phase.

        Returns:
            List of NPC names in order.
        """
        current = self.get_current_phase()
        if not current:
            return []
        return current.npc_order

    def add_phase(self, phase: Phase, index: int | None = None) -> None:
        """Add a new phase.

        Args:
            phase: The phase to add.
            index: Position to insert (None = append).
        """
        if index is None:
            self._phases.append(phase)
        else:
            self._phases.insert(index, phase)

    def remove_phase(self, phase_id: str) -> bool:
        """Remove a phase by ID.

        Args:
            phase_id: ID of phase to remove.

        Returns:
            True if removed, False if not found.
        """
        for i, phase in enumerate(self._phases):
            if phase.id == phase_id:
                self._phases.pop(i)
                if i < self._current_phase_index:
                    self._current_phase_index -= 1
                return True
        return False

    def get_phase_by_id(self, phase_id: str) -> Phase | None:
        """Get a phase by ID.

        Args:
            phase_id: ID of the phase.

        Returns:
            The phase, or None if not found.
        """
        for phase in self._phases:
            if phase.id == phase_id:
                return phase
        return None

    def get_phase_by_name(self, name: str) -> Phase | None:
        """Get a phase by name.

        Args:
            name: Name of the phase.

        Returns:
            The phase, or None if not found.
        """
        for phase in self._phases:
            if phase.name == name:
                return phase
        return None

    def get_all_phases(self) -> list[Phase]:
        """Get all phases.

        Returns:
            List of all phases.
        """
        return self._phases

    def get_phase_count(self) -> int:
        """Get total number of phases.

        Returns:
            Number of phases.
        """
        return len(self._phases)

    def get_current_phase_number(self) -> int:
        """Get the current phase number (1-indexed).

        Returns:
            Current phase number, or 0 if no phase is active.
        """
        return self._current_phase_index + 1

    def is_last_phase(self) -> bool:
        """Check if currently in the last phase.

        Returns:
            True if in last phase, False otherwise.
        """
        return self._current_phase_index == len(self._phases) - 1

    def is_game_over(self) -> bool:
        """Check if all phases are completed.

        Returns:
            True if game is over, False otherwise.
        """
        return self._current_phase_index >= len(self._phases) - 1 and \
               self.get_current_phase() is not None and \
               self.get_current_phase().status == PhaseStatus.COMPLETED

    def reset(self) -> None:
        """Reset to the first phase."""
        for phase in self._phases:
            phase.status = PhaseStatus.UPCOMING

        if self._phases:
            self._phases[0].status = PhaseStatus.ACTIVE
            self._current_phase_index = 0
        else:
            self._current_phase_index = -1

        self._phase_history.clear()

    def get_phase_history(self) -> list[str]:
        """Get list of completed phase IDs.

        Returns:
            List of phase IDs in completion order.
        """
        return self._phase_history.copy()

    def skip_to_phase(self, phase_id: str) -> bool:
        """Skip directly to a specific phase.

        Args:
            phase_id: ID of the phase to skip to.

        Returns:
            True if successful, False if phase not found.
        """
        for i, phase in enumerate(self._phases):
            if phase.id == phase_id:
                current = self.get_current_phase()
                if current:
                    current.status = PhaseStatus.SKIPPED

                for j in range(self._current_phase_index + 1, i):
                    self._phases[j].status = PhaseStatus.SKIPPED
                    self._phase_history.append(self._phases[j].id)

                self._current_phase_index = i
                phase.status = PhaseStatus.ACTIVE
                return True
        return False

    def get_phase_progress(self) -> float:
        """Get progress through all phases.

        Returns:
            Progress as a float between 0 and 1.
        """
        if not self._phases:
            return 0.0

        return (self._current_phase_index + 1) / len(self._phases)

    def to_dict(self) -> dict:
        """Export phase controller state to a dictionary.

        Returns:
            Dictionary representation.
        """
        return {
            "phases": [p.model_dump() for p in self._phases],
            "current_phase_index": self._current_phase_index,
            "phase_history": self._phase_history,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PhaseController:
        """Create a PhaseController from a dictionary.

        Args:
            data: Dictionary representation.

        Returns:
            PhaseController instance.
        """
        phases = [Phase(**p) for p in data.get("phases", [])]
        controller = cls(phases)
        controller._current_phase_index = data.get("current_phase_index", -1)
        controller._phase_history = data.get("phase_history", [])
        return controller

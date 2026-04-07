"""Script Progression - Manages plot points and story progression.

Tracks and triggers plot points based on game state.
"""

from __future__ import annotations

from datetime import datetime, UTC
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class PlotPointStatus(str, Enum):
    """Status of a plot point."""

    LOCKED = "locked"
    AVAILABLE = "available"
    TRIGGERED = "triggered"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class PlotPoint(BaseModel):
    """A key plot point in the story."""

    id: str
    name: str
    description: str = ""
    trigger_conditions: list[str] = Field(default_factory=list)
    consequences: list[str] = Field(default_factory=list)
    required_items: list[str] = Field(default_factory=list)
    required_knowledge: list[str] = Field(default_factory=list)
    phase: str = ""
    optional: bool = False
    status: PlotPointStatus = PlotPointStatus.LOCKED
    triggered_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BranchingPath(BaseModel):
    """A branching story path."""

    id: str
    name: str
    description: str = ""
    required_plot_points: list[str] = Field(default_factory=list)
    excluded_plot_points: list[str] = Field(default_factory=list)
    available: bool = True


class ScriptProgression:
    """Manages story progression and plot points."""

    def __init__(self, plot_points: list[PlotPoint] | None = None) -> None:
        """Initialize script progression.

        Args:
            plot_points: List of plot points in the story.
        """
        self._plot_points: dict[str, PlotPoint] = {}
        self._branches: dict[str, BranchingPath] = {}
        self._triggered_points: list[str] = []
        self._completed_points: list[str] = []
        self._current_branch: str | None = None

        if plot_points:
            for pp in plot_points:
                self._plot_points[pp.id] = pp

    def check_triggers(self, world_state: dict) -> list[PlotPoint]:
        """Check which plot points should be triggered.

        Args:
            world_state: Current world state including:
                - discovered_items: list of discovered items
                - known_facts: list of known facts
                - current_phase: current game phase
                - npc_states: dict of NPC states

        Returns:
            List of plot points that should be triggered.
        """
        triggered = []

        for pp in self._plot_points.values():
            if pp.status != PlotPointStatus.LOCKED:
                continue

            if self._check_conditions(pp, world_state):
                pp.status = PlotPointStatus.AVAILABLE
                triggered.append(pp)

        return triggered

    def _check_conditions(self, plot_point: PlotPoint, world_state: dict) -> bool:
        """Check if plot point conditions are met."""
        if plot_point.phase:
            current_phase = world_state.get("current_phase", "")
            if plot_point.phase.lower() not in current_phase.lower():
                return False

        discovered_items = set(world_state.get("discovered_items", []))
        for item in plot_point.required_items:
            if item not in discovered_items:
                return False

        known_facts = set(world_state.get("known_facts", []))
        for knowledge in plot_point.required_knowledge:
            if knowledge not in known_facts:
                return False

        for condition in plot_point.trigger_conditions:
            if not self._evaluate_condition(condition, world_state):
                return False

        return True

    def _evaluate_condition(self, condition: str, world_state: dict) -> bool:
        """Evaluate a single condition."""
        condition_lower = condition.lower()

        if "npc_" in condition_lower:
            npc_name = condition.split("_")[1] if "_" in condition else ""
            npc_states = world_state.get("npc_states", {})
            if npc_name in npc_states:
                return True

        if "time_" in condition_lower:
            return True

        return True

    def trigger_plot_point(self, plot_point_id: str) -> PlotPoint | None:
        """Manually trigger a plot point.

        Args:
            plot_point_id: ID of the plot point to trigger.

        Returns:
            The triggered plot point, or None if not found.
        """
        pp = self._plot_points.get(plot_point_id)
        if not pp:
            return None

        pp.status = PlotPointStatus.TRIGGERED
        pp.triggered_at = datetime.now(UTC)
        self._triggered_points.append(plot_point_id)

        return pp

    def complete_plot_point(self, plot_point_id: str) -> bool:
        """Mark a plot point as completed.

        Args:
            plot_point_id: ID of the plot point.

        Returns:
            True if completed, False if not found.
        """
        pp = self._plot_points.get(plot_point_id)
        if not pp:
            return False

        pp.status = PlotPointStatus.COMPLETED
        pp.completed_at = datetime.now(UTC)
        self._completed_points.append(plot_point_id)

        return True

    def get_available_plot_points(self) -> list[PlotPoint]:
        """Get all available plot points.

        Returns:
            List of available plot points.
        """
        return [
            pp for pp in self._plot_points.values()
            if pp.status == PlotPointStatus.AVAILABLE
        ]

    def get_triggered_plot_points(self) -> list[PlotPoint]:
        """Get all triggered but not completed plot points.

        Returns:
            List of triggered plot points.
        """
        return [
            pp for pp in self._plot_points.values()
            if pp.status == PlotPointStatus.TRIGGERED
        ]

    def get_completed_plot_points(self) -> list[PlotPoint]:
        """Get all completed plot points.

        Returns:
            List of completed plot points.
        """
        return [
            pp for pp in self._plot_points.values()
            if pp.status == PlotPointStatus.COMPLETED
        ]

    def get_plot_point(self, plot_point_id: str) -> PlotPoint | None:
        """Get a specific plot point.

        Args:
            plot_point_id: ID of the plot point.

        Returns:
            The plot point, or None if not found.
        """
        return self._plot_points.get(plot_point_id)

    def add_plot_point(self, plot_point: PlotPoint) -> None:
        """Add a new plot point.

        Args:
            plot_point: The plot point to add.
        """
        self._plot_points[plot_point.id] = plot_point

    def remove_plot_point(self, plot_point_id: str) -> bool:
        """Remove a plot point.

        Args:
            plot_point_id: ID of the plot point to remove.

        Returns:
            True if removed, False if not found.
        """
        if plot_point_id in self._plot_points:
            del self._plot_points[plot_point_id]
            return True
        return False

    def add_branch(self, branch: BranchingPath) -> None:
        """Add a branching path.

        Args:
            branch: The branch to add.
        """
        self._branches[branch.id] = branch

    def get_available_branches(self) -> list[BranchingPath]:
        """Get all available story branches.

        Returns:
            List of available branches.
        """
        available = []
        for branch in self._branches.values():
            if not branch.available:
                continue

            required_met = all(
                pp_id in self._completed_points
                for pp_id in branch.required_plot_points
            )

            excluded_met = all(
                pp_id not in self._completed_points
                for pp_id in branch.excluded_plot_points
            )

            if required_met and excluded_met:
                available.append(branch)

        return available

    def set_current_branch(self, branch_id: str) -> bool:
        """Set the current story branch.

        Args:
            branch_id: ID of the branch.

        Returns:
            True if set, False if not found.
        """
        if branch_id in self._branches:
            self._current_branch = branch_id
            return True
        return False

    def get_current_branch(self) -> BranchingPath | None:
        """Get the current story branch.

        Returns:
            Current branch, or None if not set.
        """
        if self._current_branch:
            return self._branches.get(self._current_branch)
        return None

    def get_progress(self) -> float:
        """Get story progress as a percentage.

        Returns:
            Progress between 0 and 1.
        """
        if not self._plot_points:
            return 0.0

        total = len(self._plot_points)
        completed = len(self._completed_points)

        return completed / total

    def get_progress_summary(self) -> dict[str, int]:
        """Get a summary of plot point statuses.

        Returns:
            Dict with counts of each status.
        """
        summary = {
            "locked": 0,
            "available": 0,
            "triggered": 0,
            "completed": 0,
            "skipped": 0,
        }

        for pp in self._plot_points.values():
            summary[pp.status.value] += 1

        return summary

    def get_consequences(self, plot_point_id: str) -> list[str]:
        """Get consequences of a plot point.

        Args:
            plot_point_id: ID of the plot point.

        Returns:
            List of consequence descriptions.
        """
        pp = self._plot_points.get(plot_point_id)
        if not pp:
            return []
        return pp.consequences

    def reset(self) -> None:
        """Reset all plot points to locked status."""
        for pp in self._plot_points.values():
            pp.status = PlotPointStatus.LOCKED
            pp.triggered_at = None
            pp.completed_at = None

        self._triggered_points.clear()
        self._completed_points.clear()
        self._current_branch = None

    def to_dict(self) -> dict:
        """Export to dictionary.

        Returns:
            Dictionary representation.
        """
        return {
            "plot_points": {
                pp_id: pp.model_dump()
                for pp_id, pp in self._plot_points.items()
            },
            "branches": {
                b_id: b.model_dump()
                for b_id, b in self._branches.items()
            },
            "triggered_points": self._triggered_points,
            "completed_points": self._completed_points,
            "current_branch": self._current_branch,
        }

"""Motivation Engine - Generates and prioritizes NPC motivations.

Motivations drive NPC behavior and decision-making.
"""

from __future__ import annotations

from datetime import datetime, timedelta, UTC
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from annie.npc.state import NPCProfile


class MotivationSource(str, Enum):
    """Source of a motivation."""

    SCRIPT = "script"
    EVENT = "event"
    RELATIONSHIP = "relationship"
    GOAL = "goal"
    EMOTION = "emotion"
    SURVIVAL = "survival"


class MotivationType(str, Enum):
    """Type of motivation."""

    ACHIEVEMENT = "achievement"
    SOCIAL = "social"
    INVESTIGATION = "investigation"
    PROTECTION = "protection"
    DECEPTION = "deception"
    DISCOVERY = "discovery"
    REVENGE = "revenge"
    LOVE = "love"
    FEAR = "fear"
    GREED = "greed"


class Motivation(BaseModel):
    """A single motivation driving NPC behavior."""

    goal: str
    description: str = ""
    intensity: float = Field(default=0.5, ge=0.0, le=1.0)
    source: MotivationSource = MotivationSource.GOAL
    motivation_type: MotivationType = MotivationType.ACHIEVEMENT
    deadline: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    target: str | None = None
    context: dict = Field(default_factory=dict)

    def is_expired(self) -> bool:
        """Check if this motivation has expired."""
        if self.deadline is None:
            return False
        return datetime.now(UTC) > self.deadline

    def decay(self, amount: float = 0.1) -> None:
        """Reduce motivation intensity over time."""
        self.intensity = max(0.0, self.intensity - amount)


class MotivationEngine:
    """Generates and manages NPC motivations."""

    def __init__(self) -> None:
        self._motivations: list[Motivation] = []
        self._motivation_history: list[Motivation] = []

    def generate_motivations(
        self,
        npc_profile: NPCProfile,
        context: dict,
    ) -> list[Motivation]:
        """Generate motivations based on NPC profile and current context.

        Args:
            npc_profile: The NPC's character profile.
            context: Current situation context including events, relationships, etc.

        Returns:
            List of generated motivations.
        """
        motivations = []

        motivations.extend(self._generate_from_goals(npc_profile))

        motivations.extend(self._generate_from_events(context))

        motivations.extend(self._generate_from_relationships(npc_profile, context))

        motivations.extend(self._generate_from_script(context))

        self._motivations = motivations
        return motivations

    def _generate_from_goals(self, npc_profile: NPCProfile) -> list[Motivation]:
        """Generate motivations from NPC's goals."""
        motivations = []

        for goal in npc_profile.goals.short_term:
            motivations.append(
                Motivation(
                    goal=goal,
                    source=MotivationSource.GOAL,
                    motivation_type=MotivationType.ACHIEVEMENT,
                    intensity=0.7,
                )
            )

        for goal in npc_profile.goals.long_term:
            motivations.append(
                Motivation(
                    goal=goal,
                    source=MotivationSource.GOAL,
                    motivation_type=MotivationType.ACHIEVEMENT,
                    intensity=0.5,
                )
            )

        return motivations

    def _generate_from_events(self, context: dict) -> list[Motivation]:
        """Generate motivations from current events."""
        motivations = []

        current_event = context.get("current_event")
        if current_event:
            motivations.append(
                Motivation(
                    goal=f"Respond to event: {current_event[:50]}",
                    description=current_event,
                    source=MotivationSource.EVENT,
                    motivation_type=MotivationType.INVESTIGATION,
                    intensity=0.8,
                )
            )

        threats = context.get("threats", [])
        for threat in threats:
            motivations.append(
                Motivation(
                    goal=f"Protect self from {threat}",
                    source=MotivationSource.SURVIVAL,
                    motivation_type=MotivationType.PROTECTION,
                    intensity=0.9,
                )
            )

        return motivations

    def _generate_from_relationships(
        self,
        npc_profile: NPCProfile,
        context: dict,
    ) -> list[Motivation]:
        """Generate motivations from relationships."""
        motivations = []

        for rel in npc_profile.relationships:
            rel_type = rel.type.lower()

            if "friend" in rel_type or "ally" in rel_type:
                motivations.append(
                    Motivation(
                        goal=f"Help {rel.target}",
                        target=rel.target,
                        source=MotivationSource.RELATIONSHIP,
                        motivation_type=MotivationType.SOCIAL,
                        intensity=rel.intensity * 0.8,
                    )
                )
            elif "enemy" in rel_type or "rival" in rel_type:
                motivations.append(
                    Motivation(
                        goal=f"Oppose {rel.target}",
                        target=rel.target,
                        source=MotivationSource.RELATIONSHIP,
                        motivation_type=MotivationType.REVENGE,
                        intensity=rel.intensity * 0.7,
                    )
                )

        return motivations

    def _generate_from_script(self, context: dict) -> list[Motivation]:
        """Generate motivations from script-specific requirements."""
        motivations = []

        script_tasks = context.get("script_tasks", [])
        for task in script_tasks:
            motivations.append(
                Motivation(
                    goal=task.get("description", "Complete script task"),
                    source=MotivationSource.SCRIPT,
                    motivation_type=MotivationType.ACHIEVEMENT,
                    intensity=task.get("priority", 0.6),
                    deadline=task.get("deadline"),
                )
            )

        return motivations

    def prioritize(self, motivations: list[Motivation] | None = None) -> list[Motivation]:
        """Prioritize motivations by intensity and urgency.

        Args:
            motivations: List to prioritize (uses internal list if None).

        Returns:
            Sorted list of motivations.
        """
        if motivations is None:
            motivations = self._motivations

        valid_motivations = [m for m in motivations if not m.is_expired()]

        def sort_key(m: Motivation) -> tuple[float, float]:
            urgency = 0.0
            if m.deadline:
                time_until = (m.deadline - datetime.now(UTC)).total_seconds()
                if time_until < 3600:
                    urgency = 1.0
                elif time_until < 86400:
                    urgency = 0.7
                else:
                    urgency = 0.3

            return (-m.intensity, -urgency)

        return sorted(valid_motivations, key=sort_key)

    def get_primary_motivation(self) -> Motivation | None:
        """Get the highest priority motivation.

        Returns:
            The primary motivation, or None if no motivations exist.
        """
        prioritized = self.prioritize()
        return prioritized[0] if prioritized else None

    def add_motivation(self, motivation: Motivation) -> None:
        """Add a new motivation."""
        self._motivations.append(motivation)

    def remove_motivation(self, goal: str) -> bool:
        """Remove a motivation by goal description.

        Args:
            goal: Goal description to match.

        Returns:
            True if motivation was removed, False if not found.
        """
        for i, m in enumerate(self._motivations):
            if m.goal == goal:
                removed = self._motivations.pop(i)
                self._motivation_history.append(removed)
                return True
        return False

    def get_motivations_by_type(
        self,
        motivation_type: MotivationType,
    ) -> list[Motivation]:
        """Get all motivations of a specific type."""
        return [
            m for m in self._motivations
            if m.motivation_type == motivation_type
        ]

    def get_motivations_by_target(self, target: str) -> list[Motivation]:
        """Get all motivations related to a specific target."""
        return [
            m for m in self._motivations
            if m.target == target
        ]

    def decay_all(self, amount: float = 0.05) -> None:
        """Decay all motivation intensities."""
        for m in self._motivations:
            m.decay(amount)

        self._motivations = [m for m in self._motivations if m.intensity > 0.1]

    def get_active_count(self) -> int:
        """Get number of active motivations."""
        return len([m for m in self._motivations if not m.is_expired()])

    def clear_completed(self) -> int:
        """Remove expired motivations.

        Returns:
            Number of motivations removed.
        """
        before = len(self._motivations)
        self._motivations = [m for m in self._motivations if not m.is_expired()]
        return before - len(self._motivations)

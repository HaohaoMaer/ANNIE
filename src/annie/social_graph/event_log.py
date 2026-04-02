"""Event Log - Append-only log of social events (Actor -> Target -> Action).

The single source of truth for *what actually happened* in the world.
KnowledgeItems (what NPCs *believe* happened) are derived from these events
by the PropagationEngine and Perception Pipeline.
"""

from __future__ import annotations

from datetime import datetime

from annie.social_graph.models import EventVisibility, SocialEvent


class SocialEventLog:
    """Append-only event store."""

    def __init__(self) -> None:
        self._events: list[SocialEvent] = []
        self._index: dict[str, SocialEvent] = {}  # id -> event

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def append(self, event: SocialEvent) -> str:
        """Append an event and return its ID."""
        self._events.append(event)
        self._index[event.id] = event
        return event.id

    def load_preset_events(self, events: list[SocialEvent]) -> None:
        """Bulk-load historical events (for demo seeding)."""
        for event in events:
            self.append(event)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, event_id: str) -> SocialEvent | None:
        """Lookup a single event by ID."""
        return self._index.get(event_id)

    def get_by_actor(self, actor: str) -> list[SocialEvent]:
        """Events where *actor* is the primary actor."""
        return [e for e in self._events if e.actor == actor]

    def get_by_target(self, target: str) -> list[SocialEvent]:
        """Events where *target* is the affected party."""
        return [e for e in self._events if e.target == target]

    def get_by_timerange(
        self, start: datetime, end: datetime
    ) -> list[SocialEvent]:
        """Events whose timestamp falls within [start, end]."""
        return [e for e in self._events if start <= e.timestamp <= end]

    def get_recent(self, n: int = 10) -> list[SocialEvent]:
        """Return the *n* most recent events (newest last)."""
        return self._events[-n:]

    def get_by_visibility(self, visibility: EventVisibility) -> list[SocialEvent]:
        """Filter events by visibility level."""
        return [e for e in self._events if e.visibility == visibility]

    def all_events(self) -> list[SocialEvent]:
        """Return all events in insertion order."""
        return list(self._events)

    def __len__(self) -> int:
        return len(self._events)

"""Event routing and NPC registration helpers for town simulation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from annie.town.domain import TownEvent, TownState


@dataclass
class NPCRecord:
    npc_id: str
    location_id: str | None = None
    active: bool = True


class NPCRegistry:
    """Small world-owned registry for town NPC activation."""

    def __init__(self, records: Iterable[NPCRecord] | None = None) -> None:
        self._records: dict[str, NPCRecord] = {}
        for record in records or []:
            self.register(record.npc_id, location_id=record.location_id, active=record.active)

    @classmethod
    def from_state(cls, state: TownState) -> "NPCRegistry":
        registry = cls()
        registry.sync_from_state(state)
        return registry

    def register(
        self,
        npc_id: str,
        *,
        location_id: str | None = None,
        active: bool = True,
    ) -> NPCRecord:
        record = self._records.get(npc_id)
        if record is None:
            record = NPCRecord(npc_id=npc_id, location_id=location_id, active=active)
            self._records[npc_id] = record
            return record
        record.location_id = location_id
        record.active = active
        return record

    def set_active(self, npc_id: str, active: bool) -> None:
        record = self._records.get(npc_id)
        if record is None:
            record = self.register(npc_id)
        record.active = active

    def location_for(self, npc_id: str) -> str | None:
        record = self._records.get(npc_id)
        return record.location_id if record is not None else None

    def sync_from_state(self, state: TownState) -> None:
        resident_ids = state.resident_ids()
        for npc_id in resident_ids:
            location_id = state.location_id_for(npc_id)
            active = self._records.get(npc_id, NPCRecord(npc_id)).active
            self.register(npc_id, location_id=location_id, active=active)
        for npc_id, record in self._records.items():
            if npc_id not in resident_ids:
                record.location_id = None

    def active_ids(self, requested_ids: Iterable[str] | None = None) -> list[str]:
        ids = list(requested_ids) if requested_ids is not None else list(self._records)
        return [
            npc_id
            for npc_id in ids
            if self._records.get(npc_id, NPCRecord(npc_id, active=True)).active
        ]


class TownEventBus:
    """Routes targeted events and tracks per-NPC local event deduplication."""

    def __init__(self) -> None:
        self.inboxes: dict[str, list[TownEvent]] = {}
        self.seen_event_ids: dict[str, set[str]] = {}

    def publish(self, event: TownEvent) -> None:
        for target_id in event.target_ids:
            self.publish_to(target_id, event)

    def publish_to(self, npc_id: str, event: TownEvent) -> None:
        self.inboxes.setdefault(npc_id, []).append(event)

    def drain(self, npc_id: str) -> list[TownEvent]:
        events = list(self.inboxes.get(npc_id, []))
        self.inboxes[npc_id] = []
        return events

    def mark_seen(self, npc_id: str, event_ids: Iterable[str]) -> None:
        seen = self.seen_event_ids.setdefault(npc_id, set())
        seen.update(event_ids)

    def unseen_visible_events(
        self,
        npc_id: str,
        events: Iterable[TownEvent],
        *,
        should_activate: Callable[[TownEvent], bool],
    ) -> list[TownEvent]:
        seen = self.seen_event_ids.setdefault(npc_id, set())
        return [
            event
            for event in events
            if event.id not in seen and should_activate(event)
        ]

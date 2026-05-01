"""Mutable semantic town state owned by the world engine layer."""

from __future__ import annotations

from dataclasses import dataclass, field

from annie.town.domain.models import (
    ConversationSession,
    CurrentAction,
    Location,
    MoveResult,
    ScheduleCompletion,
    ScheduleSegment,
    TownClock,
    TownEvent,
    TownObject,
    TownResidentState,
)


@dataclass
class TownState:
    """World-owned aggregate for semantic town simulation state."""

    clock: TownClock = field(default_factory=TownClock)
    locations: dict[str, Location] = field(default_factory=dict)
    objects: dict[str, TownObject] = field(default_factory=dict)
    events: list[TownEvent] = field(default_factory=list)
    schedules: dict[str, list[ScheduleSegment]] = field(default_factory=dict)
    current_actions: dict[str, CurrentAction] = field(default_factory=dict)
    conversation_sessions: dict[str, ConversationSession] = field(default_factory=dict)
    conversation_cooldowns: dict[str, int] = field(default_factory=dict)
    completed_schedule_segments: dict[str, list[ScheduleCompletion]] = field(default_factory=dict)
    npc_locations: dict[str, str] = field(default_factory=dict)
    residents: dict[str, TownResidentState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._initialize_residents()
        self._sync_legacy_mirrors()
        self.sync_occupants()

    def _initialize_residents(self) -> None:
        npc_ids = set(self.residents) | set(self.npc_locations) | set(self.schedules) | set(
            self.current_actions
        )
        for npc_id in sorted(npc_ids):
            resident = self.residents.get(npc_id)
            if resident is None:
                location_id = self.npc_locations.get(npc_id, "")
                schedule = self.schedules.get(npc_id, [])
                for segment in schedule:
                    if segment.day is None:
                        segment.day = self.clock.day
                resident = TownResidentState(
                    npc_id=npc_id,
                    location_id=location_id,
                    schedule=schedule,
                    schedule_day=self.clock.day if schedule else None,
                    current_action=self.current_actions.get(npc_id),
                )
                self.residents[npc_id] = resident
                continue
            if not resident.location_id and npc_id in self.npc_locations:
                resident.location_id = self.npc_locations[npc_id]
            if not resident.schedule and npc_id in self.schedules:
                resident.schedule = self.schedules[npc_id]
            if resident.schedule_day is None and resident.schedule:
                resident.schedule_day = self.clock.day
            for segment in resident.schedule:
                if segment.day is None:
                    segment.day = resident.schedule_day
            if resident.current_action is None and npc_id in self.current_actions:
                resident.current_action = self.current_actions[npc_id]

    def _sync_legacy_mirrors(self) -> None:
        self.npc_locations = {
            npc_id: resident.location_id
            for npc_id, resident in self.residents.items()
            if resident.location_id
        }
        self.schedules = {
            npc_id: resident.schedule for npc_id, resident in self.residents.items()
        }
        self.current_actions = {
            npc_id: resident.current_action
            for npc_id, resident in self.residents.items()
            if resident.current_action is not None
        }

    def _sync_legacy_for_resident(self, npc_id: str) -> None:
        resident = self.residents.get(npc_id)
        if resident is None:
            return
        if resident.location_id:
            self.npc_locations[npc_id] = resident.location_id
        else:
            self.npc_locations.pop(npc_id, None)
        self.schedules[npc_id] = resident.schedule
        if resident.current_action is None:
            self.current_actions.pop(npc_id, None)
        else:
            self.current_actions[npc_id] = resident.current_action

    def resident_for(self, npc_id: str) -> TownResidentState | None:
        return self.residents.get(npc_id)

    def resident_ids(self) -> list[str]:
        return list(self.residents)

    def location_id_for(self, npc_id: str) -> str | None:
        resident = self.residents.get(npc_id)
        if resident is not None and resident.location_id:
            return resident.location_id
        return self.npc_locations.get(npc_id)

    def set_location(self, npc_id: str, location_id: str) -> None:
        previous_location_id = self.location_id_for(npc_id)
        resident = self.residents.get(npc_id)
        if resident is None:
            resident = TownResidentState(npc_id=npc_id, location_id=location_id)
            self.residents[npc_id] = resident
        else:
            resident.location_id = location_id
        self._sync_legacy_for_resident(npc_id)
        if previous_location_id != location_id:
            if previous_location_id is not None:
                previous_location = self.locations.get(previous_location_id)
                if previous_location is not None and npc_id in previous_location.occupant_ids:
                    previous_location.occupant_ids.remove(npc_id)
        location = self.locations.get(location_id)
        if location is not None and npc_id not in location.occupant_ids:
            location.occupant_ids.append(npc_id)

    def current_action_for(self, npc_id: str) -> CurrentAction | None:
        legacy_action = self.current_actions.get(npc_id)
        resident = self.residents.get(npc_id)
        if resident is None:
            return legacy_action
        if legacy_action is not None:
            resident.current_action = legacy_action
            return legacy_action
        if resident.current_action is not None:
            self.current_actions[npc_id] = resident.current_action
        return resident.current_action

    def set_current_action(self, npc_id: str, action: CurrentAction) -> None:
        resident = self.residents.get(npc_id)
        if resident is None:
            resident = TownResidentState(npc_id=npc_id, location_id=action.location_id)
            self.residents[npc_id] = resident
        resident.current_action = action
        self._sync_legacy_for_resident(npc_id)

    def clear_current_action(self, npc_id: str) -> None:
        resident = self.residents.get(npc_id)
        if resident is not None:
            resident.current_action = None
        self.current_actions.pop(npc_id, None)

    def set_schedule(
        self,
        npc_id: str,
        schedule: list[ScheduleSegment],
        *,
        day: int | None = None,
    ) -> None:
        resident = self.residents.get(npc_id)
        if resident is None:
            resident = TownResidentState(
                npc_id=npc_id,
                location_id=self.npc_locations.get(npc_id, ""),
            )
            self.residents[npc_id] = resident
        schedule_day = self.clock.day if day is None else day
        for segment in schedule:
            segment.day = schedule_day
        resident.schedule = schedule
        resident.schedule_day = schedule_day
        self._sync_legacy_for_resident(npc_id)

    def sync_occupants(self) -> None:
        """Rebuild location occupants from resident locations."""
        for location in self.locations.values():
            location.occupant_ids.clear()
        for npc_id in {*self.resident_ids(), *self.npc_locations}:
            location_id = self.location_id_for(npc_id)
            if location_id is not None:
                location = self.locations.get(location_id)
                if location is not None and npc_id not in location.occupant_ids:
                    location.occupant_ids.append(npc_id)

    def location_for(self, npc_id: str) -> Location | None:
        location_id = self.location_id_for(npc_id)
        if location_id is None:
            return None
        return self.locations.get(location_id)

    def occupants_at(self, location_id: str) -> list[str]:
        location = self.locations.get(location_id)
        if location is None:
            return []
        return list(location.occupant_ids)

    def objects_at(self, location_id: str) -> list[TownObject]:
        location = self.locations.get(location_id)
        if location is None:
            return []
        return [self.objects[obj_id] for obj_id in location.object_ids if obj_id in self.objects]

    def reachable_locations(self, location_id: str) -> list[Location]:
        location = self.locations.get(location_id)
        if location is None:
            return []
        return [self.locations[exit_id] for exit_id in location.exits if exit_id in self.locations]

    def move_npc(self, npc_id: str, destination_id: str) -> MoveResult:
        origin_id = self.location_id_for(npc_id)
        if origin_id is None:
            return MoveResult(
                ok=False,
                npc_id=npc_id,
                from_location_id=None,
                reason="unknown_npc",
            )

        origin = self.locations.get(origin_id)
        destination = self.locations.get(destination_id)
        reachable = [location.id for location in self.reachable_locations(origin_id)]

        if origin is None:
            return MoveResult(
                ok=False,
                npc_id=npc_id,
                from_location_id=origin_id,
                reason="unknown_current_location",
                reachable=reachable,
            )
        if destination is None:
            return MoveResult(
                ok=False,
                npc_id=npc_id,
                from_location_id=origin_id,
                reason="unknown_destination",
                reachable=reachable,
            )
        if destination_id not in reachable:
            return MoveResult(
                ok=False,
                npc_id=npc_id,
                from_location_id=origin_id,
                to_location_id=destination_id,
                reason="unreachable_destination",
                reachable=reachable,
            )

        if npc_id in origin.occupant_ids:
            origin.occupant_ids.remove(npc_id)
        if npc_id not in destination.occupant_ids:
            destination.occupant_ids.append(npc_id)
        self.set_location(npc_id, destination_id)

        return MoveResult(
            ok=True,
            npc_id=npc_id,
            from_location_id=origin_id,
            to_location_id=destination_id,
            reachable=[location.id for location in self.reachable_locations(destination_id)],
            travel_minutes=origin.exit_travel_minutes.get(destination_id),
        )

    def schedule_for(self, npc_id: str) -> list[ScheduleSegment]:
        resident = self.residents.get(npc_id)
        if resident is not None:
            return list(resident.schedule)
        return list(self.schedules.get(npc_id, []))

    def current_schedule_segment(
        self,
        npc_id: str,
        minute: int | None = None,
    ) -> ScheduleSegment | None:
        resident = self.residents.get(npc_id)
        if (
            resident is not None
            and resident.schedule_day is not None
            and resident.schedule_day != self.clock.day
        ):
            return None
        check_minute = self.clock.minute if minute is None else minute
        for segment in self.schedule_for(npc_id):
            if segment.contains(check_minute):
                return segment
        return None

    def complete_schedule_segment(
        self,
        npc_id: str,
        segment: ScheduleSegment | None = None,
        note: str = "",
    ) -> ScheduleCompletion | None:
        target = segment or self.current_schedule_segment(npc_id)
        if target is None:
            return None
        completion = ScheduleCompletion(
            npc_id=npc_id,
            start_minute=target.start_minute,
            location_id=target.location_id,
            note=note,
            day=self.clock.day,
        )
        existing = self.completed_schedule_segments.setdefault(npc_id, [])
        for item in existing:
            item_day = self.clock.day if item.day is None else item.day
            if item.start_minute == completion.start_minute and item_day == self.clock.day:
                item.note = note or item.note
                item.day = self.clock.day
                return item
        existing.append(completion)
        return completion

    def is_schedule_segment_complete(self, npc_id: str, segment: ScheduleSegment) -> bool:
        return any(
            item.start_minute == segment.start_minute
            and (self.clock.day if item.day is None else item.day)
            == (self.clock.day if segment.day is None else segment.day)
            for item in self.completed_schedule_segments.get(npc_id, [])
        )

    def active_conversation_for(self, npc_id: str) -> ConversationSession | None:
        for session in self.conversation_sessions.values():
            if session.status == "active" and npc_id in session.participants:
                return session
        return None

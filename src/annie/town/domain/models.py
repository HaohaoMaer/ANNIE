"""Typed world-owned data models for the semantic town engine."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TownClock:
    """Simulation clock expressed as day plus minutes since midnight."""

    day: int = 1
    minute: int = 8 * 60
    stride_minutes: int = 10

    def label(self) -> str:
        hours, minutes = divmod(self.minute, 60)
        return f"第 {self.day} 天，{hours:02d}:{minutes:02d}"


@dataclass
class Location:
    id: str
    name: str
    description: str = ""
    exits: list[str] = field(default_factory=list)
    exit_travel_minutes: dict[str, int] = field(default_factory=dict)
    object_ids: list[str] = field(default_factory=list)
    occupant_ids: list[str] = field(default_factory=list)


@dataclass
class TownObject:
    id: str
    name: str
    location_id: str
    description: str = ""
    interactable: bool = True


@dataclass
class TownEvent:
    id: str
    minute: int
    location_id: str
    actor_id: str | None
    event_type: str
    summary: str
    visible: bool = True
    target_ids: list[str] = field(default_factory=list)


@dataclass
class ConversationTurn:
    speaker_id: str
    listener_id: str
    text: str
    minute: int


@dataclass
class ConversationSession:
    id: str
    participants: tuple[str, str]
    initiator_id: str
    location_id: str
    topic: str
    started_minute: int
    max_turns: int
    turns: list[ConversationTurn] = field(default_factory=list)
    status: str = "active"
    close_reason: str = ""
    ended_minute: int | None = None


@dataclass
class ScheduleSegment:
    npc_id: str
    start_minute: int
    duration_minutes: int
    location_id: str
    intent: str
    subtasks: list[str] = field(default_factory=list)

    @property
    def end_minute(self) -> int:
        return self.start_minute + self.duration_minutes

    def contains(self, minute: int) -> bool:
        return self.start_minute <= minute < self.end_minute


@dataclass
class ScheduleRevision:
    npc_id: str
    event_id: str
    reason: str
    inserted_segment: ScheduleSegment


@dataclass
class CurrentAction:
    npc_id: str
    action_type: str
    location_id: str
    start_minute: int
    duration_minutes: int
    status: str
    summary: str = ""

    @property
    def end_minute(self) -> int:
        return self.start_minute + self.duration_minutes


@dataclass
class ResidentScratch:
    currently: str = ""


@dataclass
class ResidentSpatialMemory:
    known_location_ids: list[str] = field(default_factory=list)
    known_object_ids: list[str] = field(default_factory=list)


@dataclass
class ReflectionEvidence:
    id: str
    evidence_type: str
    summary: str
    poignancy: int
    clock_minute: int
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TownPerceptionPolicy:
    max_events: int = 5
    max_objects: int = 5
    max_npcs: int = 5
    max_exits: int = 5
    max_known_locations: int = 8
    max_known_objects: int = 8


@dataclass
class TownResidentState:
    npc_id: str
    location_id: str
    schedule: list[ScheduleSegment] = field(default_factory=list)
    current_action: CurrentAction | None = None
    scratch: ResidentScratch = field(default_factory=ResidentScratch)
    spatial_memory: ResidentSpatialMemory = field(default_factory=ResidentSpatialMemory)
    poignancy: int = 0
    reflection_evidence: list[ReflectionEvidence] = field(default_factory=list)


@dataclass
class ScheduleCompletion:
    npc_id: str
    start_minute: int
    location_id: str
    note: str = ""


@dataclass
class MoveResult:
    ok: bool
    npc_id: str
    from_location_id: str | None
    to_location_id: str | None = None
    reason: str | None = None
    reachable: list[str] = field(default_factory=list)
    travel_minutes: int | None = None

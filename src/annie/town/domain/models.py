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
class SemanticAffordance:
    id: str
    label: str
    description: str = ""
    duration_minutes: int = 5
    aliases: list[str] = field(default_factory=list)
    event_type: str = "interaction"


@dataclass
class Location:
    id: str
    name: str
    description: str = ""
    exits: list[str] = field(default_factory=list)
    exit_travel_minutes: dict[str, int] = field(default_factory=dict)
    object_ids: list[str] = field(default_factory=list)
    occupant_ids: list[str] = field(default_factory=list)
    affordances: list[SemanticAffordance] = field(default_factory=list)


@dataclass
class TownObject:
    id: str
    name: str
    location_id: str
    description: str = ""
    interactable: bool = True
    affordances: list[SemanticAffordance] = field(default_factory=list)


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
    completion_tags: list[str] = field(default_factory=list)
    day: int | None = None
    completion_policy: str = "first_matching_action"
    min_matching_actions: int = 1
    allow_explicit_override: bool = True

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
    lifecycle_state: str = "in_progress"
    effect_model: str = "immediate_effect"
    occupancy_model: str = "duration_occupied"
    effect_applied: bool = True
    failure_reason: str | None = None
    interrupted_reason: str | None = None
    finalized_minute: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def end_minute(self) -> int:
        return self.start_minute + self.duration_minutes


@dataclass
class ResidentScratch:
    currently: str = ""


@dataclass
class ResidentPersona:
    currently: str = ""
    lifestyle: str = ""
    background: str = ""
    traits: list[str] = field(default_factory=list)
    relationships: dict[str, str] = field(default_factory=dict)


@dataclass
class ResidentDayPlan:
    day: int
    currently: str = ""
    wake_up_minute: int | None = None
    daily_intentions: list[str] = field(default_factory=list)
    planning_evidence: list[dict[str, object]] = field(default_factory=list)
    validation: dict[str, object] = field(default_factory=dict)
    schedule_summary: str = ""
    day_summary: str = ""
    schedule_evidence: list[dict[str, object]] = field(default_factory=list)
    started_minute: int | None = None
    ended_minute: int | None = None
    lifecycle_anomalies: list[dict[str, object]] = field(default_factory=list)


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
    max_exits: int = 4
    max_known_locations: int = 8
    max_known_objects: int = 8


@dataclass
class TownResidentState:
    npc_id: str
    location_id: str
    home_location_id: str | None = None
    sleep_location_id: str | None = None
    default_wake_window: tuple[int, int] | None = None
    default_sleep_window: tuple[int, int] | None = None
    lifecycle_status: str = "awake"
    schedule: list[ScheduleSegment] = field(default_factory=list)
    current_action: CurrentAction | None = None
    scratch: ResidentScratch = field(default_factory=ResidentScratch)
    persona: ResidentPersona = field(default_factory=ResidentPersona)
    schedule_day: int | None = None
    day_plans: dict[int, ResidentDayPlan] = field(default_factory=dict)
    spatial_memory: ResidentSpatialMemory = field(default_factory=ResidentSpatialMemory)
    poignancy: int = 0
    reflection_evidence: list[ReflectionEvidence] = field(default_factory=list)


@dataclass
class ScheduleCompletion:
    npc_id: str
    start_minute: int
    location_id: str
    note: str = ""
    day: int | None = None
    completion_type: str = "explicit"
    matched_action_id: str | None = None
    matched_action_type: str | None = None
    matching_reason: str = ""
    completion_policy: str = "first_matching_action"
    action_end_minute: int | None = None
    completion_reason: str = ""


@dataclass
class ScheduleSatisfaction:
    npc_id: str
    start_minute: int
    location_id: str
    day: int | None = None
    completion_policy: str = "first_matching_action"
    matched_action_id: str | None = None
    matched_action_type: str | None = None
    matching_reason: str = ""
    action_end_minute: int | None = None
    match_count: int = 1


@dataclass
class MoveResult:
    ok: bool
    npc_id: str
    from_location_id: str | None
    to_location_id: str | None = None
    reason: str | None = None
    reachable: list[str] = field(default_factory=list)
    travel_minutes: int | None = None

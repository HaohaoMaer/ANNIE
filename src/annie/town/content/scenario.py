"""Strict YAML scenario loading for semantic TownWorld content."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from annie.npc.memory.interface import MemoryInterface
from annie.town.domain import (
    Location,
    ResidentPersona,
    ResidentScratch,
    ResidentSpatialMemory,
    ScheduleSegment,
    SemanticAffordance,
    TownClock,
    TownObject,
    TownResidentState,
    TownState,
)

TOWN_SCENARIO_SCHEMA_VERSION = 1
SUPPORTED_MEMORY_SEED_CATEGORIES = {"semantic", "reflection", "impression", "todo"}

_TOP_LEVEL_KEYS = {
    "schema_version",
    "id",
    "name",
    "clock",
    "locations",
    "residents",
    "memory_seeds",
}
_CLOCK_KEYS = {"day", "minute", "stride_minutes"}
_LOCATION_KEYS = {
    "id",
    "name",
    "description",
    "exits",
    "objects",
    "affordances",
}
_EXIT_KEYS = {"to", "travel_minutes"}
_OBJECT_KEYS = {
    "id",
    "name",
    "description",
    "interactable",
    "affordances",
}
_AFFORDANCE_KEYS = {
    "id",
    "label",
    "description",
    "duration_minutes",
    "aliases",
    "event_type",
}
_RESIDENT_KEYS = {
    "id",
    "name",
    "starting_location",
    "home_location",
    "sleep_location",
    "default_wake_window",
    "default_sleep_window",
    "lifecycle_status",
    "persona",
    "relationships",
    "schedule",
    "known_locations",
    "known_objects",
    "memory_seeds",
}
_PERSONA_KEYS = {"currently", "lifestyle", "background", "traits"}
_SCHEDULE_KEYS = {
    "start_minute",
    "duration_minutes",
    "location",
    "intent",
    "subtasks",
    "completion_tags",
    "day",
    "completion_policy",
    "min_matching_actions",
    "allow_explicit_override",
}
_MEMORY_SEED_KEYS = {"id", "resident", "content", "category", "metadata"}


@dataclass(frozen=True)
class TownMemorySeed:
    id: str
    resident_id: str
    content: str
    category: str = "semantic"
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class LoadedTownScenario:
    id: str
    name: str
    path: Path
    state: TownState
    memory_seeds: list[TownMemorySeed]


@dataclass(frozen=True)
class TownScenarioScaleReport:
    scenario_id: str
    resident_count: int
    location_count: int
    memory_seed_count: int
    primary_hub_id: str
    checked_residents: list[str]


class TownScenarioValidationError(ValueError):
    """Raised when scenario content cannot be compiled into TownState."""


def default_small_town_scenario_path() -> Path:
    return Path(__file__).with_name("scenarios") / "small_town.yaml"


def default_replay_demo_scenario_path() -> Path:
    return Path(__file__).with_name("scenarios") / "replay_demo_town.yaml"


def default_scaled_town_scenario_path() -> Path:
    return Path(__file__).with_name("scenarios") / "generative_scale_town.yaml"


def load_town_scenario(path: str | Path) -> LoadedTownScenario:
    scenario_path = Path(path)
    try:
        with scenario_path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
    except OSError as exc:
        raise TownScenarioValidationError(f"cannot read scenario file: {scenario_path}") from exc
    data = _mapping(payload, "scenario")
    _assert_keys(data, _TOP_LEVEL_KEYS, "scenario")

    version = _required_int(data, "schema_version", "scenario")
    if version != TOWN_SCENARIO_SCHEMA_VERSION:
        raise TownScenarioValidationError(f"unsupported scenario schema_version: {version}")

    scenario_id = _required_str(data, "id", "scenario")
    name = _required_str(data, "name", "scenario")
    clock = _clock(data.get("clock", {}))
    locations, objects = _locations(_required_list(data, "locations", "scenario"))
    residents, memory_seeds = _residents(
        _required_list(data, "residents", "scenario"),
        locations=locations,
        objects=objects,
        default_day=clock.day,
    )
    memory_seeds.extend(_memory_seeds(data.get("memory_seeds", []), resident_id=None))
    _validate_graph(locations, objects, residents, memory_seeds)

    state = TownState(
        clock=clock,
        locations=locations,
        objects=objects,
        residents=residents,
    )
    return LoadedTownScenario(
        id=scenario_id,
        name=name,
        path=scenario_path,
        state=state,
        memory_seeds=memory_seeds,
    )


def load_town_state(path: str | Path) -> TownState:
    return load_town_scenario(path).state


def create_small_town_state_from_scenario() -> TownState:
    return load_town_state(default_small_town_scenario_path())


def apply_memory_seeds(
    scenario: LoadedTownScenario,
    memory_for: Callable[[str], MemoryInterface],
) -> None:
    for seed in scenario.memory_seeds:
        metadata = dict(seed.metadata or {})
        metadata.update(
            {
                "source": "town_scenario_seed",
                "scenario_id": scenario.id,
                "scenario_path": str(scenario.path),
                "seed_id": seed.id,
                "resident_id": seed.resident_id,
            }
        )
        memory_for(seed.resident_id).remember(
            seed.content,
            category=seed.category,
            metadata=metadata,
        )


def validate_scaled_town_scenario(
    scenario: LoadedTownScenario,
    *,
    min_residents: int = 25,
    min_locations: int = 20,
    primary_hub_id: str = "town_square",
    representative_resident_ids: Iterable[str] | None = None,
) -> TownScenarioScaleReport:
    """Validate structural contracts expected by scaled deterministic runs."""
    state = scenario.state
    if len(state.residents) < min_residents:
        raise TownScenarioValidationError(
            f"scaled scenario requires at least {min_residents} residents; found {len(state.residents)}"
        )
    if len(state.locations) < min_locations:
        raise TownScenarioValidationError(
            f"scaled scenario requires at least {min_locations} locations; found {len(state.locations)}"
        )
    if primary_hub_id not in state.locations:
        raise TownScenarioValidationError(
            f"scaled scenario primary hub is missing: {primary_hub_id}"
        )

    seed_residents = {seed.resident_id for seed in scenario.memory_seeds}
    resident_ids = set(state.residents)
    checked_residents = list(representative_resident_ids or sorted(state.residents))
    unknown_checked = sorted(set(checked_residents) - resident_ids)
    if unknown_checked:
        raise TownScenarioValidationError(
            f"scaled scenario representative residents are unknown: {', '.join(unknown_checked)}"
        )

    for resident in state.residents.values():
        if not resident.persona.currently or not resident.persona.background:
            raise TownScenarioValidationError(
                f"scaled scenario resident {resident.npc_id!r} is missing persona fields"
            )
        if len(resident.persona.relationships) < 2:
            raise TownScenarioValidationError(
                f"scaled scenario resident {resident.npc_id!r} must define at least two relationships"
            )
        unknown_relationships = sorted(set(resident.persona.relationships) - resident_ids)
        if unknown_relationships:
            raise TownScenarioValidationError(
                f"scaled scenario resident {resident.npc_id!r} relationships reference unknown residents: "
                f"{', '.join(unknown_relationships)}"
            )
        if resident.npc_id not in seed_residents:
            raise TownScenarioValidationError(
                f"scaled scenario resident {resident.npc_id!r} is missing memory seed coverage"
            )
        if not resident.schedule:
            raise TownScenarioValidationError(
                f"scaled scenario resident {resident.npc_id!r} is missing schedule seeds"
            )
        if not _route_exists(state.locations, resident.home_location_id or resident.location_id, primary_hub_id):
            raise TownScenarioValidationError(
                f"scaled scenario resident {resident.npc_id!r} home cannot reach {primary_hub_id}"
            )
        _validate_resident_schedule_seed(
            resident,
            locations=state.locations,
            origin=resident.location_id,
        )

    for npc_id in checked_residents:
        schedule = state.schedule_for(npc_id)
        location_ids = {segment.location_id for segment in schedule}
        if not any(segment.location_id == state.residents[npc_id].home_location_id for segment in schedule):
            raise TownScenarioValidationError(
                f"scaled scenario resident {npc_id!r} schedule lacks home/lifecycle period"
            )
        if len(location_ids - {state.residents[npc_id].home_location_id}) < 2:
            raise TownScenarioValidationError(
                f"scaled scenario resident {npc_id!r} schedule lacks work/study plus public/social destinations"
            )

    return TownScenarioScaleReport(
        scenario_id=scenario.id,
        resident_count=len(state.residents),
        location_count=len(state.locations),
        memory_seed_count=len(scenario.memory_seeds),
        primary_hub_id=primary_hub_id,
        checked_residents=checked_residents,
    )


def _clock(payload: object) -> TownClock:
    data = _mapping(payload, "clock")
    _assert_keys(data, _CLOCK_KEYS, "clock")
    return TownClock(
        day=int(data.get("day", 1)),
        minute=int(data.get("minute", 8 * 60)),
        stride_minutes=int(data.get("stride_minutes", 10)),
    )


def _locations(items: list[object]) -> tuple[dict[str, Location], dict[str, TownObject]]:
    locations: dict[str, Location] = {}
    objects: dict[str, TownObject] = {}
    for index, item in enumerate(items):
        path = f"locations[{index}]"
        data = _mapping(item, path)
        _assert_keys(data, _LOCATION_KEYS, path)
        location_id = _required_str(data, "id", path)
        _assert_new_id(location_id, locations, path)
        exits, travel_minutes = _exits(data.get("exits", []), path)
        object_ids: list[str] = []
        for object_index, object_payload in enumerate(_list(data.get("objects", []), f"{path}.objects")):
            town_object = _object(object_payload, f"{path}.objects[{object_index}]", location_id)
            _assert_new_id(town_object.id, objects, f"{path}.objects[{object_index}]")
            objects[town_object.id] = town_object
            object_ids.append(town_object.id)
        locations[location_id] = Location(
            id=location_id,
            name=_required_str(data, "name", path),
            description=str(data.get("description", "")),
            exits=exits,
            exit_travel_minutes=travel_minutes,
            object_ids=object_ids,
            affordances=[
                _affordance(affordance, f"{path}.affordances[{affordance_index}]")
                for affordance_index, affordance in enumerate(
                    _list(data.get("affordances", []), f"{path}.affordances")
                )
            ],
        )
    return locations, objects


def _exits(payload: object, path: str) -> tuple[list[str], dict[str, int]]:
    exits: list[str] = []
    travel_minutes: dict[str, int] = {}
    for index, item in enumerate(_list(payload, f"{path}.exits")):
        exit_path = f"{path}.exits[{index}]"
        if isinstance(item, str):
            destination = item
            minutes = 5
        else:
            data = _mapping(item, exit_path)
            _assert_keys(data, _EXIT_KEYS, exit_path)
            destination = _required_str(data, "to", exit_path)
            minutes = int(data.get("travel_minutes", 5))
        exits.append(destination)
        travel_minutes[destination] = minutes
    return exits, travel_minutes


def _object(payload: object, path: str, location_id: str) -> TownObject:
    data = _mapping(payload, path)
    _assert_keys(data, _OBJECT_KEYS, path)
    return TownObject(
        id=_required_str(data, "id", path),
        name=_required_str(data, "name", path),
        location_id=location_id,
        description=str(data.get("description", "")),
        interactable=bool(data.get("interactable", True)),
        affordances=[
            _affordance(affordance, f"{path}.affordances[{index}]")
            for index, affordance in enumerate(
                _list(data.get("affordances", []), f"{path}.affordances")
            )
        ],
    )


def _affordance(payload: object, path: str) -> SemanticAffordance:
    data = _mapping(payload, path)
    _assert_keys(data, _AFFORDANCE_KEYS, path)
    return SemanticAffordance(
        id=_required_str(data, "id", path),
        label=_required_str(data, "label", path),
        description=str(data.get("description", "")),
        duration_minutes=int(data.get("duration_minutes", 5)),
        aliases=[str(item) for item in _list(data.get("aliases", []), f"{path}.aliases")],
        event_type=str(data.get("event_type", "interaction")),
    )


def _residents(
    items: list[object],
    *,
    locations: dict[str, Location],
    objects: dict[str, TownObject],
    default_day: int,
) -> tuple[dict[str, TownResidentState], list[TownMemorySeed]]:
    residents: dict[str, TownResidentState] = {}
    seeds: list[TownMemorySeed] = []
    for index, item in enumerate(items):
        path = f"residents[{index}]"
        data = _mapping(item, path)
        _assert_keys(data, _RESIDENT_KEYS, path)
        npc_id = _required_str(data, "id", path)
        _assert_new_id(npc_id, residents, path)
        starting_location = _required_str(data, "starting_location", path)
        if starting_location not in locations:
            raise TownScenarioValidationError(f"{path}.starting_location references unknown location: {starting_location}")
        home_location = str(data.get("home_location") or starting_location)
        sleep_location = str(data.get("sleep_location") or home_location)
        for key, location_id in {
            "home_location": home_location,
            "sleep_location": sleep_location,
        }.items():
            if location_id not in locations:
                raise TownScenarioValidationError(
                    f"{path}.{key} references unknown location: {location_id}"
                )
        persona = _persona(data.get("persona", {}), data.get("relationships", {}), f"{path}.persona")
        schedule = [
            _schedule_segment(segment, f"{path}.schedule[{segment_index}]", npc_id, default_day)
            for segment_index, segment in enumerate(_list(data.get("schedule", []), f"{path}.schedule"))
        ]
        known_locations = _known_locations(data, starting_location, schedule, locations)
        known_objects = _known_objects(data, known_locations, locations, objects)
        residents[npc_id] = TownResidentState(
            npc_id=npc_id,
            location_id=starting_location,
            home_location_id=home_location,
            sleep_location_id=sleep_location,
            default_wake_window=_minute_window(data.get("default_wake_window"), f"{path}.default_wake_window"),
            default_sleep_window=_minute_window(data.get("default_sleep_window"), f"{path}.default_sleep_window"),
            lifecycle_status=str(data.get("lifecycle_status", "awake")),
            schedule=schedule,
            scratch=ResidentScratch(currently=persona.currently),
            persona=persona,
            schedule_day=default_day if schedule else None,
            spatial_memory=ResidentSpatialMemory(
                known_location_ids=known_locations,
                known_object_ids=known_objects,
            ),
        )
        seeds.extend(_memory_seeds(data.get("memory_seeds", []), resident_id=npc_id))
    return residents, seeds


def _persona(payload: object, relationships_payload: object, path: str) -> ResidentPersona:
    data = _mapping(payload, path)
    _assert_keys(data, _PERSONA_KEYS, path)
    relationships = _mapping(relationships_payload, path.rsplit(".", 1)[0] + ".relationships")
    return ResidentPersona(
        currently=str(data.get("currently", "")),
        lifestyle=str(data.get("lifestyle", "")),
        background=str(data.get("background", "")),
        traits=[str(item) for item in _list(data.get("traits", []), f"{path}.traits")],
        relationships={str(key): str(value) for key, value in relationships.items()},
    )


def _schedule_segment(payload: object, path: str, npc_id: str, default_day: int) -> ScheduleSegment:
    data = _mapping(payload, path)
    _assert_keys(data, _SCHEDULE_KEYS, path)
    duration = _required_int(data, "duration_minutes", path)
    if duration <= 0:
        raise TownScenarioValidationError(f"{path}.duration_minutes must be positive")
    day = default_day if data.get("day") is None else _required_int(data, "day", path)
    return ScheduleSegment(
        npc_id=npc_id,
        start_minute=_required_int(data, "start_minute", path),
        duration_minutes=duration,
        location_id=_required_str(data, "location", path),
        intent=_required_str(data, "intent", path),
        subtasks=[str(item) for item in _list(data.get("subtasks", []), f"{path}.subtasks")],
        completion_tags=[
            str(item)
            for item in _list(data.get("completion_tags", []), f"{path}.completion_tags")
        ],
        day=day,
        completion_policy=_normalize_completion_policy(
            str(data.get("completion_policy", "first_matching_action"))
        ),
        min_matching_actions=max(1, int(data.get("min_matching_actions", 1))),
        allow_explicit_override=bool(data.get("allow_explicit_override", True)),
    )


def _normalize_completion_policy(value: str) -> str:
    if value in {
        "first_matching_action",
        "occupy_until_segment_end",
        "min_matching_actions",
        "explicit",
    }:
        return value
    return "first_matching_action"


def _memory_seeds(payload: object, resident_id: str | None) -> list[TownMemorySeed]:
    seeds: list[TownMemorySeed] = []
    for index, item in enumerate(_list(payload, "memory_seeds")):
        path = f"memory_seeds[{index}]"
        data = _mapping(item, path)
        _assert_keys(data, _MEMORY_SEED_KEYS, path)
        target_resident = resident_id or _required_str(data, "resident", path)
        category = str(data.get("category", "semantic"))
        if category not in SUPPORTED_MEMORY_SEED_CATEGORIES:
            raise TownScenarioValidationError(f"{path}.category is unsupported: {category}")
        seeds.append(
            TownMemorySeed(
                id=str(data.get("id", f"{target_resident}:{index}")),
                resident_id=target_resident,
                content=_required_str(data, "content", path),
                category=category,
                metadata={
                    str(key): value
                    for key, value in _mapping(data.get("metadata", {}), f"{path}.metadata").items()
                },
            )
        )
    return seeds


def _known_locations(
    data: Mapping[str, object],
    starting_location: str,
    schedule: list[ScheduleSegment],
    locations: dict[str, Location],
) -> list[str]:
    explicit = data.get("known_locations")
    values = (
        [str(item) for item in _list(explicit, "resident.known_locations")]
        if explicit is not None
        else [starting_location, *locations.keys(), *(segment.location_id for segment in schedule)]
    )
    return _unique(values)


def _known_objects(
    data: Mapping[str, object],
    known_locations: list[str],
    locations: dict[str, Location],
    objects: dict[str, TownObject],
) -> list[str]:
    explicit = data.get("known_objects")
    if explicit is not None:
        return _unique(str(item) for item in _list(explicit, "resident.known_objects"))
    object_ids: list[str] = []
    for location_id in known_locations:
        location = locations.get(location_id)
        if location is not None:
            object_ids.extend(location.object_ids)
    return _unique(object_id for object_id in object_ids if object_id in objects)


def _validate_graph(
    locations: dict[str, Location],
    objects: dict[str, TownObject],
    residents: dict[str, TownResidentState],
    memory_seeds: list[TownMemorySeed],
) -> None:
    for location in locations.values():
        for exit_id in location.exits:
            if exit_id not in locations:
                raise TownScenarioValidationError(
                    f"location {location.id!r} exit references unknown location: {exit_id}"
                )
        for object_id in location.object_ids:
            if object_id not in objects:
                raise TownScenarioValidationError(
                    f"location {location.id!r} references unknown object: {object_id}"
                )
    for resident in residents.values():
        for attr in ("home_location_id", "sleep_location_id"):
            location_id = getattr(resident, attr)
            if location_id is not None and location_id not in locations:
                raise TownScenarioValidationError(
                    f"resident {resident.npc_id!r} {attr} references unknown location: {location_id}"
                )
        for segment in resident.schedule:
            if segment.location_id not in locations:
                raise TownScenarioValidationError(
                    f"resident {resident.npc_id!r} schedule references unknown location: {segment.location_id}"
                )
        _validate_resident_schedule_seed(
            resident,
            locations=locations,
            origin=resident.location_id,
            check_route=False,
        )
    for seed in memory_seeds:
        if seed.resident_id not in residents:
            raise TownScenarioValidationError(
                f"memory seed {seed.id!r} references unknown resident: {seed.resident_id}"
            )


def _validate_resident_schedule_seed(
    resident: TownResidentState,
    *,
    locations: dict[str, Location],
    origin: str,
    check_route: bool = True,
) -> None:
    previous_end: int | None = None
    previous_location = origin
    for segment in sorted(resident.schedule, key=lambda item: (item.day or 0, item.start_minute)):
        if segment.start_minute < 0 or segment.end_minute > 24 * 60:
            raise TownScenarioValidationError(
                f"resident {resident.npc_id!r} schedule segment is outside 00:00-24:00: {segment.intent}"
            )
        if previous_end is not None and segment.start_minute < previous_end:
            raise TownScenarioValidationError(
                f"resident {resident.npc_id!r} schedule has overlapping segments near {segment.intent!r}"
            )
        if check_route and not _route_exists(locations, previous_location, segment.location_id):
            raise TownScenarioValidationError(
                f"resident {resident.npc_id!r} schedule location is unreachable: {segment.location_id}"
            )
        previous_end = segment.end_minute
        previous_location = segment.location_id


def _route_exists(locations: dict[str, Location], start: str | None, target: str) -> bool:
    if start is None or start not in locations or target not in locations:
        return False
    queue: deque[str] = deque([start])
    seen = {start}
    while queue:
        current = queue.popleft()
        if current == target:
            return True
        for next_id in locations[current].exits:
            if next_id not in locations or next_id in seen:
                continue
            seen.add(next_id)
            queue.append(next_id)
    return False


def _assert_keys(data: Mapping[str, object], allowed: set[str], path: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise TownScenarioValidationError(f"{path} has unsupported fields: {', '.join(unknown)}")


def _assert_new_id(identifier: str, existing: Mapping[str, object], path: str) -> None:
    if identifier in existing:
        raise TownScenarioValidationError(f"{path}.id is duplicated: {identifier}")


def _mapping(payload: object, path: str) -> Mapping[str, object]:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise TownScenarioValidationError(f"{path} must be an object")
    return payload


def _list(payload: object, path: str) -> list[object]:
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise TownScenarioValidationError(f"{path} must be a list")
    return payload


def _required_list(data: Mapping[str, object], key: str, path: str) -> list[object]:
    if key not in data:
        raise TownScenarioValidationError(f"{path}.{key} is required")
    return _list(data[key], f"{path}.{key}")


def _required_str(data: Mapping[str, object], key: str, path: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise TownScenarioValidationError(f"{path}.{key} must be a non-empty string")
    return value


def _required_int(data: Mapping[str, object], key: str, path: str) -> int:
    value = data.get(key)
    if not isinstance(value, int):
        raise TownScenarioValidationError(f"{path}.{key} must be an integer")
    return value


def _minute_window(payload: object, path: str) -> tuple[int, int] | None:
    if payload is None:
        return None
    values = _list(payload, path)
    if len(values) != 2 or not all(isinstance(item, int) for item in values):
        raise TownScenarioValidationError(f"{path} must be a two-item integer list")
    start, end = int(values[0]), int(values[1])
    if start < 0 or end > 24 * 60 or start >= end:
        raise TownScenarioValidationError(f"{path} must be within 00:00-24:00")
    return (start, end)


def _unique(items: object) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = str(item)
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result

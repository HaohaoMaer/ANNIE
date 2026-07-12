from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from annie.npc.memory.interface import MemoryRecord
from annie.town import (
    TownRuntimeConfig,
    TownScenarioValidationError,
    apply_memory_seeds,
    create_small_town_state,
    default_scaled_town_scenario_path,
    default_small_town_scenario_path,
    load_town_scenario,
    run_town_runtime,
    validate_scaled_town_scenario,
)


def test_small_town_scenario_loads_semantic_state() -> None:
    scenario = load_town_scenario(default_small_town_scenario_path())
    state = scenario.state

    assert scenario.id == "small_town"
    assert state.clock.day == 1
    assert state.clock.minute == 8 * 60
    assert set(state.locations) == {
        "home_alice",
        "home_bob",
        "home_clara",
        "town_square",
        "cafe",
        "library",
        "clinic",
        "market",
        "workshop",
        "park",
    }
    assert state.locations["town_square"].exit_travel_minutes["cafe"] == 3
    assert state.locations["town_square"].exit_travel_minutes["home_bob"] == 5
    assert state.objects["cafe_counter"].location_id == "cafe"
    assert state.objects["cafe_counter"].affordances[0].id == "order_coffee"
    assert state.location_id_for("alice") == "home_alice"
    assert state.residents["alice"].persona.currently
    assert state.residents["alice"].persona.traits == ["细心", "友善", "守时"]
    assert state.residents["alice"].persona.relationships["bob"].startswith("常在咖啡馆")
    assert state.residents["alice"].scratch.currently == state.residents["alice"].persona.currently
    assert state.residents["alice"].home_location_id == "home_alice"
    assert state.residents["bob"].home_location_id == "home_bob"
    assert state.residents["bob"].sleep_location_id == "home_bob"
    assert state.residents["clara"].default_wake_window == (420, 540)
    assert state.schedule_for("bob")[0].intent == "准备咖啡馆营业"
    assert state.schedule_for("bob")[0].day == 1
    assert "cafe_counter" in state.residents["alice"].spatial_memory.known_object_ids


def test_create_small_town_state_uses_scenario_loader() -> None:
    state = create_small_town_state()

    assert state.resident_ids() == ["alice", "bob", "clara"]
    assert state.objects["breakfast_table"].affordances[0].aliases == ["吃早餐", "用餐"]


def test_scenario_loader_rejects_invalid_references(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        """
schema_version: 1
id: bad
name: Bad
locations:
  - id: home
    name: Home
    exits:
      - to: nowhere
residents:
  - id: alice
    starting_location: home
    schedule:
      - start_minute: 480
        duration_minutes: 30
        location: missing
        intent: Leave
""",
        encoding="utf-8",
    )

    with pytest.raises(TownScenarioValidationError, match="unknown location"):
        load_town_scenario(path)


def test_scenario_loader_rejects_unknown_content_fields(tmp_path: Path) -> None:
    path = tmp_path / "ga_fields.yaml"
    path.write_text(
        """
schema_version: 1
id: bad
name: Bad
locations:
  - id: home
    name: Home
residents:
  - id: alice
    starting_location: home
    tile: [1, 2]
""",
        encoding="utf-8",
    )

    with pytest.raises(TownScenarioValidationError, match="unsupported fields: tile"):
        load_town_scenario(path)


def test_generative_agents_cn_fields_are_not_required(tmp_path: Path) -> None:
    path = tmp_path / "minimal.yaml"
    path.write_text(
        """
schema_version: 1
id: minimal
name: Minimal
locations:
  - id: home
    name: Home
residents:
  - id: alice
    starting_location: home
    persona:
      currently: At home.
      lifestyle: Quiet.
      background: Local resident.
      traits: [calm]
""",
        encoding="utf-8",
    )

    state = load_town_scenario(path).state

    assert state.residents["alice"].persona.background == "Local resident."
    assert state.location_id_for("alice") == "home"


def test_memory_seeds_are_written_through_memory_interface() -> None:
    scenario = load_town_scenario(default_small_town_scenario_path())
    memories = {"alice": RecordingMemory()}

    apply_memory_seeds(scenario, lambda npc_id: memories[npc_id])

    assert memories["alice"].writes == [
        {
            "content": "Alice 通常先吃早餐，再去咖啡馆买咖啡。",
            "category": "semantic",
            "metadata": {
                "topic": "routine",
                "source": "town_scenario_seed",
                "scenario_id": "small_town",
                "scenario_path": str(default_small_town_scenario_path()),
                "seed_id": "alice_routine",
                "resident_id": "alice",
            },
        }
    ]


def test_scaled_town_scenario_satisfies_generative_scale_contracts() -> None:
    scenario = load_town_scenario(default_scaled_town_scenario_path())
    report = validate_scaled_town_scenario(
        scenario,
        representative_resident_ids=["ada", "ben", "cara", "dan", "elena"],
    )

    assert scenario.id == "generative_scale_town"
    assert report.resident_count >= 25
    assert report.location_count >= 20
    assert report.memory_seed_count >= 25
    assert {"town_square", "riverside_cafe", "school", "festival_green"} <= set(
        scenario.state.locations
    )
    assert all(len(resident.persona.relationships) >= 2 for resident in scenario.state.residents.values())
    assert all(resident.schedule for resident in scenario.state.residents.values())
    assert "thread" in (scenario.memory_seeds[0].metadata or {})
    cafe_affordances = scenario.state.objects["cafe_counter_scale"].affordances
    assert any(
        affordance.id == "deliver_pastries"
        and "deliver pastries" in affordance.aliases
        for affordance in cafe_affordances
    )
    market_affordance_ids = {
        affordance.id
        for affordance in scenario.state.objects["market_stall_scale"].affordances
    }
    assert {"prepare_stall", "check_inventory", "update_price_board"} <= market_affordance_ids
    assert "Rest" in scenario.state.locations["home_ada"].affordances[0].aliases
    assert {
        "review_notes",
        "file_notes",
        "plan_day",
    } <= {
        affordance.id
        for affordance in scenario.state.objects["home_sam_table"].affordances
    }
    jules_delivery = next(
        segment
        for segment in scenario.state.schedule_for("jules")
        if segment.intent == "Deliver pastries"
    )
    assert "deliver_pastries" in jules_delivery.completion_tags


def test_scaled_scenario_validation_rejects_relationship_and_seed_gaps(tmp_path: Path) -> None:
    path = tmp_path / "bad_scaled.yaml"
    path.write_text(
        """
schema_version: 1
id: bad_scaled
name: Bad Scaled
locations:
  - id: town_square
    name: Town Square
  - id: home_a
    name: Home A
    exits: [{to: town_square}]
residents:
  - id: resident_a
    name: Resident A
    starting_location: home_a
    home_location: home_a
    sleep_location: home_a
    persona:
      currently: Present.
      lifestyle: Local.
      background: Local resident.
      traits: [steady]
    relationships:
      missing: Missing resident.
    schedule:
      - start_minute: 480
        duration_minutes: 30
        location: home_a
        intent: Start day
""",
        encoding="utf-8",
    )

    scenario = load_town_scenario(path)
    with pytest.raises(TownScenarioValidationError, match="at least 25 residents"):
        validate_scaled_town_scenario(scenario)


def test_invalid_scaled_scenario_fails_before_runtime_tick(tmp_path: Path) -> None:
    path = tmp_path / "bad_runtime.yaml"
    path.write_text(
        """
schema_version: 1
id: bad_runtime
name: Bad Runtime
locations:
  - id: home
    name: Home
residents:
  - id: resident_a
    name: Resident A
    starting_location: home
    schedule:
      - start_minute: 480
        duration_minutes: 30
        location: missing_place
        intent: Bad route
""",
        encoding="utf-8",
    )

    with pytest.raises(TownScenarioValidationError, match="unknown location"):
        run_town_runtime(
            TownRuntimeConfig(
                run_id="bad",
                run_root=tmp_path,
                scenario_path=path,
                max_ticks_per_day=1,
            )
        )

    assert not (tmp_path / "bad" / "replay").exists()


@dataclass
class RecordingMemory:
    writes: list[dict[str, object]] = field(default_factory=list)

    def recall(
        self,
        query: str,
        categories: list[str] | None = None,
        k: int = 5,
    ) -> list[MemoryRecord]:
        return []

    def grep(
        self,
        pattern: str,
        category: str | None = None,
        metadata_filters: dict[str, object] | None = None,
        k: int = 20,
    ) -> list[MemoryRecord]:
        return []

    def remember(
        self,
        content: str,
        category: str = "semantic",
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.writes.append(
            {
                "content": content,
                "category": category,
                "metadata": dict(metadata or {}),
            }
        )

    def build_context(self, query: str) -> str:
        return ""

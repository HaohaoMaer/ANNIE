"""Unit tests for GameState helpers and map preset validation."""

from annie.war_game.config import GameConfig
from annie.war_game.game_state import City, Faction, GameState
from annie.war_game.map_preset import (
    FACTION_A,
    FACTION_B,
    PLAYER,
    create_default_state,
)


class TestMapPreset:
    def test_creates_15_cities(self) -> None:
        state = create_default_state()
        assert len(state.cities) == 15

    def test_each_faction_owns_5_cities(self) -> None:
        state = create_default_state()
        for fid in [PLAYER, FACTION_A, FACTION_B]:
            assert len(state.owned_cities(fid)) == 5

    def test_adjacency_is_bidirectional(self) -> None:
        state = create_default_state()
        for city in state.cities.values():
            for adj_id in city.adjacent:
                adj_city = state.cities[adj_id]
                assert city.id in adj_city.adjacent, (
                    f"{city.id} -> {adj_id} but not reverse"
                )

    def test_rotational_symmetry(self) -> None:
        """P→A→B→P rotation preserves adjacency structure."""
        state = create_default_state()

        def rotate(cid: str) -> str:
            return {"P": "A", "A": "B", "B": "P"}[cid[0]] + cid[1:]

        for city in state.cities.values():
            rotated = rotate(city.id)
            expected_adj = sorted(rotate(a) for a in city.adjacent)
            actual_adj = sorted(state.cities[rotated].adjacent)
            assert expected_adj == actual_adj

    def test_each_faction_has_exactly_two_borders_per_enemy(self) -> None:
        state = create_default_state()
        for fid in [PLAYER, FACTION_A, FACTION_B]:
            enemies = {f for f in [PLAYER, FACTION_A, FACTION_B] if f != fid}
            for enemy in enemies:
                border_count = 0
                for city in state.owned_cities(fid):
                    for adj_id in city.adjacent:
                        if state.cities[adj_id].owner == enemy:
                            border_count += 1
                assert border_count == 2, (
                    f"{fid} has {border_count} borders with {enemy}, expected 2"
                )

    def test_rear_city_has_no_enemy_neighbors(self) -> None:
        state = create_default_state()
        for rear_id in ["P1", "A1", "B1"]:
            city = state.cities[rear_id]
            for adj_id in city.adjacent:
                assert state.cities[adj_id].owner == city.owner

    def test_custom_config(self) -> None:
        cfg = GameConfig(initial_forces=500, production_per_city=100)
        state = create_default_state(cfg)
        for f in state.factions.values():
            assert f.force_pool == 500


class TestGameStateHelpers:
    def _make_state(self) -> GameState:
        return create_default_state()

    def test_owned_cities(self) -> None:
        state = self._make_state()
        player_cities = state.owned_cities(PLAYER)
        assert {c.id for c in player_cities} == {"P1", "P2", "P3", "P4", "P5"}

    def test_adjacent_enemies(self) -> None:
        state = self._make_state()
        enemies = state.adjacent_enemies(PLAYER)
        enemy_ids = {c.id for c in enemies}
        # Player borders A5, A3 (A-side) and B4, B2 (B-side)
        assert enemy_ids == {"A5", "A3", "B4", "B2"}

    def test_is_game_over_initial(self) -> None:
        state = self._make_state()
        assert not state.is_game_over()
        assert state.winner() is None

    def test_is_game_over_one_eliminated(self) -> None:
        state = self._make_state()
        state.factions[FACTION_B].is_eliminated = True
        assert not state.is_game_over()

    def test_is_game_over_two_eliminated(self) -> None:
        state = self._make_state()
        state.factions[FACTION_A].is_eliminated = True
        state.factions[FACTION_B].is_eliminated = True
        assert state.is_game_over()
        assert state.winner() == PLAYER

    def test_active_factions(self) -> None:
        state = self._make_state()
        assert len(state.active_factions()) == 3
        state.factions[FACTION_A].is_eliminated = True
        assert len(state.active_factions()) == 2

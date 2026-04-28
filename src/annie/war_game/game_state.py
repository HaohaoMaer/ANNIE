"""Core data model for the three-faction war game."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class City:
    id: str
    owner: str  # faction_id
    adjacent: list[str]  # city_ids
    captured_this_round: bool = False


@dataclass
class Faction:
    id: str
    force_pool: int
    is_eliminated: bool = False


@dataclass
class Deployment:
    """A single allocation entry: defend an owned city or attack an enemy city."""

    target: str  # city_id
    troops: int
    action: str  # "defend" | "attack"


@dataclass
class BattleResult:
    """Outcome of one battle at a single city."""

    city_id: str
    attacker_id: str
    defender_id: str
    attacker_troops: int
    defender_troops: int
    winner: str = ""  # faction_id of the winner
    attacker_remaining: int = 0
    defender_remaining: int = 0
    city_captured: bool = False
    # For 2v1 battles
    is_2v1: bool = False
    second_attacker_id: str = ""
    second_attacker_troops: int = 0


@dataclass
class GameState:
    """Mutable game state mutated by phase functions."""

    cities: dict[str, City]
    factions: dict[str, Faction]
    round_number: int = 0
    declarations: dict[str, str] = field(default_factory=dict)
    deployments: dict[str, list[Deployment]] = field(default_factory=dict)
    round_log: list[BattleResult] = field(default_factory=list)

    def owned_cities(self, faction_id: str) -> list[City]:
        """Return all cities owned by the given faction."""
        return [c for c in self.cities.values() if c.owner == faction_id]

    def adjacent_enemies(self, faction_id: str) -> list[City]:
        """Return enemy cities adjacent to the faction's territory."""
        owned_ids = {c.id for c in self.owned_cities(faction_id)}
        result: list[City] = []
        seen: set[str] = set()
        for city in self.owned_cities(faction_id):
            for adj_id in city.adjacent:
                if adj_id not in owned_ids and adj_id not in seen:
                    seen.add(adj_id)
                    result.append(self.cities[adj_id])
        return result

    def is_game_over(self) -> bool:
        """True when at most one faction remains active."""
        active = [f for f in self.factions.values() if not f.is_eliminated]
        return len(active) <= 1

    def winner(self) -> str | None:
        """Return the winning faction id, or None if game is not over."""
        active = [f for f in self.factions.values() if not f.is_eliminated]
        if len(active) == 1:
            return active[0].id
        return None

    def active_factions(self) -> list[Faction]:
        """Return all non-eliminated factions."""
        return [f for f in self.factions.values() if not f.is_eliminated]

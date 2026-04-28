"""Default 15-city symmetric map preset.

Three-fold rotational symmetry: each faction has 5 cities.
Rotation mapping: P→A→B→P (i.e. P1→A1→B1, P2→A2→B2, etc.)

Per faction (X):
  X1 — rear (adjacent to X2, X3 only — no enemy border)
  X2 — mid/flank (adjacent to X1, X4, and one enemy city)
  X3 — mid/flank (adjacent to X1, X5, and one enemy city)
  X4 — front (adjacent to X2 and one enemy city)
  X5 — front (adjacent to X3 and one enemy city)

Cross-faction borders (two rotationally-symmetric patterns):
  Pattern 1: P2-A5, A2-B5, B2-P5
  Pattern 2: P3-B4, A3-P4, B3-A4

Result: each faction has 2 cities bordering each enemy.

Factions:
  "player" (丙) — the human player
  "faction_a" (甲) — AI Hawk
  "faction_b" (乙) — AI Fox
"""

from __future__ import annotations

from annie.war_game.config import GameConfig
from annie.war_game.game_state import City, Faction, GameState

# Faction IDs
PLAYER = "player"
FACTION_A = "faction_a"
FACTION_B = "faction_b"

# Display names (Chinese convention)
FACTION_NAMES: dict[str, str] = {
    PLAYER: "丙（你）",
    FACTION_A: "甲",
    FACTION_B: "乙",
}

# City definitions: (city_id, owner, adjacent_ids)
_CITY_DEFS: list[tuple[str, str, list[str]]] = [
    # Player cities
    ("P1", PLAYER, ["P2", "P3"]),          # rear
    ("P2", PLAYER, ["P1", "P4", "A5"]),    # mid — borders A via A5
    ("P3", PLAYER, ["P1", "P5", "B4"]),    # mid — borders B via B4
    ("P4", PLAYER, ["P2", "A3"]),          # front — borders A via A3
    ("P5", PLAYER, ["P3", "B2"]),          # front — borders B via B2
    # Faction A cities
    ("A1", FACTION_A, ["A2", "A3"]),       # rear
    ("A2", FACTION_A, ["A1", "A4", "B5"]), # mid — borders B via B5
    ("A3", FACTION_A, ["A1", "A5", "P4"]), # mid — borders P via P4
    ("A4", FACTION_A, ["A2", "B3"]),       # front — borders B via B3
    ("A5", FACTION_A, ["A3", "P2"]),       # front — borders P via P2
    # Faction B cities
    ("B1", FACTION_B, ["B2", "B3"]),       # rear
    ("B2", FACTION_B, ["B1", "B4", "P5"]), # mid — borders P via P5
    ("B3", FACTION_B, ["B1", "B5", "A4"]), # mid — borders A via A4
    ("B4", FACTION_B, ["B2", "P3"]),       # front — borders P via P3
    ("B5", FACTION_B, ["B3", "A2"]),       # front — borders A via A2
]


def _validate_symmetry() -> None:
    """Verify adjacency is bidirectional and each faction has 5 cities."""
    adj: dict[str, set[str]] = {}
    owners: dict[str, list[str]] = {}
    for cid, owner, adjs in _CITY_DEFS:
        adj[cid] = set(adjs)
        owners.setdefault(owner, []).append(cid)

    # Bidirectional check
    for cid, neighbours in adj.items():
        for n in neighbours:
            assert cid in adj[n], f"Adjacency not bidirectional: {cid} -> {n}"

    # Per-faction count
    for faction, cities in owners.items():
        assert len(cities) == 5, f"Faction {faction} has {len(cities)} cities, expected 5"

    # Rotational symmetry check: rotation P→A→B→P
    def rotate(city_id: str) -> str:
        prefix = city_id[0]
        suffix = city_id[1:]
        mapping = {"P": "A", "A": "B", "B": "P"}
        return mapping[prefix] + suffix

    for cid, neighbours in adj.items():
        rotated_neighbours = {rotate(n) for n in neighbours}
        rotated_city = rotate(cid)
        assert adj[rotated_city] == rotated_neighbours, (
            f"Rotational symmetry broken: {cid}→{rotated_city}, "
            f"expected neighbours {rotated_neighbours}, got {adj[rotated_city]}"
        )


# Run at import time so a broken map never silently loads.
_validate_symmetry()


def create_default_state(config: GameConfig | None = None) -> GameState:
    """Build the initial GameState from the default 15-city preset."""
    cfg = config or GameConfig()

    cities: dict[str, City] = {}
    for cid, owner, adjs in _CITY_DEFS:
        cities[cid] = City(id=cid, owner=owner, adjacent=list(adjs))

    factions: dict[str, Faction] = {
        PLAYER: Faction(id=PLAYER, force_pool=cfg.initial_forces),
        FACTION_A: Faction(id=FACTION_A, force_pool=cfg.initial_forces),
        FACTION_B: Faction(id=FACTION_B, force_pool=cfg.initial_forces),
    }

    return GameState(cities=cities, factions=factions)

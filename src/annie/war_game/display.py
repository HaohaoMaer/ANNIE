"""CLI rendering: ASCII map, round reports, force pool display."""

from __future__ import annotations

from annie.war_game.game_state import GameState
from annie.war_game.map_preset import FACTION_A, FACTION_B, FACTION_NAMES, PLAYER


def _owner_tag(owner: str) -> str:
    """Short faction tag for map display."""
    return {"player": "P", "faction_a": "A", "faction_b": "B"}.get(owner, "?")


def render_map(state: GameState) -> str:
    """Render a text-based map showing city ownership.

    Uses a tabular layout rather than trying to draw graph edges,
    since terminal-width constraints make true graph rendering fragile.
    """
    lines: list[str] = []
    lines.append("╔══════════════════════════════════════╗")
    lines.append("║           三 方 势 力 地 图           ║")
    lines.append("╠══════════════════════════════════════╣")

    for faction_id, label in [(PLAYER, "丙（你）"), (FACTION_A, "甲"), (FACTION_B, "乙")]:
        faction = state.factions[faction_id]
        if faction.is_eliminated:
            lines.append(f"║  {label}: ☠ 已被消灭                  ║")
            continue
        owned = state.owned_cities(faction_id)
        city_ids = " ".join(c.id for c in sorted(owned, key=lambda c: c.id))
        lines.append(f"║  {label}: [{_owner_tag(faction_id)}] {city_ids:<20s}║")

    lines.append("╠══════════════════════════════════════╣")
    lines.append("║  城市邻接关系:                        ║")

    # Show border cities
    borders: list[str] = []
    seen: set[tuple[str, str]] = set()
    for city in state.cities.values():
        for adj_id in city.adjacent:
            adj = state.cities[adj_id]
            if city.owner != adj.owner:
                a, b_ = sorted([city.id, adj_id])
                pair = (a, b_)
                if pair not in seen:
                    seen.add(pair)
                    borders.append(
                        f"  {city.id}[{_owner_tag(city.owner)}]─{adj_id}[{_owner_tag(adj.owner)}]"
                    )

    for b in sorted(borders):
        lines.append(f"║{b:<38s}║")

    lines.append("╚══════════════════════════════════════╝")
    return "\n".join(lines)


def render_force_pool(state: GameState, faction_id: str) -> str:
    """Show the player's own force pool (never enemy pools)."""
    faction = state.factions[faction_id]
    owned_count = len(state.owned_cities(faction_id))
    return (
        f"你的兵力池: {faction.force_pool}  |  "
        f"你的城市数: {owned_count}"
    )


def render_round_header(round_number: int) -> str:
    return (
        f"\n{'='*40}\n"
        f"       第 {round_number} 回合\n"
        f"{'='*40}"
    )


def render_declarations(declarations: dict[str, str]) -> str:
    """Show all declarations."""
    lines = ["", "═══ 各方宣言 ═══"]
    for fid, decl in declarations.items():
        name = FACTION_NAMES.get(fid, fid)
        lines.append(f"  {name}: \"{decl}\"")
    return "\n".join(lines)


def render_victory(winner: str) -> str:
    name = FACTION_NAMES.get(winner, winner)
    return (
        f"\n{'★'*20}\n"
        f"  {name} 获得胜利！\n"
        f"{'★'*20}"
    )


def render_game_over_summary(state: GameState) -> str:
    """Final state summary on quit."""
    lines = ["\n═══ 游戏结束 ═══"]
    for faction in state.factions.values():
        name = FACTION_NAMES.get(faction.id, faction.id)
        if faction.is_eliminated:
            lines.append(f"  {name}: 已被消灭")
        else:
            owned = len(state.owned_cities(faction.id))
            lines.append(f"  {name}: {owned}座城市, 兵力{faction.force_pool}")
    return "\n".join(lines)

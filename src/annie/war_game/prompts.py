"""Prompt text and situation rendering for the war game."""

from __future__ import annotations

from annie.war_game.game_state import GameState
from annie.war_game.map_preset import FACTION_NAMES

WORLD_RULES = """\
你正在参与一场三方势力争霸的策略游戏。

## 核心规则

**地图**: 15座城市，每方初始5座。城市之间有邻接关系，只能进攻相邻的敌方城市。

**兵力**: 每方有一个中央兵力池。每回合将全部兵力分配到防守（自己的城市）和进攻（相邻的敌方城市）。分配总和必须等于你的兵力池。

**回合流程**:
1. 宣言阶段：每方公开宣布本轮意图（可以说谎）
2. 外交阶段：与其他势力私下对话
3. 部署阶段：秘密分配兵力（防守+进攻）
4. 结算阶段：所有战斗同时结算

**战斗结算**: 进攻方与防守方兵力互相消耗。平局防守方胜。无防守的城市自动被占领。

**2v1情况**: 当两方同时进攻同一城市时，防守方伤害平均分摊给两个进攻方。防守方消灭后，两个进攻方进入谈判，然后同时选择"撤退"或"战斗"。双方都不知道对方剩余兵力。

**生产**: 每回合结束，每座城市产出固定兵力。本回合刚占领的城市下回合才开始产出。

**胜利条件**: 当场上只剩一方势力时，该方获胜。

## 关键策略提示
- 宣言是公开的，但不一定是真实的
- 外交对话是私密的，只有对话双方知道内容
- 你只能看到涉及你的城市的战斗细节
- 你无法看到敌方的总兵力
"""


def render_situation(state: GameState, faction_id: str) -> str:
    """Render the current round state as natural language for one faction."""
    faction = state.factions[faction_id]
    owned = state.owned_cities(faction_id)
    enemies = state.adjacent_enemies(faction_id)

    lines: list[str] = []
    lines.append(f"## 当前状态 — 第{state.round_number}回合")
    lines.append("")
    lines.append(f"**你是**: {FACTION_NAMES.get(faction_id, faction_id)}")
    lines.append(f"**你的兵力池**: {faction.force_pool}")
    lines.append("")

    # Owned cities
    lines.append("**你的城市**:")
    for city in sorted(owned, key=lambda c: c.id):
        adj_enemies = [
            f"{a} ({FACTION_NAMES.get(state.cities[a].owner, state.cities[a].owner)})"
            for a in city.adjacent
            if state.cities[a].owner != faction_id
        ]
        adj_str = f" [相邻敌方: {', '.join(adj_enemies)}]" if adj_enemies else ""
        lines.append(f"  - {city.id}{adj_str}")
    lines.append("")

    # Adjacent enemy cities
    lines.append("**可进攻的相邻敌方城市**:")
    for city in sorted(enemies, key=lambda c: c.id):
        owner_name = FACTION_NAMES.get(city.owner, city.owner)
        lines.append(f"  - {city.id} (属于{owner_name})")
    lines.append("")

    # Declarations (if any)
    if state.declarations:
        lines.append("**本轮各方宣言**:")
        for fid, decl in state.declarations.items():
            name = FACTION_NAMES.get(fid, fid)
            lines.append(f"  - {name}: \"{decl}\"")
        lines.append("")

    # Active factions
    active = state.active_factions()
    if len(active) < 3:
        eliminated = [
            FACTION_NAMES.get(f.id, f.id)
            for f in state.factions.values()
            if f.is_eliminated
        ]
        if eliminated:
            lines.append(f"**已被消灭的势力**: {', '.join(eliminated)}")
            lines.append("")

    return "\n".join(lines)

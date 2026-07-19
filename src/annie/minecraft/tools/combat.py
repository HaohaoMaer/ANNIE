"""Combat tools — attack, defend.

Mirrors mindcraft commands: !attack, !defendSelf, !moveAway (from avoidEnemies).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from annie.npc.tools.base_tool import ToolContext, ToolDef


# ── Input schemas ───────────────────────────────────────────────────────────

class AttackInput(BaseModel):
    entity_type: str = Field(
        default="hostile",
        description="要攻击的实体类型。默认 'hostile' 攻击最近的敌对生物。"
                    "也可以指定具体的生物名称如 'zombie', 'skeleton'。",
    )


class DefendInput(BaseModel):
    range: int = Field(default=8, ge=1, le=32, description="防御范围，默认8格")


# ── Tools ───────────────────────────────────────────────────────────────────

class AttackTool(ToolDef):
    name = "attack"
    description = "攻击最近的敌对生物。自动装备最佳武器并接近目标。仅在持有武器时使用。"
    input_schema = AttackInput
    is_read_only = False
    ends_activation_on_success = True

    def call(self, input: AttackInput, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        return bridge.call("attack_nearest", {"entity_type": input.entity_type})


class DefendTool(ToolDef):
    name = "defend"
    description = (
        "在指定范围内搜索并攻击最近的敌对生物。"
        "持续防御直到范围内没有敌人。"
        "当你被攻击时必须使用此工具进行自卫。"
    )
    input_schema = DefendInput
    is_read_only = False
    ends_activation_on_success = True

    def call(self, input: DefendInput, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        return bridge.call("defend_self", {"range": input.range})


class EquipHighestAttackTool(ToolDef):
    name = "equip_best_weapon"
    description = (
        "自动从背包中选择攻击力最高的武器并装备到手中。"
        "优先级：剑 > 斧 > 镐 > 锹。"
        "战斗前使用此工具确保自己有最强的武器。"
    )
    is_read_only = False

    def call(self, input: None, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        inv = bridge.call("get_inventory")
        items = inv.get("items", {})

        weapon_keywords = [
            "netherite_sword", "diamond_sword", "iron_sword", "stone_sword", "wooden_sword", "golden_sword",
            "netherite_axe", "diamond_axe", "iron_axe", "stone_axe", "wooden_axe", "golden_axe",
            "netherite_pickaxe", "diamond_pickaxe", "iron_pickaxe", "stone_pickaxe", "wooden_pickaxe", "golden_pickaxe",
            "netherite_shovel", "diamond_shovel", "iron_shovel", "stone_shovel", "wooden_shovel", "golden_shovel",
        ]

        for weapon in weapon_keywords:
            if weapon in items and items[weapon] > 0:
                result = bridge.call("equip", {"item_name": weapon})
                return {"ok": True, "equipped": weapon, "result": result}

        return {"ok": False, "reason": "no weapon found in inventory"}


def _get_bridge(ctx: ToolContext):
    bridge = ctx.agent_context.extra.get("_minecraft_bridge")
    if bridge is None:
        raise RuntimeError("MinecraftBridge not found in agent context")
    return bridge

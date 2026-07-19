"""Perception tools — check_surroundings, check_inventory, check_craftable.

Mirrors mindcraft queries: !stats + !nearbyBlocks + !entities, !inventory, !craftable.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from annie.npc.tools.base_tool import ToolContext, ToolDef
from annie.minecraft.perception import MinecraftPerception


# ── Tools ───────────────────────────────────────────────────────────────────

class CheckSurroundingsTool(ToolDef):
    name = "check_surroundings"
    description = (
        "获取周围环境的详细快照：自身状态、周围方块、附近实体、掉落物。"
        "系统在每次 tick 的上下文中已自动提供摘要版本。"
        "仅在需要更详细信息（如精确方块坐标、远处实体）时才调用此工具。"
    )
    is_read_only = True
    allowed_routes = {"action", "dialogue"}

    def call(self, input: None, ctx: ToolContext) -> Any:
        bridge = ctx.agent_context.extra.get("_minecraft_bridge")
        perception = ctx.agent_context.extra.get("_minecraft_perception")
        if bridge is None:
            return {"ok": False, "reason": "bridge not available"}
        if perception is None:
            perception = MinecraftPerception(bridge)
        snapshot = perception.snapshot()
        return {
            "ok": True,
            "stats": snapshot.get("stats", {}),
            "blocks": snapshot.get("blocks", {}),
            "entities": snapshot.get("entities", {}),
        }


class CheckInventoryTool(ToolDef):
    name = "check_inventory"
    description = (
        "获取完整物品栏：所有物品及其数量、装备的盔甲、手持物品、空余格子数。"
        "系统上下文中只包含物品摘要。需要精确库存信息时调用此工具。"
    )
    is_read_only = True
    allowed_routes = {"action", "dialogue"}

    def call(self, input: None, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        return bridge.call("get_inventory")


class CheckCraftableTool(ToolDef):
    name = "check_craftable"
    description = (
        "获取当前物品栏可合成的所有物品列表。"
        "在合成前调用此工具确认自己是否有足够的材料。"
    )
    is_read_only = True
    allowed_routes = {"action"}

    def call(self, input: None, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        return bridge.call("get_craftable")


# ── Helper ──────────────────────────────────────────────────────────────────

def _get_bridge(ctx: ToolContext):
    bridge = ctx.agent_context.extra.get("_minecraft_bridge")
    if bridge is None:
        raise RuntimeError("MinecraftBridge not found in agent context")
    return bridge

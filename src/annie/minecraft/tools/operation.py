"""Block/item operation tools.

Mirrors mindcraft commands: !collectBlocks, !placeHere, !equip, !consume,
!discard, !pickupNearbyItems, and related actions from skills.js.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from annie.npc.tools.base_tool import ToolContext, ToolDef


# ── Input schemas ───────────────────────────────────────────────────────────

class BreakBlockInput(BaseModel):
    x: float = Field(..., description="方块 X 坐标")
    y: float = Field(..., description="方块 Y 坐标")
    z: float = Field(..., description="方块 Z 坐标")


class CollectItemInput(BaseModel):
    item_type: str = Field(..., description="要收集的物品/方块类型，如 oak_log, iron_ore")
    count: int = Field(default=1, ge=1, le=64, description="收集数量，默认1")


class EquipInput(BaseModel):
    item_name: str = Field(..., description="要装备/切换到手中的物品名称")


class ConsumeInput(BaseModel):
    item_name: str = Field(..., description="要食用/饮用的物品名称，如 apple, cooked_beef")


class DiscardInput(BaseModel):
    item_name: str = Field(..., description="要丢弃的物品名称")
    count: int = Field(default=1, ge=1, le=64, description="丢弃数量")


class PlaceBlockInput(BaseModel):
    x: float = Field(..., description="参考方块 X 坐标（要放置位置旁边的方块）")
    y: float = Field(..., description="参考方块 Y 坐标")
    z: float = Field(..., description="参考方块 Z 坐标")
    block_type: str = Field(..., description="要放置的方块类型，如 crafting_table, dirt")


class PickupNearbyInput(BaseModel):
    radius: int = Field(default=8, ge=1, le=32, description="拾取半径，默认8格")


# ── Tools ───────────────────────────────────────────────────────────────────

class BreakBlockTool(ToolDef):
    name = "break_block"
    description = "挖掘指定坐标的方块。需要走到方块旁边才能挖掘。用于收集资源和清理地形。"
    input_schema = BreakBlockInput
    is_read_only = False

    def call(self, input: BreakBlockInput, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        return bridge.call("break_block", {"x": input.x, "y": input.y, "z": input.z})


class CollectItemTool(ToolDef):
    name = "collect_item"
    description = (
        "收集指定类型和数量的方块/物品。会自动寻找最近的此类方块、走过去并挖掘。"
        "例如：collect_item(item_type='oak_log', count=5) 收集 5 个橡木原木。"
    )
    input_schema = CollectItemInput
    is_read_only = False
    ends_activation_on_success = True

    def call(self, input: CollectItemInput, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        return bridge.call("collect_block", {
            "block_type": input.item_type,
            "count": input.count,
        })


class EquipTool(ToolDef):
    name = "equip"
    description = "装备/切换到指定物品到手中。战斗前切武器、挖掘前切工具、放置方块前切方块。"
    input_schema = EquipInput
    is_read_only = False

    def call(self, input: EquipInput, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        return bridge.call("equip", {"item_name": input.item_name})


class ConsumeTool(ToolDef):
    name = "consume"
    description = "食用或饮用指定物品。饥饿度低时优先使用。只能食用食物类物品。"
    input_schema = ConsumeInput
    is_read_only = False

    def call(self, input: ConsumeInput, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        return bridge.call("consume", {"item_name": input.item_name})


class DiscardTool(ToolDef):
    name = "discard"
    description = "丢弃指定物品。用于清理不需要的物品腾出背包空间。"
    input_schema = DiscardInput
    is_read_only = False

    def call(self, input: DiscardInput, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        return bridge.call("discard", {"item_name": input.item_name, "count": input.count})


class PickupNearbyTool(ToolDef):
    name = "pickup_nearby"
    description = "拾取周围指定半径内的所有掉落物。看到地上有物品时使用。"
    input_schema = PickupNearbyInput
    is_read_only = False
    ends_activation_on_success = True

    def call(self, input: PickupNearbyInput, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        return bridge.call("pickup_nearby", {"radius": input.radius})


class PlaceBlockTool(ToolDef):
    name = "place_block"
    description = (
        "在指定坐标放置方块。需先用 equip 把要放的方块拿在手里。"
        "x/y/z 是要放置位置旁边的参考方块坐标。"
    )
    input_schema = PlaceBlockInput
    is_read_only = False

    def call(self, input: PlaceBlockInput, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        return bridge.call("place_block", {
            "x": input.x,
            "y": input.y,
            "z": input.z,
            "block_type": input.block_type,
        })


# ── Helper ──────────────────────────────────────────────────────────────────

def _get_bridge(ctx: ToolContext):
    bridge = ctx.agent_context.extra.get("_minecraft_bridge")
    if bridge is None:
        raise RuntimeError("MinecraftBridge not found in agent context")
    return bridge

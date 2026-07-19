"""Storage tools — view_chest, take_from_chest, put_in_chest.

Mirrors mindcraft commands: viewChest, takeFromChest, putInChest.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from annie.npc.tools.base_tool import ToolContext, ToolDef


# ── Input schemas ───────────────────────────────────────────────────────────

class ChestAtInput(BaseModel):
    x: float = Field(..., description="箱子的 X 坐标")
    y: float = Field(..., description="箱子的 Y 坐标")
    z: float = Field(..., description="箱子的 Z 坐标")


class TakeFromChestInput(BaseModel):
    x: float = Field(..., description="箱子的 X 坐标")
    y: float = Field(..., description="箱子的 Y 坐标")
    z: float = Field(..., description="箱子的 Z 坐标")
    item_name: str = Field(..., description="要取出的物品名称")
    count: int = Field(default=1, ge=1, le=64, description="取出数量")


class PutInChestInput(BaseModel):
    x: float = Field(..., description="箱子的 X 坐标")
    y: float = Field(..., description="箱子的 Y 坐标")
    z: float = Field(..., description="箱子的 Z 坐标")
    item_name: str = Field(..., description="要存入的物品名称")
    count: int = Field(default=1, ge=1, le=64, description="存入数量")


# ── Tools ───────────────────────────────────────────────────────────────────

class ViewChestTool(ToolDef):
    name = "view_chest"
    description = (
        "查看指定坐标箱子的内容物。返回箱子里所有物品的列表和数量。"
        "用于检查物资、确认箱子里有什么。"
    )
    input_schema = ChestAtInput
    is_read_only = True
    allowed_routes = {"action"}

    def call(self, input: ChestAtInput, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        return bridge.call("open_chest", {
            "x": input.x, "y": input.y, "z": input.z,
        })


class TakeFromChestTool(ToolDef):
    name = "take_from_chest"
    description = (
        "从指定坐标的箱子中取出物品。取出后物品会进入自己的背包。"
        "用于从仓库取物资、使用公共存储。"
    )
    input_schema = TakeFromChestInput
    is_read_only = False

    def call(self, input: TakeFromChestInput, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        return bridge.call("take_from_chest", {
            "x": input.x, "y": input.y, "z": input.z,
            "item_name": input.item_name,
            "count": input.count,
        })


class PutInChestTool(ToolDef):
    name = "put_in_chest"
    description = (
        "将背包中的物品存入指定坐标的箱子。存入后物品会从背包移除。"
        "用于整理物资、将收集的资源存入仓库。"
    )
    input_schema = PutInChestInput
    is_read_only = False

    def call(self, input: PutInChestInput, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        return bridge.call("put_in_chest", {
            "x": input.x, "y": input.y, "z": input.z,
            "item_name": input.item_name,
            "count": input.count,
        })


# ── Helper ──────────────────────────────────────────────────────────────────

def _get_bridge(ctx: ToolContext):
    bridge = ctx.agent_context.extra.get("_minecraft_bridge")
    if bridge is None:
        raise RuntimeError("MinecraftBridge not found in agent context")
    return bridge

"""Crafting tools — craft, get_crafting_plan.

Mirrors mindcraft commands: !craftRecipe, !getCraftingPlan.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from annie.npc.tools.base_tool import ToolContext, ToolDef


# ── Input schemas ───────────────────────────────────────────────────────────

class CraftInput(BaseModel):
    item_name: str = Field(..., description="要合成的目标物品名称，如 stick, wooden_pickaxe")
    count: int = Field(default=1, ge=1, le=64, description="合成数量，默认1")


class GetCraftingPlanInput(BaseModel):
    item_name: str = Field(..., description="要查询合成方案的目标物品名称")
    count: int = Field(default=1, ge=1, le=64, description="目标数量，默认1")


class SmeltItemInput(BaseModel):
    item_name: str = Field(..., description="要烧炼的物品名称, 如 iron_ore, raw_beef")
    count: int = Field(default=1, ge=1, le=64, description="烧炼数量，默认1")


# ── Tools ───────────────────────────────────────────────────────────────────

class CraftTool(ToolDef):
    name = "craft"
    description = (
        "合成指定物品。自动判断是否需要工作台。"
        "常见配方：stick=2木板, wooden_pickaxe=3木板+2木棍, "
        "stone_pickaxe=3圆石+2木棍, crafting_table=4木板。"
    )
    input_schema = CraftInput
    is_read_only = False

    def call(self, input: CraftInput, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        return bridge.call("craft_recipe", {"item_name": input.item_name, "count": input.count})


class GetCraftingPlanTool(ToolDef):
    name = "get_crafting_plan"
    description = (
        "查询合成指定物品所需的材料和步骤。返回包含所需材料清单、"
        "当前库存是否足够、以及是否需要工作台的完整合成方案。"
    )
    input_schema = GetCraftingPlanInput
    is_read_only = True
    allowed_routes = {"action"}

    def call(self, input: GetCraftingPlanInput, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        target = input.item_name
        target_count = input.count

        try:
            # Get current inventory
            inventory = bridge.call("get_inventory")
            items = inventory.get("items", {}) if isinstance(inventory, dict) else {}

            # Get craftable items list
            craftable_result = bridge.call("get_craftable")
            if not isinstance(craftable_result, dict):
                return {"ok": True, "target": target, "can_craft": False,
                        "reason": "无法获取合成列表", "hint": "直接尝试用 craft 工具合成"}

            craftable_list = craftable_result.get("craftable", [])
            if not isinstance(craftable_list, list):
                craftable_list = []

            # Check if target is craftable (handle both string and dict entries)
            can_craft = False
            for entry in craftable_list:
                name = entry.get("name") if isinstance(entry, dict) else entry
                if name == target:
                    can_craft = True
                    break

            if can_craft:
                return {
                    "ok": True, "target": target, "target_count": target_count,
                    "can_craft": True,
                    "hint": f"可以合成 {target}，直接使用 craft 工具",
                    "inventory": {k: v for k, v in items.items() if v > 0},
                }
            else:
                return {
                    "ok": True, "target": target, "can_craft": False,
                    "reason": f"{target} 不在可合成列表中",
                    "craftable_options": [
                        (e.get("name") if isinstance(e, dict) else str(e))
                        for e in craftable_list[:15]
                    ],
                    "hint": "先收集基础材料（原木→木板→木棍），再尝试合成",
                }
        except Exception as e:
            return {"ok": False, "reason": f"查询失败: {e}"}


class SmeltItemTool(ToolDef):
    name = "smelt_item"
    description = (
        "在熔炉中烧炼物品（需要燃料如煤炭/木炭/原木）。"
        "自动寻找附近的熔炉，如果没有且背包里有熔炉则自动放置。"
        "常用：铁矿石→铁锭、生牛肉→熟牛肉、沙子→玻璃。"
    )
    input_schema = SmeltItemInput
    is_read_only = False
    ends_activation_on_success = True

    def call(self, input: SmeltItemInput, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        return bridge.call("smelt_item", {
            "item_name": input.item_name,
            "count": input.count,
        })


class ClearFurnaceTool(ToolDef):
    name = "clear_furnace"
    description = (
        "取出最近熔炉中所有已烧炼完成的物品。"
        "烧炼完成（燃料耗尽或物品烧完）后使用此工具收取成品。"
    )
    is_read_only = False

    def call(self, input: None, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        return bridge.call("clear_furnace")


def _get_bridge(ctx: ToolContext):
    bridge = ctx.agent_context.extra.get("_minecraft_bridge")
    if bridge is None:
        raise RuntimeError("MinecraftBridge not found in agent context")
    return bridge

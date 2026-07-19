"""Movement tools — go_to_coordinates, go_to_block, stop_moving.

Mirrors mindcraft commands: !goToCoordinates, !goToPlayer, !followPlayer,
!moveAway, !searchForBlock.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from annie.npc.tools.base_tool import ToolContext, ToolDef


# ── Input schemas ───────────────────────────────────────────────────────────

class GoToCoordinatesInput(BaseModel):
    x: float = Field(..., description="目标 X 坐标")
    y: float = Field(..., description="目标 Y 坐标")
    z: float = Field(..., description="目标 Z 坐标")


class GoToBlockInput(BaseModel):
    block_type: str = Field(..., description="目标方块类型，如 oak_log, crafting_table")
    radius: int = Field(default=64, description="搜索半径，默认64格")


class MoveAwayInput(BaseModel):
    distance: int = Field(default=10, ge=1, le=64, description="远离距离（格），默认10格")


class DigDownInput(BaseModel):
    depth: int = Field(default=3, ge=1, le=20, description="向下挖掘深度，默认3格")


class FollowPlayerInput(BaseModel):
    username: str = Field(..., description="要跟随的玩家名称")
    distance: int = Field(default=4, ge=1, le=16, description="保持距离（格），默认4格")


class GoToPlayerInput(BaseModel):
    username: str = Field(..., description="要汇合的玩家名称")


# ── Tools ───────────────────────────────────────────────────────────────────

class GoToCoordinatesTool(ToolDef):
    name = "go_to_coordinates"
    description = (
        "使用路径规划走到指定坐标 (x, y, z)。"
        "这是一个长时动作——发出后你不需要等待完成，结果会在下一次 tick 中反馈。"
        "用于：移动到资源旁、探索指定位置、到达建造地点。"
    )
    input_schema = GoToCoordinatesInput
    is_read_only = False
    ends_activation_on_success = True

    def call(self, input: GoToCoordinatesInput, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        result = bridge.call("go_to", {"x": input.x, "y": input.y, "z": input.z})
        return result


class GoToBlockTool(ToolDef):
    name = "go_to_block"
    description = (
        "走到最近的指定类型方块旁。例如 'oak_log' 走到最近的橡木原木。"
        "仅在需要到达特定方块类型时使用，不要用于收集——收集用 collect_item。"
    )
    input_schema = GoToBlockInput
    is_read_only = False
    ends_activation_on_success = True

    def call(self, input: GoToBlockInput, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        result = bridge.call("go_to_block", {
            "block_type": input.block_type,
            "radius": input.radius,
        })
        return result


class StopMovingTool(ToolDef):
    name = "stop_moving"
    description = "立即停止所有移动动作。用于紧急情况或改变计划时。"
    is_read_only = False

    def call(self, input: None, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        return bridge.call("stop_moving")


class MoveAwayTool(ToolDef):
    name = "move_away"
    description = (
        "远离当前位置一段距离。向远离最近威胁（敌对生物/危险方块）的方向移动。"
        "用于紧急避险：逃离怪物、远离岩浆。"
    )
    input_schema = MoveAwayInput
    is_read_only = False
    ends_activation_on_success = True

    def call(self, input: MoveAwayInput, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        return bridge.call("move_away", {"distance": input.distance})


class DigDownTool(ToolDef):
    name = "dig_down"
    description = (
        "向下挖掘指定深度。自带安全检查，会在遇到岩浆、水或基岩时自动停止。"
        "用于采矿、挖地下室、寻找洞穴。"
    )
    input_schema = DigDownInput
    is_read_only = False
    ends_activation_on_success = True

    def call(self, input: DigDownInput, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        return bridge.call("dig_down", {"depth": input.depth})


class GoToSurfaceTool(ToolDef):
    name = "go_to_surface"
    description = (
        "从当前位置垂直向上挖掘到地表。遇到岩浆或水会自动停止。"
        "用于从矿洞或地下结构中安全返回地面。"
    )
    is_read_only = False
    ends_activation_on_success = True

    def call(self, input: None, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        return bridge.call("go_to_surface")


class FollowPlayerTool(ToolDef):
    name = "follow_player"
    description = (
        "跟随指定玩家，保持一定距离。会持续跟随直到被其他指令打断。"
        "用于陪伴玩家探索、协助搬运等场景。"
    )
    input_schema = FollowPlayerInput
    is_read_only = False
    ends_activation_on_success = True

    def call(self, input: FollowPlayerInput, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        return bridge.call("follow_player", {
            "username": input.username,
            "distance": input.distance,
        })


class GoToPlayerTool(ToolDef):
    name = "go_to_player"
    description = (
        "走到指定玩家身边（2格内）。用于快速与玩家汇合。"
    )
    input_schema = GoToPlayerInput
    is_read_only = False
    ends_activation_on_success = True

    def call(self, input: GoToPlayerInput, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        return bridge.call("go_to_player", {"username": input.username})


# ── Helper ──────────────────────────────────────────────────────────────────

def _get_bridge(ctx: ToolContext):
    """Retrieve the MinecraftBridge from agent context extra."""
    bridge = ctx.agent_context.extra.get("_minecraft_bridge")
    if bridge is None:
        raise RuntimeError("MinecraftBridge not found in agent context")
    return bridge

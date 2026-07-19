"""Interaction tools — send_chat, give_to_player.

Mirrors mindcraft commands: !givePlayer and chat interaction patterns.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from annie.npc.tools.base_tool import ToolContext, ToolDef


# ── Input schemas ───────────────────────────────────────────────────────────

class SendChatInput(BaseModel):
    message: str = Field(..., description="要发送的聊天消息内容")


class GiveToPlayerInput(BaseModel):
    item_name: str = Field(..., description="要给玩家的物品名称")
    username: str = Field(..., description="接收物品的玩家名称")
    count: int = Field(default=1, ge=1, le=64, description="给与数量，默认1")


# ── Tools ───────────────────────────────────────────────────────────────────

class SendChatTool(ToolDef):
    name = "send_chat"
    description = (
        "在 Minecraft 聊天中发送消息。用于向玩家报告任务进度、"
        "询问问题、或进行简单对话。消息会显示在所有人的聊天栏中。"
    )
    input_schema = SendChatInput
    is_read_only = False

    def call(self, input: SendChatInput, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        return bridge.call("send_chat", {"message": input.message})


class GiveToPlayerTool(ToolDef):
    name = "give_to_player"
    description = (
        "将物品从背包中扔给指定玩家。物品会以掉落物形式出现在地上供玩家拾取。"
        "用于分享资源、交付任务物品。需要玩家在附近。"
    )
    input_schema = GiveToPlayerInput
    is_read_only = False

    def call(self, input: GiveToPlayerInput, ctx: ToolContext) -> Any:
        bridge = _get_bridge(ctx)
        return bridge.call("give_to_player", {
            "item_name": input.item_name,
            "username": input.username,
            "count": input.count,
        })


# ── Helper ──────────────────────────────────────────────────────────────────

def _get_bridge(ctx: ToolContext):
    bridge = ctx.agent_context.extra.get("_minecraft_bridge")
    if bridge is None:
        raise RuntimeError("MinecraftBridge not found in agent context")
    return bridge

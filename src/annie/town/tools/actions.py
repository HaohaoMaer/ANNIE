"""Town-specific tools injected by TownWorldEngine."""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from pydantic import BaseModel, Field

from annie.npc.response import ActionResult
from annie.npc.tools.base_tool import ToolContext, ToolDef

T = TypeVar("T", bound=BaseModel)


class MoveToInput(BaseModel):
    destination_id: str = Field(..., description="可达目标地点的 id。")


class WaitInput(BaseModel):
    minutes: int = Field(..., ge=1, le=240, description="当前 NPC 需要等待的分钟数。")


class FinishScheduleSegmentInput(BaseModel):
    note: str = Field("", description="简短说明为什么当前日程段已经完成。")


class SpeakToInput(BaseModel):
    target_npc_id: str = Field(..., description="同一地点内可见 NPC 的 id。")
    text: str = Field(..., min_length=1, description="要对目标 NPC 说的话。")


class StartConversationInput(BaseModel):
    target_npc_id: str = Field(..., description="同一地点内想要主动交谈的 NPC id。")
    topic_or_reason: str = Field(
        "",
        description="想要开启这次对话的简短话题或原因。",
    )


class InteractWithInput(BaseModel):
    object_id: str = Field(..., description="当前位置可见物体的 id。")
    intent: str = Field(..., min_length=1, description="本次交互的目的或动作描述。")


class MoveToTool(ToolDef):
    name = "move_to"
    description = (
        "按地点 id 沿出口移动到目标地点，并消耗对应移动时间。只能使用明确列出的出口。"
        "如果当前日程目标地点不能直接到达，"
        "先移动到一个可达的中转地点。"
    )
    input_schema = MoveToInput
    is_read_only = False
    ends_activation_on_success = True

    def __init__(self, move_to: Callable[[str], ActionResult]) -> None:
        self._move_to = move_to

    def call(self, input: BaseModel | dict, ctx: ToolContext) -> Any:
        inp = _coerce(input, MoveToInput)
        result = self._move_to(inp.destination_id)
        ctx.runtime.setdefault("action_results", []).append(result)
        return result.model_dump()


class ObserveTool(ToolDef):
    name = "observe"
    description = (
        "仅在当前上下文信息不足、需要刷新本地可见状态、"
        "新事件细节不清或工具失败后需要确认环境时，查看当前本地小镇状态。"
        "如果 <situation> 已经明确给出当前位置、出口、可见 NPC、可见物体、"
        "本地事件和当前日程段，不要把 observe 当作行动前默认步骤。"
        "observe 只查看状态，不代表世界行动完成，也不会推进全局时钟，"
        "不能替代移动、交互、说话、等待或完成日程。"
    )
    is_read_only = True

    def __init__(self, observe: Callable[[], ActionResult]) -> None:
        self._observe = observe

    def call(self, input: BaseModel | dict, ctx: ToolContext) -> Any:
        result = self._observe()
        ctx.runtime.setdefault("action_results", []).append(result)
        return result.model_dump()


class WaitTool(ToolDef):
    name = "wait"
    description = (
        "选择把接下来 N 分钟用于原地等待。成功后本次行动结束；"
        "这个工具不推进全局模拟时钟，但会让该 NPC 在等待结束前保持忙碌。"
    )
    input_schema = WaitInput
    is_read_only = False
    ends_activation_on_success = True

    def __init__(self, wait: Callable[[int], ActionResult]) -> None:
        self._wait = wait

    def call(self, input: BaseModel | dict, ctx: ToolContext) -> Any:
        inp = _coerce(input, WaitInput)
        result = self._wait(inp.minutes)
        ctx.runtime.setdefault("action_results", []).append(result)
        return result.model_dump()


class FinishScheduleSegmentTool(ToolDef):
    name = "finish_schedule_segment"
    description = (
        "在日程目标已经满足或无法继续时，将当前日程段标记为完成。"
    )
    input_schema = FinishScheduleSegmentInput
    is_read_only = False
    ends_activation_on_success = True

    def __init__(self, finish: Callable[[str], ActionResult]) -> None:
        self._finish = finish

    def call(self, input: BaseModel | dict, ctx: ToolContext) -> Any:
        inp = _coerce(input, FinishScheduleSegmentInput)
        result = self._finish(inp.note)
        ctx.runtime.setdefault("action_results", []).append(result)
        return result.model_dump()


class SpeakToTool(ToolDef):
    name = "speak_to"
    description = (
        "对当前同一地点内可见的 NPC 发送一次短消息，"
        "用于打招呼、通知或回答一句话，并将事件路由给目标 NPC。"
        "成功后本次行动结束；不要用 speak_to 维持多轮聊天。"
    )
    input_schema = SpeakToInput
    is_read_only = False
    ends_activation_on_success = True

    def __init__(self, speak_to: Callable[[str, str], ActionResult]) -> None:
        self._speak_to = speak_to

    def call(self, input: BaseModel | dict, ctx: ToolContext) -> Any:
        inp = _coerce(input, SpeakToInput)
        result = self._speak_to(inp.target_npc_id, inp.text)
        ctx.runtime.setdefault("action_results", []).append(result)
        return result.model_dump()


class StartConversationTool(ToolDef):
    name = "start_conversation"
    description = (
        "当你自己判断值得和同一地点可见 NPC 主动聊天时，"
        "用这个工具发起一段受世界引擎控制的多轮会话。"
        "世界引擎会检查对方是否可聊、最近是否聊过、双方是否忙碌，"
        "并在合适时统一结束会话。不要用 speak_to 维持 NPC-NPC 多轮聊天。"
    )
    input_schema = StartConversationInput
    is_read_only = False
    ends_activation_on_success = True

    def __init__(self, start_conversation: Callable[[str, str], ActionResult]) -> None:
        self._start_conversation = start_conversation

    def call(self, input: BaseModel | dict, ctx: ToolContext) -> Any:
        inp = _coerce(input, StartConversationInput)
        result = self._start_conversation(inp.target_npc_id, inp.topic_or_reason)
        ctx.runtime.setdefault("action_results", []).append(result)
        return result.model_dump()


class InteractWithTool(ToolDef):
    name = "interact_with"
    description = "与当前位置可见物体交互，并写入本地结构化小镇事件。"
    input_schema = InteractWithInput
    is_read_only = False
    ends_activation_on_success = True

    def __init__(self, interact_with: Callable[[str, str], ActionResult]) -> None:
        self._interact_with = interact_with

    def call(self, input: BaseModel | dict, ctx: ToolContext) -> Any:
        inp = _coerce(input, InteractWithInput)
        result = self._interact_with(inp.object_id, inp.intent)
        ctx.runtime.setdefault("action_results", []).append(result)
        return result.model_dump()


def _coerce(input_data: BaseModel | dict, schema: type[T]) -> T:
    if isinstance(input_data, schema):
        return input_data
    if isinstance(input_data, BaseModel):
        return schema(**input_data.model_dump())
    return schema(**input_data)

"""运行真实 LLM 单 NPC 小镇一天日程 smoke 测试。

用法：
    conda run -n annie python scripts/run_town_day_real_llm.py

脚本读取 ``config/model_config.yaml`` 和 ``.env``。项目默认配置通过
``DEEPSEEK_API_KEY`` 调用 DeepSeek。脚本只运行 fixture 中一个 NPC 的日程，
用于在终端检查真实模型调用、工具调用和小镇状态变化。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from annie.npc import NPCAgent
from annie.npc.config import load_model_config
from annie.town import TownWorldEngine, create_small_town_state, run_single_npc_day


class TraceChatModel:
    """打印 LLM 调用和工具调用的轻量包装器，内部模型仍是真实 ChatOpenAI。"""

    def __init__(
        self,
        model: Any,
        *,
        state: dict[str, int] | None = None,
        bound_tool_names: list[str] | None = None,
    ) -> None:
        self._model = model
        self._state = state if state is not None else {"calls": 0}
        self._bound_tool_names = bound_tool_names or []

    @property
    def call_count(self) -> int:
        return self._state["calls"]

    def bind_tools(self, tools: list[dict]) -> "TraceChatModel":
        bound = self._model.bind_tools(tools)
        names = [tool.get("function", {}).get("name", "<unknown>") for tool in tools]
        return TraceChatModel(
            bound,
            state=self._state,
            bound_tool_names=names,
        )

    def invoke(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        self._state["calls"] += 1
        call_no = self._state["calls"]
        print_header(f"LLM 调用 {call_no}")
        print(f"已绑定工具: {', '.join(self._bound_tool_names) or '无'}")
        print("最后一条消息:")
        print(indent(str(messages[-1].content)))

        response = self._model.invoke(messages, **kwargs)
        if not isinstance(response, AIMessage):
            response = AIMessage(content=str(getattr(response, "content", response)))

        if response.tool_calls:
            print("工具调用:")
            print(indent(json.dumps(response.tool_calls, ensure_ascii=False, indent=2)))
        else:
            print("模型回复:")
            print(indent(str(response.content)))
        return response


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    config = load_model_config("config/model_config.yaml")
    print(f"模型: provider={config.model.provider}, name={config.model.model_name}")
    print(f"API 地址: {config.model.base_url}")
    print(f"API Key 环境变量: {config.model.api_key_env}")
    if not config.api_key:
        raise SystemExit(f"缺少 API Key 环境变量: {config.model.api_key_env}")

    real_model = ChatOpenAI(
        model=config.model.model_name,
        base_url=config.model.base_url,
        api_key=SecretStr(config.api_key),
        temperature=config.model.temperature,
        extra_body={"thinking": {"type": "disabled"}},
    )
    traced_model = TraceChatModel(real_model)
    agent = NPCAgent(llm=traced_model)
    engine = TownWorldEngine(create_small_town_state())

    print_header("初始小镇状态")
    print("npc: alice")
    print(f"起点: {engine.state.npc_locations['alice']}")
    for segment in engine.state.schedule_for("alice"):
        print(
            f"- {minute_label(segment.start_minute)}-{minute_label(segment.end_minute)} "
            f"目标地点={segment.location_id} 日程目标={segment.intent}"
        )

    result = run_single_npc_day(
        engine,
        agent,
        "alice",
        max_steps_per_segment=6,
    )

    if traced_model.call_count <= 0:
        raise SystemExit("真实 LLM 调用次数为 0，测试没有实际触发模型。")

    print_header("日程时间线")
    for segment_trace in result.segments:
        segment = segment_trace.segment
        print(
            f"{minute_label(segment.start_minute)} 目标地点={segment.location_id} "
            f"日程目标={segment.intent} 状态={segment_trace.status} "
            f"最终位置={segment_trace.final_location_id}"
        )
        for step in segment_trace.steps:
            print(
                f"  步骤 {step.step}: {step.start_location_id} -> "
                f"{step.end_location_id}; 对话={step.dialogue or '无'}"
            )

    print_header("小镇工具结果")
    for item in engine.action_log:
        print(
            f"{item['time']} npc={item['npc_id']} 动作={item['action_type']} "
            f"状态={item['status']} 位置={item['location_id']}"
        )
        print(indent(str(item["summary"]), prefix="    "))

    print_header("最终结果")
    print(f"真实 LLM 调用次数: {traced_model.call_count}")
    print(f"是否完成: {result.ok}")
    print(f"最终位置: {engine.state.npc_locations['alice']}")


def print_header(title: str) -> None:
    print("\n" + "=" * 10 + f" {title} " + "=" * 10)


def indent(text: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


def minute_label(minute: int) -> str:
    hours, minutes = divmod(minute, 60)
    return f"{hours:02d}:{minutes:02d}"


if __name__ == "__main__":
    main()

"""运行真实 LLM 多 NPC 小镇 tick smoke 测试。

用法：
    conda run -n annie python scripts/run_town_multi_npc_real_llm.py

脚本读取 ``config/model_config.yaml`` 和 ``.env``。项目默认配置通过
``DEEPSEEK_API_KEY`` 调用 DeepSeek。脚本会运行 Alice、Bob、Clara 三个
NPC 的短时段多 NPC tick，并输出真实模型调用、工具调用、小镇动作日志和
replay 文件位置。
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import chromadb
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from annie.npc import NPCAgent
from annie.npc.config import load_model_config
from annie.town import (
    ScheduleSegment,
    TownWorldEngine,
    create_small_town_state,
    run_multi_npc_day,
)


class TraceChatModel:
    """打印 LLM 调用和工具调用的轻量包装器，内部模型仍是真实 ChatOpenAI。"""

    def __init__(
        self,
        model: Any,
        *,
        state: dict[str, int] | None = None,
        bound_tool_names: list[str] | None = None,
        verbose_messages: bool = False,
    ) -> None:
        self._model = model
        self._state = state if state is not None else {"calls": 0}
        self._bound_tool_names = bound_tool_names or []
        self._verbose_messages = verbose_messages

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
            verbose_messages=self._verbose_messages,
        )

    def invoke(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        self._state["calls"] += 1
        call_no = self._state["calls"]
        print_header(f"LLM 调用 {call_no}")
        print(f"已绑定工具: {', '.join(self._bound_tool_names) or '无'}")
        if self._verbose_messages:
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
    args = parse_args()
    load_dotenv()
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    run_dir = args.output_dir or default_run_dir()
    replay_dir = run_dir / "replay"
    history_dir = run_dir / "history"
    vector_dir = run_dir / "vector_store"
    run_dir.mkdir(parents=True, exist_ok=True)

    config = load_model_config(args.model_config)
    print_header("模型配置")
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
    traced_model = TraceChatModel(real_model, verbose_messages=args.verbose_messages)
    agent = NPCAgent(llm=traced_model, max_retries=args.max_retries)
    engine = TownWorldEngine(
        create_small_town_state(),
        chroma_client=chromadb.PersistentClient(path=str(vector_dir)),
        history_dir=history_dir,
    )

    npc_ids = [item.strip() for item in args.npcs.split(",") if item.strip()]
    print_header("初始小镇状态")
    print(f"运行 NPC: {', '.join(npc_ids)}")
    print(f"时间窗口: {minute_label(args.start_minute)}-{minute_label(args.end_minute)}")
    print(f"最大 tick: {args.max_ticks}")
    print(f"输出目录: {run_dir}")
    print_world_snapshot(engine)
    print("fixture 原始 resident schedule:")
    print_schedules(engine, npc_ids)

    planning_call_count = 0
    if not args.skip_resident_planning:
        print_header("新增内容: resident daily planning")
        print(
            "真实 LLM 先为每个 NPC 生成候选日程；"
            "TownWorldEngine.generate_day_plan_for_resident() 调用 NPCAgent，"
            "再经 plan_day_for_resident() 校验后写入 resident.schedule。"
        )
        for npc_id in npc_ids:
            before = schedule_signature(engine.state.schedule_for(npc_id))
            before_calls = traced_model.call_count
            accepted = engine.generate_day_plan_for_resident(
                npc_id,
                agent,
                start_minute=args.start_minute,
                end_minute=args.end_minute,
            )
            planning_call_count += traced_model.call_count - before_calls
            changed = schedule_signature(accepted) != before
            print(f"[Planning Accepted] npc={npc_id} changed={changed}")
            print_schedule(engine, npc_id, prefix="  ")

        print_header("planning 后的 resident schedule")
        print("下面这些日程已进入 resident state，后续 multi-NPC runner 会从这里读取。")
        print_schedules(engine, npc_ids)

        print_header("context proof")
        for npc_id in npc_ids:
            context = engine.build_context(npc_id, "检查 planning 后的当前日程。")
            current_schedule = context.extra["town"]["current_schedule"]
            print(f"{npc_id} current_schedule:")
            print(indent(json.dumps(current_schedule, ensure_ascii=False, indent=2)))

    result = run_multi_npc_day(
        engine,
        agent,
        npc_ids,
        start_minute=args.start_minute,
        end_minute=args.end_minute,
        max_ticks=args.max_ticks,
        replay_dir=replay_dir,
        reflection_agent=agent if args.enable_reflection else None,
    )

    print_header("Tick 结果")
    for tick in result.ticks:
        print(
            f"tick={tick.tick} time={minute_label(tick.minute)} "
            f"ran={tick.ran_npc_ids or ['none']} "
            f"skipped={tick.skipped_npc_ids or ['none']} "
            f"actions={tick.action_count} "
            f"reflections={tick.reflection_count}"
        )

    print_header("小镇动作日志")
    if not engine.action_log:
        print("没有产生小镇动作。")
    for item in engine.action_log:
        print(
            f"{item['time']} npc={item['npc_id']} 动作={item['action_type']} "
            f"状态={item['status']} 位置={item['location_id']}"
        )
        print(indent(str(item["summary"]), prefix="    "))

    print_header("最终小镇状态")
    print_world_snapshot(engine)
    print_schedule_completion(engine, npc_ids)

    print_header("验证摘要")
    action_types = [str(item["action_type"]) for item in engine.action_log]
    print(f"resident planning LLM 调用次数: {planning_call_count}")
    print(f"真实 LLM 总调用次数: {traced_model.call_count}")
    print(f"multi-NPC 行动/认知 LLM 调用次数: {traced_model.call_count - planning_call_count}")
    print(f"runner ok: {result.ok}")
    if result.note:
        print(f"runner note: {result.note}")
    print(f"动作类型: {', '.join(sorted(set(action_types))) if action_types else '无'}")
    print(f"移动动作数: {action_types.count('move_to') + action_types.count('move')}")
    print(f"对话动作数: {action_types.count('speak_to')}")
    print(f"交互动作数: {action_types.count('interact_with')}")
    print(f"reflection 事件数: {len(engine.reflection_log)}")
    print("Replay 文件:")
    for name, path in result.replay_paths.items():
        print(f"- {name}: {path}")

    if traced_model.call_count <= 0:
        raise SystemExit("真实 LLM 调用次数为 0，测试没有实际触发模型。")
    if not result.ok and not args.allow_incomplete:
        raise SystemExit("多 NPC runner 未正常完成，请检查上方 tick 与动作日志。")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run real-LLM multi-NPC town smoke.")
    parser.add_argument("--model-config", default="config/model_config.yaml")
    parser.add_argument("--npcs", default="alice,bob,clara")
    parser.add_argument("--start-minute", type=int, default=8 * 60)
    parser.add_argument("--end-minute", type=int, default=10 * 60)
    parser.add_argument("--max-ticks", type=int, default=12)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--skip-resident-planning",
        action="store_true",
        help="跳过新增 resident daily planning 阶段，只跑旧的 multi-NPC smoke。",
    )
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="即使 runner 因 max_ticks 到达上限而未完成，也以 0 退出。适合短 smoke。",
    )
    parser.add_argument(
        "--enable-reflection",
        action="store_true",
        help="启用 opt-in reflection runner；默认关闭以避免额外真实 LLM 调用。",
    )
    parser.add_argument(
        "--verbose-messages",
        action="store_true",
        help="打印每次 LLM 调用的最后一条 prompt 消息。",
    )
    return parser.parse_args()


def default_run_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("data/town/live_multi_npc") / stamp


def print_world_snapshot(engine: TownWorldEngine) -> None:
    state = engine.state
    print(f"[World State] {state.clock.label()}")
    for location in state.locations.values():
        exits = ", ".join(location.exits) if location.exits else "none"
        occupants = ", ".join(location.occupant_ids) if location.occupant_ids else "none"
        objects = ", ".join(location.object_ids) if location.object_ids else "none"
        print(f"- {location.id}: {location.name}")
        print(f"  exits: {exits}")
        print(f"  occupants: {occupants}")
        print(f"  objects: {objects}")


def print_schedules(engine: TownWorldEngine, npc_ids: list[str]) -> None:
    print("[Schedules]")
    for npc_id in npc_ids:
        print(f"- {npc_id}")
        print_schedule(engine, npc_id, prefix="  ")


def print_schedule(engine: TownWorldEngine, npc_id: str, *, prefix: str = "") -> None:
    for segment in engine.state.schedule_for(npc_id):
        print(
            f"{prefix}{minute_label(segment.start_minute)}-{minute_label(segment.end_minute)} "
            f"目标地点={segment.location_id} 日程目标={segment.intent}"
        )


def print_schedule_completion(engine: TownWorldEngine, npc_ids: list[str]) -> None:
    print("[Schedule Completion]")
    for npc_id in npc_ids:
        completed = engine.state.completed_schedule_segments.get(npc_id, [])
        if not completed:
            print(f"- {npc_id}: 无完成日程")
            continue
        for item in completed:
            print(
                f"- {npc_id}: start={minute_label(item.start_minute)} "
                f"location={item.location_id} note={item.note}"
            )


def schedule_signature(schedule: list[ScheduleSegment]) -> list[tuple[int, int, str, str]]:
    return [
        (
            segment.start_minute,
            segment.duration_minutes,
            segment.location_id,
            segment.intent,
        )
        for segment in schedule
    ]


def print_header(title: str) -> None:
    print("\n" + "=" * 10 + f" {title} " + "=" * 10)


def indent(text: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


def minute_label(minute: int) -> str:
    hours, minutes = divmod(minute, 60)
    return f"{hours:02d}:{minutes:02d}"


if __name__ == "__main__":
    main()

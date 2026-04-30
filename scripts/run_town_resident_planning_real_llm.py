"""真实 LLM resident daily planning smoke 测试。

用法：
    conda run -n annie python scripts/run_town_resident_planning_real_llm.py

这个脚本专门验证当前阶段新增的架构路径：

1. 真实 LLM 为 resident 生成候选日程 JSON。
2. TownWorldEngine.plan_day_for_resident() 校验并持久化到 resident state。
3. build_context() 从新的 resident schedule 渲染当前日程。
4. run_single_npc_day() 按新 resident schedule 执行。

注意：这不是 2.4 的 NPCAgent-backed daily planning 正式实现；这里只在
smoke 脚本里用真实 LLM 生成候选 schedule，以便在终端直接观察当前改动的影响。
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import chromadb
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from annie.npc.config import load_model_config
from annie.npc.context import AgentContext
from annie.npc.response import AgentResponse
from annie.npc.tools.base_tool import ToolContext
from annie.town import (
    ScheduleSegment,
    TownWorldEngine,
    create_small_town_state,
    run_single_npc_day,
)


class ToolDrivingAgent:
    """Small deterministic executor so this smoke isolates the planning path."""

    def run(self, context: AgentContext) -> AgentResponse:
        town = context.extra["town"]
        target = town["current_schedule_target_location_id"]
        location = town["location_id"]
        exits = town["exits"]
        tool_context = ToolContext(agent_context=context, runtime={})

        if location == target:
            _tool(context, "finish_schedule_segment").safe_call(
                {"note": "已到达 LLM 计划中的目标地点"},
                tool_context,
            )
            return AgentResponse(dialogue=f"完成日程目标：{target}")

        destination = target if target in exits else exits[0]
        _tool(context, "move_to").safe_call(
            {"destination_id": destination},
            tool_context,
        )
        return AgentResponse(dialogue=f"按 LLM 日程移动到 {destination}")


def main() -> None:
    args = parse_args()
    load_dotenv()
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    run_dir = args.output_dir or default_run_dir()
    vector_dir = run_dir / "vector_store"
    history_dir = run_dir / "history"
    run_dir.mkdir(parents=True, exist_ok=True)

    config = load_model_config(args.model_config)
    print_header("模型配置")
    print(f"模型: provider={config.model.provider}, name={config.model.model_name}")
    print(f"API 地址: {config.model.base_url}")
    print(f"API Key 环境变量: {config.model.api_key_env}")
    if not config.api_key:
        raise SystemExit(f"缺少 API Key 环境变量: {config.model.api_key_env}")

    engine = TownWorldEngine(
        create_small_town_state(),
        chroma_client=chromadb.PersistentClient(path=str(vector_dir)),
        history_dir=history_dir,
    )

    print_header("Before: fixture resident schedule")
    print(f"resident: {args.npc_id}")
    print(f"resident location: {engine.state.location_id_for(args.npc_id)}")
    print_schedule(engine, args.npc_id)
    before_signature = schedule_signature(engine.state.schedule_for(args.npc_id))

    llm = ChatOpenAI(
        model=config.model.model_name,
        base_url=config.model.base_url,
        api_key=SecretStr(config.api_key),
        temperature=args.temperature,
        extra_body={"thinking": {"type": "disabled"}},
    )

    candidate = ask_llm_for_schedule(
        llm,
        engine,
        args.npc_id,
        start_minute=args.start_minute,
        end_minute=args.end_minute,
    )

    print_header("LLM raw candidate schedule")
    print(json.dumps([segment_to_dict(item) for item in candidate], ensure_ascii=False, indent=2))
    if schedule_signature(candidate) == before_signature:
        raise SystemExit(
            "LLM 返回的候选日程与 fixture 原日程完全相同，无法明显验证替换效果。"
            "请重跑脚本或调高 --temperature。"
        )

    accepted = engine.plan_day_for_resident(args.npc_id, candidate)

    print_header("After: plan_day_for_resident accepted schedule")
    print("影响 1: resident.schedule 已被替换")
    print_schedule(engine, args.npc_id)
    print("影响 2: legacy state.schedules 仍是兼容镜像")
    print(
        "legacy mirror equals resident schedule:",
        engine.state.schedules[args.npc_id] == engine.state.residents[args.npc_id].schedule,
    )
    print("accepted object ids:")
    for item in accepted:
        print(
            f"- {minute_label(item.start_minute)}-{minute_label(item.end_minute)} "
            f"{item.location_id}: {item.intent}"
        )

    context = engine.build_context(args.npc_id, "检查新生成的 resident 日程。")
    town_extra = context.extra["town"]

    print_header("Context rendering proof")
    print("影响 3: build_context() 读取新的 resident current_schedule")
    print(json.dumps(town_extra["current_schedule"], ensure_ascii=False, indent=2))
    print("situation 中的当前日程行:")
    for line in context.situation.splitlines():
        if "当前日程" in line:
            print(line)

    print_header("Runner execution proof")
    print("影响 4: run_single_npc_day() 按新的 resident schedule 执行")
    result = run_single_npc_day(
        engine,
        ToolDrivingAgent(),
        args.npc_id,
        max_steps_per_segment=args.max_steps_per_segment,
    )
    for segment_trace in result.segments:
        segment = segment_trace.segment
        print(
            f"{minute_label(segment.start_minute)}-{minute_label(segment.end_minute)} "
            f"目标={segment.location_id}/{segment.intent} "
            f"状态={segment_trace.status} 最终位置={segment_trace.final_location_id}"
        )
        for step in segment_trace.steps:
            print(
                f"  step={step.step} {step.start_location_id} -> {step.end_location_id}; "
                f"actions={step.action_count}; dialogue={step.dialogue or '无'}"
            )

    print_header("Action log")
    if not engine.action_log:
        print("没有产生小镇动作。")
    for item in engine.action_log:
        print(
            f"{item['time']} npc={item['npc_id']} 动作={item['action_type']} "
            f"状态={item['status']} 位置={item['location_id']}"
        )
        print(indent(str(item["summary"]), prefix="    "))

    print_header("验证摘要")
    print("真实 LLM 调用次数: 1")
    print(f"runner ok: {result.ok}")
    print(f"最终 resident location: {engine.state.location_id_for(args.npc_id)}")
    print(f"输出目录: {run_dir}")

    if not result.ok:
        raise SystemExit("runner 未完成 LLM 生成的新日程，请检查上方执行 trace。")


def ask_llm_for_schedule(
    llm: ChatOpenAI,
    engine: TownWorldEngine,
    npc_id: str,
    *,
    start_minute: int,
    end_minute: int,
) -> list[ScheduleSegment]:
    resident = engine.state.resident_for(npc_id)
    if resident is None:
        raise SystemExit(f"unknown resident: {npc_id}")

    locations = [
        {
            "id": location.id,
            "name": location.name,
            "description": location.description,
            "exits": location.exits,
            "objects": location.object_ids,
        }
        for location in engine.state.locations.values()
    ]
    existing_schedule = [segment_to_dict(item) for item in engine.state.schedule_for(npc_id)]
    prompt_payload = {
        "npc_id": npc_id,
        "current_location_id": engine.state.location_id_for(npc_id),
        "planning_window": {
            "start_minute": start_minute,
            "end_minute": end_minute,
            "start_label": minute_label(start_minute),
            "end_label": minute_label(end_minute),
        },
        "known_locations": locations,
        "existing_fixture_schedule": existing_schedule,
    }

    response = llm.invoke(
        [
            SystemMessage(
                content=(
                    "你是 ANNIE TownWorld 的 resident daily planning cognition。"
                    "你只输出 JSON，不输出 markdown。"
                    "你要为指定 npc 生成 2 到 3 个不重叠日程段。"
                    "每个日程段必须使用 known_locations 中存在的 location_id。"
                    "每个日程段必须属于输入 npc_id。"
                    "为了 smoke 测试验证替换效果，绝对不要原样复用 existing_fixture_schedule；"
                    "至少一个日程段的 location_id 或 intent 必须与原 fixture 不同。"
                    "建议包含 town_square 的公告板、问候邻居或晨间观察任务。"
                )
            ),
            HumanMessage(
                content=(
                    "根据下面的小镇状态生成候选日程。输出格式必须是：\n"
                    '{"schedule":[{"npc_id":"alice","start_minute":480,'
                    '"duration_minutes":30,"location_id":"town_square",'
                    '"intent":"查看公告板"}]}\n\n'
                    + json.dumps(prompt_payload, ensure_ascii=False, indent=2)
                )
            ),
        ]
    )
    raw = str(response.content)
    print_header("LLM response text")
    print(raw)

    payload = parse_json_object(raw)
    schedule_items = payload.get("schedule")
    if not isinstance(schedule_items, list):
        raise SystemExit("LLM 输出中缺少 schedule 数组。")

    segments: list[ScheduleSegment] = []
    for item in schedule_items:
        if not isinstance(item, dict):
            raise SystemExit(f"非法日程项: {item!r}")
        segments.append(
            ScheduleSegment(
                npc_id=str(item["npc_id"]),
                start_minute=int(item["start_minute"]),
                duration_minutes=int(item["duration_minutes"]),
                location_id=str(item["location_id"]),
                intent=str(item["intent"]),
            )
        )
    return segments


def parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if match is None:
            raise
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise SystemExit("LLM 输出不是 JSON object。")
    return payload


def print_schedule(engine: TownWorldEngine, npc_id: str) -> None:
    resident = engine.state.residents[npc_id]
    print("[resident.schedule]")
    for segment in resident.schedule:
        print(
            f"- {minute_label(segment.start_minute)}-{minute_label(segment.end_minute)} "
            f"目标地点={segment.location_id} 日程目标={segment.intent}"
        )


def segment_to_dict(segment: ScheduleSegment) -> dict[str, Any]:
    return {
        "npc_id": segment.npc_id,
        "start_minute": segment.start_minute,
        "duration_minutes": segment.duration_minutes,
        "end_minute": segment.end_minute,
        "location_id": segment.location_id,
        "intent": segment.intent,
    }


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


def _tool(context: AgentContext, name: str):
    return next(tool for tool in context.tools if tool.name == name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run real-LLM resident planning smoke.")
    parser.add_argument("--model-config", default="config/model_config.yaml")
    parser.add_argument("--npc-id", default="alice")
    parser.add_argument("--start-minute", type=int, default=8 * 60)
    parser.add_argument("--end-minute", type=int, default=10 * 60)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-steps-per-segment", type=int, default=4)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def default_run_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("data/town/resident_planning_real_llm") / stamp


def print_header(title: str) -> None:
    print("\n" + "=" * 10 + f" {title} " + "=" * 10)


def indent(text: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


def minute_label(minute: int) -> str:
    hours, minutes = divmod(minute, 60)
    return f"{hours:02d}:{minutes:02d}"


if __name__ == "__main__":
    main()

"""真实 LLM 全阶段验证 TownWorld Generative Agents change。

用法：
    conda run -n annie python scripts/validate_townworld_generative_agents_real_llm.py

这个脚本有意比 smoke 更啰嗦：它用真实 NPCAgent 跑 resident planning、
bounded perception、schedule revision、conversation、reflection、multi-NPC runner、
replay snapshot 和 memory artifact 检查，并在终端打印每个阶段的执行细节。
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, field
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
    TownEvent,
    TownPerceptionPolicy,
    TownWorldEngine,
    create_small_town_state,
    run_multi_npc_day,
)


@dataclass
class Check:
    label: str
    ok: bool
    detail: str = ""


@dataclass
class CheckBoard:
    checks: list[Check] = field(default_factory=list)

    def add(self, label: str, ok: bool, detail: str = "") -> None:
        self.checks.append(Check(label=label, ok=ok, detail=detail))
        print(f"{'PASS' if ok else 'FAIL'} {label}" + (f" | {detail}" if detail else ""))

    def require_all(self) -> None:
        failed = [check for check in self.checks if not check.ok]
        if not failed:
            return
        print_header("失败项")
        for check in failed:
            print(f"- {check.label}: {check.detail}")
        raise SystemExit(f"{len(failed)} 个验证项失败。")


class TraceChatModel:
    """真实模型包装器：记录 phase、工具绑定、prompt 摘要和模型响应。"""

    def __init__(
        self,
        model: Any,
        *,
        state: dict[str, Any] | None = None,
        bound_tool_names: list[str] | None = None,
        verbose_messages: bool = False,
        preview_chars: int = 1600,
    ) -> None:
        self._model = model
        self._state = state if state is not None else {"calls": 0, "phase": "bootstrap"}
        self._bound_tool_names = bound_tool_names or []
        self._verbose_messages = verbose_messages
        self._preview_chars = preview_chars

    @property
    def call_count(self) -> int:
        return int(self._state["calls"])

    @property
    def phase(self) -> str:
        return str(self._state["phase"])

    @phase.setter
    def phase(self, value: str) -> None:
        self._state["phase"] = value

    def bind_tools(self, tools: list[dict]) -> "TraceChatModel":
        bound = self._model.bind_tools(tools)
        names = [tool.get("function", {}).get("name", "<unknown>") for tool in tools]
        return TraceChatModel(
            bound,
            state=self._state,
            bound_tool_names=names,
            verbose_messages=self._verbose_messages,
            preview_chars=self._preview_chars,
        )

    def invoke(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        self._state["calls"] += 1
        call_no = self._state["calls"]
        print_header(f"LLM 调用 {call_no} | phase={self.phase}")
        print(f"绑定工具: {', '.join(self._bound_tool_names) or '无'}")
        print(f"消息数: {len(messages)}")
        last_content = str(messages[-1].content) if messages else ""
        if self._verbose_messages:
            print("最后一条消息:")
            print(indent(last_content[: self._preview_chars]))
        else:
            print("最后一条消息摘要:")
            print(indent(squash(last_content)[: self._preview_chars]))

        response = self._model.invoke(messages, **kwargs)
        if not isinstance(response, AIMessage):
            response = AIMessage(content=str(getattr(response, "content", response)))

        if response.tool_calls:
            print("工具调用:")
            print(indent(json.dumps(response.tool_calls, ensure_ascii=False, indent=2)))
        else:
            print("模型回复:")
            print(indent(str(response.content)[: self._preview_chars]))
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
    print_header("验证目标")
    print("OpenSpec change: evolve-townworld-generative-agents")
    print("覆盖阶段: resident state, planning, perception, schedule revision, conversation,")
    print("          reflection, multi-NPC runner, replay snapshot, memory/history artifacts")
    print(f"输出目录: {run_dir}")

    print_header("模型配置")
    print(f"provider={config.model.provider}")
    print(f"model={config.model.model_name}")
    print(f"base_url={config.model.base_url}")
    print(f"api_key_env={config.model.api_key_env}")
    if not config.api_key:
        raise SystemExit(f"缺少 API Key 环境变量: {config.model.api_key_env}")

    real_model = ChatOpenAI(
        model=config.model.model_name,
        base_url=config.model.base_url,
        api_key=SecretStr(config.api_key),
        temperature=args.temperature,
        extra_body={"thinking": {"type": "disabled"}},
    )
    traced_model = TraceChatModel(
        real_model,
        verbose_messages=args.verbose_messages,
        preview_chars=args.preview_chars,
    )
    agent = NPCAgent(llm=traced_model, max_retries=args.max_retries)
    engine = TownWorldEngine(
        create_small_town_state(),
        chroma_client=chromadb.PersistentClient(path=str(vector_dir)),
        history_dir=history_dir,
        perception_policy=TownPerceptionPolicy(
            max_events=args.max_events,
            max_objects=args.max_objects,
            max_npcs=args.max_npcs,
            max_exits=args.max_exits,
        ),
    )
    engine.chat_iter = args.chat_iter
    npc_ids = [item.strip() for item in args.npcs.split(",") if item.strip()]
    checks = CheckBoard()

    print_header("阶段 0: 初始 world/resident 状态")
    print_world(engine, npc_ids)
    print_schedules(engine, npc_ids)
    checks.add(
        "resident state exists for all requested NPCs",
        all(engine.state.resident_for(npc_id) is not None for npc_id in npc_ids),
        ", ".join(npc_ids),
    )
    checks.add(
        "legacy schedule mirrors resident schedule",
        all(
            engine.state.schedules[npc_id] is engine.state.residents[npc_id].schedule
            for npc_id in npc_ids
        ),
    )

    run_planning_phase(engine, agent, traced_model, npc_ids, args, checks)
    run_perception_and_revision_phase(engine, npc_ids, checks)
    run_conversation_phase(engine, agent, traced_model, checks)
    run_reflection_phase(engine, agent, traced_model, checks)
    result = run_multi_npc_phase(engine, agent, traced_model, npc_ids, replay_dir, args, checks)
    run_replay_and_memory_phase(engine, result.replay_paths, npc_ids, checks)

    print_header("最终 world 状态")
    print_world(engine, npc_ids)
    print_schedule_completion(engine, npc_ids)
    print_action_log(engine)
    print_reflections(engine)

    print_header("验证汇总")
    print(f"真实 LLM 调用总数: {traced_model.call_count}")
    print(f"action_log 条数: {len(engine.action_log)}")
    print(f"conversation sessions: {len(engine.state.conversation_sessions)}")
    print(f"reflection events: {len(engine.reflection_log)}")
    print("Replay 文件:")
    for name, path in result.replay_paths.items():
        print(f"- {name}: {path}")
    checks.add("real LLM was called", traced_model.call_count > 0, str(traced_model.call_count))
    if not args.allow_failures:
        checks.require_all()
    else:
        failed = [check for check in checks.checks if not check.ok]
        print(f"allow-failures enabled; failed checks: {len(failed)}")


def run_planning_phase(
    engine: TownWorldEngine,
    agent: NPCAgent,
    traced_model: TraceChatModel,
    npc_ids: list[str],
    args: argparse.Namespace,
    checks: CheckBoard,
) -> None:
    print_header("阶段 1: 真实 LLM resident daily planning")
    for npc_id in npc_ids:
        traced_model.phase = f"planning:{npc_id}"
        before = schedule_signature(engine.state.schedule_for(npc_id))
        try:
            accepted = engine.generate_day_plan_for_resident(
                npc_id,
                agent,
                start_minute=args.start_minute,
                end_minute=args.end_minute,
            )
        except Exception as exc:
            checks.add(f"{npc_id} planning accepted", False, repr(exc))
            if args.abort_on_phase_error:
                raise
            continue
        after = schedule_signature(accepted)
        print(f"[Planning Accepted] npc={npc_id} changed={after != before}")
        print_schedule(engine, npc_id, prefix="  ")
        checks.add(f"{npc_id} planning wrote resident schedule", bool(accepted))
        checks.add(
            f"{npc_id} schedule mirror remains compatible",
            engine.state.schedules[npc_id] is engine.state.residents[npc_id].schedule,
        )
        current = engine.build_context(npc_id, "验证 planning 后的 current_schedule。")
        print(f"{npc_id} current_schedule extra:")
        print(indent(json.dumps(current.extra["town"]["current_schedule"], ensure_ascii=False, indent=2)))
        checks.add(
            f"{npc_id} context renders current_schedule",
            isinstance(current.extra["town"]["current_schedule"], dict),
        )


def run_perception_and_revision_phase(
    engine: TownWorldEngine,
    npc_ids: list[str],
    checks: CheckBoard,
) -> None:
    print_header("阶段 2: bounded perception + schedule revision")
    actor = npc_ids[0]
    engine.state.set_location(actor, "town_square")
    event = TownEvent(
        id="full_validation_urgent_square",
        minute=engine.state.clock.minute,
        location_id="town_square",
        actor_id="gm",
        event_type="urgent",
        summary="广场公告栏旁响起紧急铃声，居民需要判断是否调整计划。",
        target_ids=[actor],
    )
    engine.state.events.append(event)
    context = engine.build_context(actor, "观察广场紧急事件并判断是否调整日程。")
    town = context.extra["town"]
    print("visible_event_ids:", town["visible_event_ids"])
    print("perception:")
    print(indent(json.dumps(town["perception"], ensure_ascii=False, indent=2)))
    print("schedule_revision:")
    print(indent(json.dumps(town["schedule_revision"], ensure_ascii=False, indent=2)))
    resident = engine.state.residents[actor]
    checks.add("urgent event appears in bounded perception", event.id in town["visible_event_ids"])
    checks.add("schedule revision is town-owned", town["schedule_revision"].get("revised") is True)
    checks.add("poignancy accumulated from event", resident.poignancy >= 4, str(resident.poignancy))
    checks.add(
        "reflection evidence tracks event",
        any(item.evidence_type == "event" for item in resident.reflection_evidence),
        str([item.evidence_type for item in resident.reflection_evidence]),
    )


def run_conversation_phase(
    engine: TownWorldEngine,
    agent: NPCAgent,
    traced_model: TraceChatModel,
    checks: CheckBoard,
) -> None:
    print_header("阶段 3: relationship-aware conversation")
    engine.state.set_location("alice", "cafe")
    engine.state.set_location("bob", "cafe")
    traced_model.phase = "conversation:alice-bob"
    previous_agent = engine._active_step_agent
    engine._active_step_agent = agent
    try:
        result = engine.start_conversation("alice", "bob", "验证咖啡馆晨间交流和关系记忆")
    finally:
        engine._active_step_agent = previous_agent
    print("start_conversation result:")
    print(indent(json.dumps(result.model_dump(), ensure_ascii=False, indent=2, default=str)))
    session = engine.state.conversation_sessions.get(
        str(result.facts.get("conversation_session_id"))
    )
    if session is not None:
        print("conversation session snapshot:")
        print(indent(json.dumps(engine.build_replay_snapshot(["alice", "bob"])["conversation_sessions"], ensure_ascii=False, indent=2)))
        print("transcript:")
        for turn in session.turns:
            print(f"  {minute_label(turn.minute)} {turn.speaker_id}->{turn.listener_id}: {turn.text}")
    checks.add("conversation action succeeded", result.status == "succeeded", result.reason or "")
    checks.add("conversation session closed", session is not None and session.status == "closed")
    checks.add(
        "conversation wrote impression memory",
        bool(
            engine.memory_for("alice").grep(
                "",
                category="impression",
                metadata_filters={"source": "town_conversation", "partner_npc_id": "bob"},
            )
        ),
    )
    later_context = engine.build_context("alice", "验证 Bob 的关系线索与冷却。")
    cues = later_context.extra["town"]["relationship_cues"]
    print("relationship_cues:")
    print(indent(json.dumps(cues, ensure_ascii=False, indent=2, default=str)))
    checks.add("relationship cues render into context", bool(cues))


def run_reflection_phase(
    engine: TownWorldEngine,
    agent: NPCAgent,
    traced_model: TraceChatModel,
    checks: CheckBoard,
) -> None:
    print_header("阶段 4: reflection trigger + distilled memory")
    actor = "alice"
    due_before = engine.reflection_due_for(actor)
    print(f"reflection_due_before={due_before}")
    print("reflection evidence:")
    for item in engine.state.residents[actor].reflection_evidence:
        print(f"- {item.id} type={item.evidence_type} poignancy={item.poignancy} summary={item.summary}")
    traced_model.phase = f"reflection:{actor}"
    try:
        reflected = engine.reflect_for_resident(actor, agent)
    except Exception as exc:
        checks.add("reflection call completed", False, repr(exc))
        raise
    print(f"reflect_for_resident returned: {reflected}")
    checks.add("reflection was due before call", due_before)
    checks.add("reflection call produced event", reflected)
    reflections = engine.memory_for(actor).grep(
        "",
        category="reflection",
        metadata_filters={"source": "town_reflection"},
    )
    print("reflection memory:")
    for record in reflections:
        print(f"- {record.content}")
        print(indent(json.dumps(record.metadata, ensure_ascii=False, default=str)))
    checks.add("reflection memory written", bool(reflections))
    checks.add("reflection evidence cleared after success", not engine.state.residents[actor].reflection_evidence)


def run_multi_npc_phase(
    engine: TownWorldEngine,
    agent: NPCAgent,
    traced_model: TraceChatModel,
    npc_ids: list[str],
    replay_dir: Path,
    args: argparse.Namespace,
    checks: CheckBoard,
):
    print_header("阶段 5: multi-NPC runner + action arbitration + opt-in reflection")
    traced_model.phase = "multi-npc-runner"
    result = run_multi_npc_day(
        engine,
        agent,
        npc_ids,
        start_minute=args.start_minute,
        end_minute=args.end_minute,
        max_ticks=args.max_ticks,
        replay_dir=replay_dir,
        reflection_agent=agent,
    )
    for tick in result.ticks:
        print(
            f"tick={tick.tick} minute={tick.minute} time={minute_label(tick.minute)} "
            f"ran={tick.ran_npc_ids or ['none']} skipped={tick.skipped_npc_ids or ['none']} "
            f"actions={tick.action_count} reflections={tick.reflection_count}"
        )
    if result.note:
        print(f"runner note: {result.note}")
    checks.add("multi-NPC runner returned ok", result.ok or args.allow_incomplete, result.note)
    checks.add("runner produced ticks", bool(result.ticks), str(len(result.ticks)))
    checks.add("action log is populated", bool(engine.action_log), str(len(engine.action_log)))
    checks.add("replay paths were written", all(path.exists() for path in result.replay_paths.values()))
    return result


def run_replay_and_memory_phase(
    engine: TownWorldEngine,
    replay_paths: dict[str, Path],
    npc_ids: list[str],
    checks: CheckBoard,
) -> None:
    print_header("阶段 6: replay snapshot + artifacts + memory/history")
    checkpoints = read_jsonl(replay_paths["checkpoints"])
    actions = read_jsonl(replay_paths["actions"])
    reflections = read_jsonl(replay_paths["reflections"])
    print(f"checkpoint rows: {len(checkpoints)}")
    print(f"action rows: {len(actions)}")
    print(f"reflection rows: {len(reflections)}")
    if checkpoints:
        print("first checkpoint snapshot:")
        print(indent(json.dumps(checkpoints[0]["snapshot"], ensure_ascii=False, indent=2, default=str)))
        print("last checkpoint snapshot:")
        print(indent(json.dumps(checkpoints[-1]["snapshot"], ensure_ascii=False, indent=2, default=str)))
    checks.add("checkpoints include snapshot", bool(checkpoints) and "snapshot" in checkpoints[0])
    checks.add(
        "snapshot residents include requested NPCs",
        bool(checkpoints)
        and set(npc_ids).issubset(set(checkpoints[-1]["snapshot"]["residents"])),
    )
    checks.add(
        "snapshot includes conversation sessions",
        any(row["snapshot"]["conversation_sessions"] for row in checkpoints),
    )
    checks.add("town_reflections artifact exists", replay_paths["reflections"].exists())
    checks.add(
        "reflection artifact matches engine log length",
        len(reflections) == len(engine.reflection_log),
        f"file={len(reflections)} engine={len(engine.reflection_log)}",
    )
    timeline_text = replay_paths["timeline"].read_text(encoding="utf-8")
    print("timeline preview:")
    print(indent("\n".join(timeline_text.splitlines()[:20]) or "空"))
    checks.add("timeline artifact exists", replay_paths["timeline"].exists())
    for npc_id in npc_ids:
        history_entries = engine.history_for(npc_id).read_last(5)
        print(f"{npc_id} history last {len(history_entries)}:")
        for entry in history_entries:
            print(f"  [{entry.speaker}] {entry.content[:160]}")
        checks.add(f"{npc_id} memory interface reachable", engine.memory_for(npc_id) is not None)


def print_world(engine: TownWorldEngine, npc_ids: list[str]) -> None:
    print(f"clock={engine.state.clock.label()} minute={engine.state.clock.minute}")
    for location in engine.state.locations.values():
        print(
            f"- {location.id} {location.name}: occupants={location.occupant_ids or []} "
            f"exits={location.exits or []} objects={location.object_ids or []}"
        )
    print("resident locations:")
    for npc_id in npc_ids:
        resident = engine.state.resident_for(npc_id)
        if resident is None:
            print(f"- {npc_id}: missing")
            continue
        print(
            f"- {npc_id}: location={resident.location_id} poignancy={resident.poignancy} "
            f"evidence={len(resident.reflection_evidence)} action={resident.current_action}"
        )


def print_schedules(engine: TownWorldEngine, npc_ids: list[str]) -> None:
    print("[Schedules]")
    for npc_id in npc_ids:
        print(f"- {npc_id}")
        print_schedule(engine, npc_id, prefix="  ")


def print_schedule(engine: TownWorldEngine, npc_id: str, *, prefix: str = "") -> None:
    for segment in engine.state.schedule_for(npc_id):
        complete = engine.state.is_schedule_segment_complete(npc_id, segment)
        print(
            f"{prefix}{minute_label(segment.start_minute)}-{minute_label(segment.end_minute)} "
            f"location={segment.location_id} intent={segment.intent} complete={complete}"
        )


def print_schedule_completion(engine: TownWorldEngine, npc_ids: list[str]) -> None:
    print("[Schedule Completion]")
    for npc_id in npc_ids:
        completed = engine.state.completed_schedule_segments.get(npc_id, [])
        print(f"- {npc_id}: {len(completed)} completed")
        for item in completed:
            print(f"  {minute_label(item.start_minute)} location={item.location_id} note={item.note}")


def print_action_log(engine: TownWorldEngine) -> None:
    print_header("Action log")
    if not engine.action_log:
        print("没有产生小镇动作。")
        return
    for index, item in enumerate(engine.action_log, start=1):
        print(
            f"{index:03d} [{item.get('time')}] npc={item.get('npc_id')} "
            f"action={item.get('action_type')} status={item.get('status')} "
            f"location={item.get('location_id')}"
        )
        print(indent(str(item.get("summary", "")), prefix="    "))
        print(indent(json.dumps(item.get("facts", {}), ensure_ascii=False, default=str), prefix="    facts="))


def print_reflections(engine: TownWorldEngine) -> None:
    print_header("Reflection log")
    if not engine.reflection_log:
        print("没有 reflection event。")
        return
    for item in engine.reflection_log:
        print(json.dumps(item, ensure_ascii=False, indent=2, default=str))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def schedule_signature(schedule) -> list[tuple[int, int, str, str]]:
    return [
        (
            segment.start_minute,
            segment.duration_minutes,
            segment.location_id,
            segment.intent,
        )
        for segment in schedule
    ]


def default_run_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("data/town/full_change_validation_real_llm") / stamp


def print_header(title: str) -> None:
    print("\n" + "=" * 12 + f" {title} " + "=" * 12)


def indent(text: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


def squash(text: str) -> str:
    return " ".join(text.split())


def minute_label(minute: int) -> str:
    hours, minutes = divmod(minute, 60)
    return f"{hours:02d}:{minutes:02d}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run full real-LLM validation for evolve-townworld-generative-agents."
    )
    parser.add_argument("--model-config", default="config/model_config.yaml")
    parser.add_argument("--npcs", default="alice,bob,clara")
    parser.add_argument("--start-minute", type=int, default=8 * 60)
    parser.add_argument("--end-minute", type=int, default=10 * 60)
    parser.add_argument("--max-ticks", type=int, default=8)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--chat-iter", type=int, default=2)
    parser.add_argument("--max-events", type=int, default=3)
    parser.add_argument("--max-objects", type=int, default=3)
    parser.add_argument("--max-npcs", type=int, default=3)
    parser.add_argument("--max-exits", type=int, default=4)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--preview-chars", type=int, default=1600)
    parser.add_argument(
        "--verbose-messages",
        action="store_true",
        help="打印每次真实 LLM 调用的 prompt 预览，而不只是压缩摘要。",
    )
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="runner 到达 max_ticks 未完成时不视为失败。",
    )
    parser.add_argument(
        "--allow-failures",
        action="store_true",
        help="打印 FAIL 但脚本最后仍以 0 退出，适合调试不稳定模型行为。",
    )
    parser.add_argument(
        "--abort-on-phase-error",
        action="store_true",
        help="阶段内部异常时立即退出；默认记录 FAIL 后继续执行后续阶段。",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()

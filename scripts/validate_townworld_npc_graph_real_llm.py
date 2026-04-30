"""Validate TownWorldEngine against the graph-id NPC layer with a real LLM.

Usage:
    conda run -n annie python scripts/validate_townworld_npc_graph_real_llm.py

The script reads ``config/model_config.yaml`` and ``.env``. It runs a bounded
multi-NPC TownWorld scenario through the real ``NPCAgent`` and records every
requested/returned NPC cognitive graph id.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import chromadb
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from annie.npc import AgentGraphID, NPCAgent
from annie.npc.config import load_model_config
from annie.npc.context import AgentContext
from annie.npc.response import AgentResponse
from annie.town import (
    ReflectionEvidence,
    TownMultiNpcRunResult,
    TownWorldEngine,
    create_small_town_state,
    run_multi_npc_day,
)


@dataclass
class AgentRunRecord:
    npc_id: str
    input_event: str
    requested_graph_id: str
    response_graph_id: str
    route: str
    bound_tools: list[str]
    dialogue: str
    structured_output_preview: str
    reflection_preview: str


class TraceChatModel:
    """Real-model wrapper that prints concise LLM/tool-call traces."""

    def __init__(
        self,
        model: Any,
        *,
        state: dict[str, Any] | None = None,
        bound_tool_names: list[str] | None = None,
        verbose_messages: bool = False,
        preview_chars: int = 1200,
    ) -> None:
        self._model = model
        self._state = state if state is not None else {"calls": 0}
        self._bound_tool_names = bound_tool_names or []
        self._verbose_messages = verbose_messages
        self._preview_chars = preview_chars

    @property
    def call_count(self) -> int:
        return int(self._state["calls"])

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
        print_header(f"LLM call {call_no}")
        print(f"bound tools: {', '.join(self._bound_tool_names) or 'none'}")
        if messages:
            last = str(messages[-1].content)
            if self._verbose_messages:
                print("last message:")
                print(indent(last[: self._preview_chars]))
            else:
                print("last message preview:")
                print(indent(squash(last)[: self._preview_chars]))

        response = self._model.invoke(messages, **kwargs)
        if not isinstance(response, AIMessage):
            response = AIMessage(content=str(getattr(response, "content", response)))
        if response.tool_calls:
            print("tool calls:")
            print(indent(json.dumps(response.tool_calls, ensure_ascii=False, indent=2)))
        else:
            print("model response:")
            print(indent(str(response.content)[: self._preview_chars]))
        return response


class RecordingNPCAgent:
    """Wraps NPCAgent and records graph-id proof for each TownWorld call."""

    def __init__(self, agent: NPCAgent) -> None:
        self._agent = agent
        self.records: list[AgentRunRecord] = []

    def run(self, context: AgentContext) -> AgentResponse:
        response = self._agent.run(context)
        record = AgentRunRecord(
            npc_id=context.npc_id,
            input_event=context.input_event,
            requested_graph_id=str(context.graph_id or ""),
            response_graph_id=response.graph_id,
            route=str(response.route),
            bound_tools=[str(item) for item in response.debug.get("bound_tools", [])],
            dialogue=response.dialogue[:160],
            structured_output_preview=response.structured_output[:160],
            reflection_preview=response.reflection[:160],
        )
        self.records.append(record)
        print_header("NPC graph proof")
        print(f"npc={record.npc_id}")
        print(f"requested_graph_id={record.requested_graph_id or '<compat-default>'}")
        print(f"response_graph_id={record.response_graph_id}")
        print(f"route={record.route}")
        print(f"bound_tools={', '.join(record.bound_tools) or 'none'}")
        if record.dialogue:
            print(f"dialogue={record.dialogue}")
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
    print_header("model config")
    print(f"provider={config.model.provider}")
    print(f"model={config.model.model_name}")
    print(f"base_url={config.model.base_url}")
    print(f"api_key_env={config.model.api_key_env}")
    if not config.api_key:
        raise SystemExit(f"missing API key environment variable: {config.model.api_key_env}")

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
    agent = RecordingNPCAgent(NPCAgent(llm=traced_model, max_retries=args.max_retries))
    engine = TownWorldEngine(
        create_small_town_state(),
        chroma_client=chromadb.PersistentClient(path=str(vector_dir)),
        history_dir=history_dir,
    )
    engine.chat_iter = args.chat_iter

    npc_ids = [item.strip() for item in args.npcs.split(",") if item.strip()]
    if len(npc_ids) < 2:
        raise SystemExit("--npcs must include at least two NPC ids for dialogue validation")

    print_header("scenario")
    print(f"npcs={', '.join(npc_ids)}")
    print(f"time_window={minute_label(args.start_minute)}-{minute_label(args.end_minute)}")
    print(f"max_ticks={args.max_ticks}")
    print(f"run_dir={run_dir}")
    print_world(engine)

    if not args.skip_planning:
        run_planning_phase(engine, agent, npc_ids, args)

    result = run_action_phase(engine, agent, npc_ids, replay_dir, args)

    if not args.skip_conversation:
        run_forced_conversation_phase(engine, agent, npc_ids[0], npc_ids[1])

    if not args.skip_reflection:
        run_reflection_phase(engine, agent, npc_ids[0])

    print_header("final state")
    print_world(engine)
    print_action_log(engine)
    print_replay_paths(result)
    print_graph_summary(agent.records)
    validate_graph_coverage(agent.records, args)

    if traced_model.call_count <= 0:
        raise SystemExit("real LLM call count is 0; validation did not exercise the model")
    if not result.ok and not args.allow_incomplete:
        raise SystemExit(f"multi-NPC runner incomplete: {result.note}")


def run_planning_phase(
    engine: TownWorldEngine,
    agent: RecordingNPCAgent,
    npc_ids: list[str],
    args: argparse.Namespace,
) -> None:
    print_header("phase 1: resident planning via structured graph")
    for npc_id in npc_ids:
        before = len(agent.records)
        accepted = engine.generate_day_plan_for_resident(
            npc_id,
            agent,
            start_minute=args.start_minute,
            end_minute=args.end_minute,
        )
        record = agent.records[before]
        print(f"accepted schedule for {npc_id}:")
        for segment in accepted:
            print(
                f"  {minute_label(segment.start_minute)}-{minute_label(segment.end_minute)} "
                f"{segment.location_id}: {segment.intent}"
            )
        require_graph(
            record,
            AgentGraphID.OUTPUT_STRUCTURED_JSON,
            f"planning graph for {npc_id}",
            args.allow_graph_mismatch,
        )


def run_action_phase(
    engine: TownWorldEngine,
    agent: RecordingNPCAgent,
    npc_ids: list[str],
    replay_dir: Path,
    args: argparse.Namespace,
) -> TownMultiNpcRunResult:
    print_header("phase 2: bounded multi-NPC ticks via action graph")
    result = run_multi_npc_day(
        engine,
        agent,
        npc_ids,
        start_minute=args.start_minute,
        end_minute=args.end_minute,
        max_ticks=args.max_ticks,
        replay_dir=replay_dir,
    )
    for tick in result.ticks:
        print(
            f"tick={tick.tick} time={minute_label(tick.minute)} "
            f"ran={tick.ran_npc_ids or ['none']} skipped={tick.skipped_npc_ids or ['none']} "
            f"actions={tick.action_count} reflections={tick.reflection_count}"
        )
    return result


def run_forced_conversation_phase(
    engine: TownWorldEngine,
    agent: RecordingNPCAgent,
    speaker_id: str,
    listener_id: str,
) -> None:
    print_header("phase 3: forced managed dialogue via dialogue graph")
    previous_agent = getattr(engine, "_active_step_agent")
    setattr(engine, "_active_step_agent", agent)
    try:
        result = engine.start_conversation(
            speaker_id,
            listener_id,
            "请聊聊今天的小镇安排，并自然结束。",
        )
    finally:
        setattr(engine, "_active_step_agent", previous_agent)
    print(f"conversation status={result.status} reason={result.reason or ''}")


def run_reflection_phase(
    engine: TownWorldEngine,
    agent: RecordingNPCAgent,
    npc_id: str,
) -> None:
    print_header("phase 4: forced reflection via reflection graph")
    resident = engine.state.resident_for(npc_id)
    if resident is None:
        raise SystemExit(f"unknown resident: {npc_id}")
    resident.poignancy = max(resident.poignancy, engine.reflection_threshold)
    resident.reflection_evidence.append(
        ReflectionEvidence(
            id=f"{npc_id}_script_reflection_1",
            evidence_type="script_validation",
            summary="真实 LLM 多 NPC 验证脚本要求居民总结刚才的小镇行动和对话。",
            poignancy=engine.reflection_threshold,
            clock_minute=engine.state.clock.minute,
            metadata={"source": "validate_townworld_npc_graph_real_llm"},
        )
    )
    ok = engine.reflect_for_resident(npc_id, agent)
    print(f"reflection persisted={ok}")


def require_graph(
    record: AgentRunRecord,
    expected: AgentGraphID,
    label: str,
    allow_mismatch: bool,
) -> None:
    if record.requested_graph_id == expected and record.response_graph_id == expected:
        print(f"PASS {label}: {expected}")
        return
    message = (
        f"FAIL {label}: requested={record.requested_graph_id}, "
        f"response={record.response_graph_id}, expected={expected}"
    )
    if allow_mismatch:
        print(message)
        return
    raise SystemExit(message)


def validate_graph_coverage(records: list[AgentRunRecord], args: argparse.Namespace) -> None:
    expected = {
        str(AgentGraphID.ACTION_EXECUTOR_DEFAULT),
    }
    if not args.skip_planning:
        expected.add(str(AgentGraphID.OUTPUT_STRUCTURED_JSON))
    if not args.skip_conversation:
        expected.add(str(AgentGraphID.DIALOGUE_MEMORY_THEN_OUTPUT))
    if not args.skip_reflection:
        expected.add(str(AgentGraphID.REFLECTION_EVIDENCE_TO_MEMORY_CANDIDATE))

    seen_requested = {record.requested_graph_id for record in records if record.requested_graph_id}
    seen_response = {record.response_graph_id for record in records if record.response_graph_id}
    missing = sorted(expected - seen_requested - seen_response)
    if not missing:
        print("PASS graph coverage")
        return
    message = f"missing expected graph ids: {', '.join(missing)}"
    if args.allow_graph_mismatch:
        print(f"FAIL graph coverage: {message}")
        return
    raise SystemExit(message)


def print_graph_summary(records: list[AgentRunRecord]) -> None:
    print_header("graph summary")
    requested = Counter(record.requested_graph_id or "<compat-default>" for record in records)
    responded = Counter(record.response_graph_id or "<none>" for record in records)
    print("requested graph ids:")
    for graph_id, count in sorted(requested.items()):
        print(f"- {graph_id}: {count}")
    print("response graph ids:")
    for graph_id, count in sorted(responded.items()):
        print(f"- {graph_id}: {count}")
    print("runs:")
    for index, record in enumerate(records, start=1):
        print(
            f"{index:02d}. npc={record.npc_id} route={record.route} "
            f"requested={record.requested_graph_id or '<compat-default>'} "
            f"response={record.response_graph_id}"
        )


def print_world(engine: TownWorldEngine) -> None:
    print(f"time={engine.state.clock.label()}")
    for location in engine.state.locations.values():
        occupants = ", ".join(location.occupant_ids) if location.occupant_ids else "none"
        exits = ", ".join(location.exits) if location.exits else "none"
        print(f"- {location.id}: occupants={occupants}; exits={exits}")


def print_action_log(engine: TownWorldEngine) -> None:
    print_header("action log")
    if not engine.action_log:
        print("no actions")
        return
    for item in engine.action_log:
        print(
            f"{item['time']} npc={item['npc_id']} action={item['action_type']} "
            f"status={item['status']} location={item['location_id']}"
        )
        print(indent(str(item["summary"]), prefix="    "))


def print_replay_paths(result: TownMultiNpcRunResult) -> None:
    print_header("replay artifacts")
    if result.note:
        print(f"runner note: {result.note}")
    if not result.replay_paths:
        print("no replay files")
        return
    for name, path in result.replay_paths.items():
        print(f"- {name}: {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate TownWorldEngine real-LLM execution through NPC graph ids."
    )
    parser.add_argument("--model-config", default="config/model_config.yaml")
    parser.add_argument("--npcs", default="alice,bob,clara")
    parser.add_argument("--start-minute", type=int, default=8 * 60)
    parser.add_argument("--end-minute", type=int, default=9 * 60)
    parser.add_argument("--max-ticks", type=int, default=6)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--chat-iter", type=int, default=1)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--preview-chars", type=int, default=1200)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--skip-planning", action="store_true")
    parser.add_argument("--skip-conversation", action="store_true")
    parser.add_argument("--skip-reflection", action="store_true")
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--allow-graph-mismatch", action="store_true")
    parser.add_argument("--verbose-messages", action="store_true")
    return parser.parse_args()


def default_run_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("data/town/npc_graph_real_llm") / stamp


def print_header(title: str) -> None:
    print("\n" + "=" * 10 + f" {title} " + "=" * 10)


def indent(text: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


def minute_label(minute: int) -> str:
    hours, minutes = divmod(minute, 60)
    return f"{hours:02d}:{minutes:02d}"


def squash(text: str) -> str:
    return " ".join(text.split())


if __name__ == "__main__":
    main()

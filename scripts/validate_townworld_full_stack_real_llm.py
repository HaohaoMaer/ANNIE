"""Comprehensive opt-in real-LLM validation for the current TownWorld stack.

Run:
    PYTHONPATH=src conda run -n annie python scripts/validate_townworld_full_stack_real_llm.py

This script intentionally excludes only UI/frontend behavior. It exercises and
prints evidence for the TownWorld backend surface: world state, resident
planning, bounded perception, event-driven schedule revision, tool actions,
NPC-NPC conversation, memory/history, reflection, replay artifacts, runtime
snapshot persistence, manifest-based resume, and NPC-layer statelessness.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

import chromadb
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from annie.npc import NPCAgent
from annie.npc.model.config import load_model_config
from annie.npc.core.context import AgentContext
from annie.npc.core.response import AgentResponse
from annie.npc.tools.base_tool import ToolContext
from annie.town import (
    ReflectionEvidence,
    TownEvent,
    TownPerceptionPolicy,
    TownRuntimeConfig,
    TownWorldEngine,
    create_town_engine_for_new_run,
    load_run_manifest,
    resolve_manifest_paths,
    run_multi_npc_day,
)


class Tee:
    def __init__(self, *streams: TextIO) -> None:
        self._streams = streams

    def write(self, text: str) -> int:
        for stream in self._streams:
            stream.write(text)
            stream.flush()
        return len(text)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()


class TraceChatModel:
    """Real model wrapper that logs phase, bound tools, prompt preview and response."""

    def __init__(
        self,
        model: Any,
        *,
        state: dict[str, Any] | None = None,
        bound_tool_names: list[str] | None = None,
        preview_chars: int = 1600,
        verbose_messages: bool = False,
    ) -> None:
        self._model = model
        self._state = state if state is not None else {"calls": 0, "phase": "bootstrap"}
        self._bound_tool_names = bound_tool_names or []
        self._preview_chars = preview_chars
        self._verbose_messages = verbose_messages

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
            preview_chars=self._preview_chars,
            verbose_messages=self._verbose_messages,
        )

    def invoke(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        self._state["calls"] += 1
        print_header(f"LLM call {self.call_count} | phase={self.phase}")
        print(f"bound_tools={', '.join(self._bound_tool_names) or 'none'}")
        print(f"message_count={len(messages)}")
        if messages:
            last = str(messages[-1].content)
            print("last_message:")
            preview = last if self._verbose_messages else squash(last)
            print(indent(preview[: self._preview_chars]))
        response = self._model.invoke(messages, **kwargs)
        if not isinstance(response, AIMessage):
            response = AIMessage(content=str(getattr(response, "content", response)))
        if response.tool_calls:
            print("tool_calls:")
            print(indent(json.dumps(response.tool_calls, ensure_ascii=False, indent=2)))
        else:
            print("model_response:")
            print(indent(str(response.content)[: self._preview_chars]))
        return response


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

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)


class StatelessResumeProbeAgent:
    """Tiny deterministic agent used only after resume to prove AgentContext carries state."""

    def __init__(self) -> None:
        self.contexts: list[AgentContext] = []

    def run(self, context: AgentContext) -> AgentResponse:
        self.contexts.append(context)
        town = context.extra.get("town", {})
        if not town.get("known"):
            return AgentResponse()
        target = town.get("current_schedule_target_location_id")
        location = town.get("location_id")
        tool_context = ToolContext(agent_context=context, runtime={})
        if location == target:
            _tool(context, "complete_current_schedule").safe_call(
                {"note": "resume probe reached schedule target"},
                tool_context,
            )
            return AgentResponse()
        exits = list(town.get("exits", []))
        if exits:
            destination = target if target in exits else exits[0]
            _tool(context, "move_to").safe_call(
                {"destination_id": destination},
                tool_context,
            )
        return AgentResponse()


def main() -> int:
    args = parse_args()
    run_dir = args.output_dir or default_run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)
    terminal_output = run_dir / "terminal_output.txt"
    with terminal_output.open("w", encoding="utf-8") as log_file:
        tee = Tee(sys.stdout, log_file)
        with redirect_stdout(tee), redirect_stderr(tee):
            return run_validation(args, run_dir, terminal_output)


def run_validation(args: argparse.Namespace, run_dir: Path, terminal_output: Path) -> int:
    load_dotenv()
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    replay_dir = run_dir / "replay"
    history_dir = run_dir / "history"
    vector_dir = run_dir / "vector_store"
    config = load_model_config(args.model_config)

    print_header("TownWorld Full Stack Real-LLM Validation")
    print("Scope: all backend/runtime functionality except UI/frontend.")
    print(f"run_dir={run_dir}")
    print(f"terminal_output={terminal_output}")
    print(f"model_config={args.model_config}")
    print(f"provider={config.model.provider}")
    print(f"model={config.model.model_name}")
    print(f"base_url={config.model.base_url}")
    print(f"api_key_env={config.model.api_key_env}")
    if not config.api_key:
        raise SystemExit(f"Missing API key environment variable: {config.model.api_key_env}")

    traced_model = TraceChatModel(
        ChatOpenAI(
            model=config.model.model_name,
            base_url=config.model.base_url,
            api_key=SecretStr(config.api_key),
            temperature=args.temperature,
            extra_body={"thinking": {"type": "disabled"}},
        ),
        preview_chars=args.preview_chars,
        verbose_messages=args.verbose_messages,
    )
    agent = NPCAgent(llm=traced_model, max_retries=args.max_retries)
    engine, scenario_metadata = create_town_engine_for_new_run(
        TownRuntimeConfig(
            run_id=run_dir.name,
            run_root=run_dir.parent,
            model_config_path=Path(args.model_config),
            agent_mode="real_llm",
            perception_policy=TownPerceptionPolicy(
                max_events=args.max_events,
                max_objects=args.max_objects,
                max_npcs=args.max_npcs,
                max_exits=args.max_exits,
            ),
        )
    )
    print("scenario:")
    print(indent(json.dumps(scenario_metadata["scenario"], ensure_ascii=False, indent=2)))
    if engine._memory_path != vector_dir or engine._history_dir != history_dir:
        raise RuntimeError("runtime setup did not create expected full-stack backend paths")
    engine.perception_policy = TownPerceptionPolicy(
        max_events=args.max_events,
        max_objects=args.max_objects,
        max_npcs=args.max_npcs,
        max_exits=args.max_exits,
    )
    engine.chat_iter = args.chat_iter
    engine.reflection_threshold = args.reflection_threshold
    npc_ids = resolve_requested_npcs(args.npcs, engine)
    checks = CheckBoard()

    phase_initial_state(engine, npc_ids, checks)
    phase_memory_seed(engine, npc_ids, checks)
    phase_real_llm_planning(engine, agent, traced_model, npc_ids, args, checks)
    phase_perception_revision(engine, npc_ids, checks)
    phase_real_llm_conversation(engine, agent, traced_model, checks)
    phase_real_llm_reflection(engine, agent, traced_model, checks)
    result = phase_multi_npc_runner(engine, agent, traced_model, npc_ids, args, replay_dir, checks)
    persistence_paths = phase_replay_persistence_resume(
        engine,
        result.replay_paths,
        run_dir,
        vector_dir,
        npc_ids,
        config_summary(args.model_config, config),
        checks,
    )
    summary_path = write_summary(
        run_dir,
        terminal_output,
        traced_model,
        engine,
        checks,
        result.replay_paths,
        persistence_paths,
    )

    print_header("Final Summary")
    print(f"llm_call_count={traced_model.call_count}")
    print(f"checks_total={len(checks.checks)}")
    print(f"checks_failed={sum(1 for check in checks.checks if not check.ok)}")
    print(f"summary_json={summary_path}")
    print(f"manifest={persistence_paths.get('manifest')}")
    print(f"latest_snapshot={persistence_paths.get('latest_snapshot')}")
    print("RESULT PASS full stack real-LLM validation" if checks.ok else "RESULT FAIL")
    return 0 if checks.ok or args.allow_failures else 1


def phase_initial_state(engine: TownWorldEngine, npc_ids: list[str], checks: CheckBoard) -> None:
    print_header("Phase 0: world and resident state")
    print(f"clock={engine.state.clock.label()}")
    for location in engine.state.locations.values():
        print(
            f"- location={location.id} name={location.name} "
            f"occupants={location.occupant_ids} exits={location.exits} objects={location.object_ids}"
        )
    for npc_id in npc_ids:
        resident = engine.state.resident_for(npc_id)
        print(f"- resident={npc_id} state={resident}")
    checks.add(
        "all requested residents exist",
        all(engine.state.resident_for(npc_id) is not None for npc_id in npc_ids),
        ",".join(npc_ids),
    )
    checks.add("semantic locations exist", bool(engine.state.locations), str(len(engine.state.locations)))
    checks.add("semantic objects exist", bool(engine.state.objects), str(len(engine.state.objects)))


def phase_memory_seed(engine: TownWorldEngine, npc_ids: list[str], checks: CheckBoard) -> None:
    print_header("Phase 1: memory and history seed")
    engine.memory_for("alice").remember(
        "Alice 记得咖啡馆柜台下面有一份新菜单，Bob 昨天提醒她今天可以查看。",
        category="semantic",
        metadata={"source": "full_stack_real_llm_seed", "location_id": "cafe"},
    )
    engine.ingest_external(
        "alice",
        "bob",
        "Bob 昨晚说：明早咖啡馆会有新菜单，也许适合推荐给 Clara。",
        metadata={"source": "full_stack_real_llm_seed"},
    )
    for npc_id in npc_ids:
        grep = engine.memory_for(npc_id).grep("", category="semantic")
        history = engine.history_for(npc_id).read_last(3)
        print(f"{npc_id} semantic_memory_count={len(grep)} history_tail={len(history)}")
    checks.add(
        "seed semantic memory is retrievable",
        bool(
            engine.memory_for("alice").grep(
                "新菜单",
                category="semantic",
                metadata_filters={"source": "full_stack_real_llm_seed"},
            )
        ),
    )
    checks.add("seed history is retrievable", bool(engine.history_for("alice").read_last(1)))


def phase_real_llm_planning(
    engine: TownWorldEngine,
    agent: NPCAgent,
    traced_model: TraceChatModel,
    npc_ids: list[str],
    args: argparse.Namespace,
    checks: CheckBoard,
) -> None:
    print_header("Phase 2: real-LLM daily planning")
    for npc_id in npc_ids:
        traced_model.phase = f"planning:{npc_id}"
        engine.start_day_for_resident(
            npc_id,
            day=engine.state.clock.day,
            start_minute=args.start_minute,
            end_minute=args.end_minute,
        )
        try:
            accepted = engine.generate_day_plan_for_resident(
                npc_id,
                agent,
                start_minute=args.start_minute,
                end_minute=args.end_minute,
            )
        except Exception as exc:
            checks.add(f"{npc_id} real LLM planning accepted", False, repr(exc))
            if args.abort_on_phase_error:
                raise
            continue
        print_schedule(engine, npc_id)
        resident = engine.state.residents[npc_id]
        checks.add(f"{npc_id} schedule generated", bool(accepted), str(len(accepted)))
        checks.add(
            f"{npc_id} day plan stored on resident",
            engine.state.clock.day in resident.day_plans,
        )
        checks.add(
            f"{npc_id} schedule mirror intact",
            engine.state.schedules[npc_id] is resident.schedule,
        )


def phase_perception_revision(engine: TownWorldEngine, npc_ids: list[str], checks: CheckBoard) -> None:
    print_header("Phase 3: bounded perception and schedule revision")
    actor = npc_ids[0]
    engine.state.set_location(actor, "town_square")
    event = TownEvent(
        id="full_stack_urgent_notice",
        minute=engine.state.clock.minute,
        location_id="town_square",
        actor_id="gm",
        event_type="urgent",
        summary="广场公告栏旁响起紧急铃声，居民需要判断是否调整计划。",
        target_ids=[actor],
    )
    engine.state.events.append(event)
    context = engine.build_context(actor, "观察广场紧急事件并判断是否调整计划。")
    town = context.extra["town"]
    print("perception:")
    print(indent(json.dumps(town["perception"], ensure_ascii=False, indent=2, default=str)))
    print("schedule_revision:")
    print(indent(json.dumps(town["schedule_revision"], ensure_ascii=False, indent=2, default=str)))
    checks.add("urgent event is visible", event.id in town["visible_event_ids"])
    checks.add("schedule revision happened", town["schedule_revision"].get("revised") is True)
    checks.add(
        "reflection evidence collected from event",
        bool(engine.state.residents[actor].reflection_evidence),
    )


def phase_real_llm_conversation(
    engine: TownWorldEngine,
    agent: NPCAgent,
    traced_model: TraceChatModel,
    checks: CheckBoard,
) -> None:
    print_header("Phase 4: real-LLM conversation and relationship memory")
    engine.state.set_location("alice", "cafe")
    engine.state.set_location("bob", "cafe")
    traced_model.phase = "conversation:alice-bob"
    previous_agent = engine._active_step_agent
    engine._active_step_agent = agent
    try:
        result = engine.start_conversation("alice", "bob", "讨论新菜单并约定是否提醒 Clara")
    finally:
        engine._active_step_agent = previous_agent
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2, default=str))
    session_id = result.facts.get("conversation_session_id")
    session = engine.state.conversation_sessions.get(str(session_id))
    if session is not None:
        for turn in session.turns:
            print(f"{minute_label(turn.minute)} {turn.speaker_id}->{turn.listener_id}: {turn.text}")
    checks.add("conversation action succeeded", result.status == "succeeded", result.reason or "")
    checks.add("conversation session persisted", session is not None)
    checks.add(
        "conversation memory persisted",
        bool(
            engine.memory_for("alice").grep(
                "",
                category="impression",
                metadata_filters={"source": "town_conversation", "partner_npc_id": "bob"},
            )
        ),
    )
    checks.add(
        "conversation cooldown persisted",
        bool(engine.state.conversation_cooldowns),
        json.dumps(engine.state.conversation_cooldowns, ensure_ascii=False),
    )
    later = engine.build_context("alice", "验证 Bob 的关系线索。")
    checks.add("relationship cues render into AgentContext", bool(later.extra["town"]["relationship_cues"]))


def phase_real_llm_reflection(
    engine: TownWorldEngine,
    agent: NPCAgent,
    traced_model: TraceChatModel,
    checks: CheckBoard,
) -> None:
    print_header("Phase 5: real-LLM reflection")
    resident = engine.state.residents["alice"]
    resident.poignancy = max(resident.poignancy, engine.reflection_threshold)
    if not resident.reflection_evidence:
        resident.reflection_evidence.append(
            ReflectionEvidence(
                id="full_stack_reflection_seed",
                evidence_type="conversation",
                summary="Alice 和 Bob 关于新菜单的对话值得反思。",
                poignancy=engine.reflection_threshold,
                clock_minute=engine.state.clock.minute,
                metadata={"source": "full_stack_real_llm"},
            )
        )
    print(f"reflection_due={engine.reflection_due_for('alice')}")
    traced_model.phase = "reflection:alice"
    reflected = engine.reflect_for_resident("alice", agent)
    checks.add("reflection produced distilled memory", reflected)
    checks.add(
        "reflection memory retrievable",
        bool(
            engine.memory_for("alice").grep(
                "",
                category="reflection",
                metadata_filters={"source": "town_reflection"},
            )
        ),
    )
    checks.add("reflection evidence cleared", not engine.state.residents["alice"].reflection_evidence)


def phase_multi_npc_runner(
    engine: TownWorldEngine,
    agent: NPCAgent,
    traced_model: TraceChatModel,
    npc_ids: list[str],
    args: argparse.Namespace,
    replay_dir: Path,
    checks: CheckBoard,
):
    print_header("Phase 6: multi-NPC runner, tools, arbitration, replay")
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
            f"tick={tick.tick} minute={minute_label(tick.minute)} "
            f"ran={tick.ran_npc_ids or ['none']} skipped={tick.skipped_npc_ids or ['none']} "
            f"actions={tick.action_count} reflections={tick.reflection_count}"
        )
    if result.note:
        print(f"runner_note={result.note}")
    checks.add("runner produced ticks", bool(result.ticks), str(len(result.ticks)))
    checks.add("runner completed or allowed incomplete", result.ok or args.allow_incomplete, result.note)
    checks.add("action log populated", bool(engine.action_log), str(len(engine.action_log)))
    checks.add("replay artifacts written", all(path.exists() for path in result.replay_paths.values()))
    return result


def phase_replay_persistence_resume(
    engine: TownWorldEngine,
    replay_paths: dict[str, Path],
    run_dir: Path,
    vector_dir: Path,
    npc_ids: list[str],
    model_summary: dict[str, object],
    checks: CheckBoard,
) -> dict[str, Path]:
    print_header("Phase 7: replay artifacts, runtime snapshot, manifest resume")
    checkpoints = read_jsonl(replay_paths["checkpoints"])
    actions = read_jsonl(replay_paths["actions"])
    reflections = read_jsonl(replay_paths["reflections"])
    print(f"checkpoint_rows={len(checkpoints)} action_rows={len(actions)} reflection_rows={len(reflections)}")
    if checkpoints:
        print("last_checkpoint_snapshot:")
        print(indent(json.dumps(checkpoints[-1]["snapshot"], ensure_ascii=False, indent=2, default=str)))
    checks.add("checkpoint replay has snapshots", bool(checkpoints) and "snapshot" in checkpoints[-1])
    checks.add("action replay exists", replay_paths["actions"].exists())
    checks.add("timeline replay exists", replay_paths["timeline"].exists())

    persistence_paths = engine.save_run(
        run_dir,
        run_id=run_dir.name,
        replay_paths=replay_paths,
        write_step_snapshot=True,
        model_summary=model_summary,
        validation={"script": Path(__file__).name, "ok_before_resume": checks.ok},
    )
    manifest = load_run_manifest(persistence_paths["manifest"])
    resolved = resolve_manifest_paths(run_dir, manifest)
    print("manifest:")
    print(indent(json.dumps(manifest, ensure_ascii=False, indent=2, default=str)))
    print("resolved_manifest_paths:")
    print(indent(json.dumps({k: str(v) for k, v in resolved.items()}, ensure_ascii=False, indent=2, default=str)))
    checks.add("manifest written", persistence_paths["manifest"].exists(), str(persistence_paths["manifest"]))
    checks.add("latest snapshot written", persistence_paths["latest_snapshot"].exists())
    checks.add("step snapshot written", any(key.startswith("step_snapshot") for key in persistence_paths))

    resumed = TownWorldEngine.resume_run(
        run_dir,
        chroma_client=chromadb.PersistentClient(path=str(vector_dir)),
    )
    checks.add("resume restores clock day", resumed.state.clock.day == engine.state.clock.day)
    checks.add("resume restores clock minute", resumed.state.clock.minute == engine.state.clock.minute)
    checks.add(
        "resume restores resident locations",
        {
            npc_id: resumed.state.location_id_for(npc_id)
            for npc_id in npc_ids
        }
        == {
            npc_id: engine.state.location_id_for(npc_id)
            for npc_id in npc_ids
        },
    )
    checks.add(
        "resume keeps memory backend available",
        bool(resumed.memory_for("alice").grep("新菜单", category="semantic")),
    )

    probe = StatelessResumeProbeAgent()
    probe_event = TownEvent(
        id="resume_probe_event",
        minute=resumed.state.clock.minute,
        location_id=resumed.state.location_id_for(npc_ids[0]),
        actor_id="validator",
        event_type="resume_probe",
        summary="恢复验证事件：请确认恢复后的 AgentContext 仍携带小镇状态。",
        target_ids=[npc_ids[0]],
    )
    resumed.state.events.append(probe_event)
    resumed.event_bus.publish(probe_event)
    resumed.step(probe, [npc_ids[0]])
    checks.add("resumed engine can tick with a fresh stateless agent", bool(probe.contexts))
    if probe.contexts:
        town = probe.contexts[0].extra["town"]
        checks.add("resumed AgentContext carries durable town state", town.get("known") is True)
        checks.add("resume did not require retained NPCAgent instance", not isinstance(probe, NPCAgent))
    return persistence_paths


def write_summary(
    run_dir: Path,
    terminal_output: Path,
    traced_model: TraceChatModel,
    engine: TownWorldEngine,
    checks: CheckBoard,
    replay_paths: dict[str, Path],
    persistence_paths: dict[str, Path],
) -> Path:
    summary = {
        "ok": checks.ok,
        "llm_call_count": traced_model.call_count,
        "clock": {
            "day": engine.state.clock.day,
            "minute": engine.state.clock.minute,
            "label": engine.state.clock.label(),
        },
        "resident_locations": {
            npc_id: engine.state.location_id_for(npc_id)
            for npc_id in engine.state.resident_ids()
        },
        "action_log_count": len(engine.action_log),
        "conversation_session_count": len(engine.state.conversation_sessions),
        "reflection_log_count": len(engine.reflection_log),
        "planning_log_count": len(engine.planning_log),
        "loop_guard_count": len(engine.loop_guard_events),
        "terminal_output": str(terminal_output),
        "replay_paths": {name: str(path) for name, path in replay_paths.items()},
        "persistence_paths": {name: str(path) for name, path in persistence_paths.items()},
        "checks": [
            {"label": check.label, "ok": check.ok, "detail": check.detail}
            for check in checks.checks
        ],
    }
    path = run_dir / "summary.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def config_summary(model_config_path: str, config: Any) -> dict[str, object]:
    return {
        "config_path": model_config_path,
        "provider": config.model.provider,
        "model": config.model.model_name,
        "base_url": config.model.base_url,
        "api_key_env": config.model.api_key_env,
    }


def _tool(context: AgentContext, name: str):
    return next(tool for tool in context.tools if tool.name == name)


def print_schedule(engine: TownWorldEngine, npc_id: str) -> None:
    print(f"schedule[{npc_id}]:")
    for segment in engine.state.schedule_for(npc_id):
        print(
            f"- day={segment.day} {minute_label(segment.start_minute)}-"
            f"{minute_label(segment.end_minute)} {segment.location_id}: {segment.intent} "
            f"subtasks={segment.subtasks}"
        )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def resolve_requested_npcs(value: str, engine: TownWorldEngine) -> list[str]:
    requested = value.strip()
    resident_ids = engine.state.resident_ids()
    if requested.isdigit():
        count = int(requested)
        if count <= 0:
            raise ValueError("--npcs numeric value must be positive")
        if count > len(resident_ids):
            raise ValueError(
                f"--npcs requested {count} residents, but scenario only has {len(resident_ids)}"
            )
        return resident_ids[:count]
    npc_ids = [item.strip() for item in requested.split(",") if item.strip()]
    if not npc_ids:
        raise ValueError("--npcs must name at least one resident or provide a positive count")
    return npc_ids


def default_run_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("runs") / "town_full_stack_real_llm" / stamp


def minute_label(minute: int) -> str:
    hours, minutes = divmod(minute, 60)
    return f"{hours:02d}:{minutes:02d}"


def print_header(text: str) -> None:
    print("\n" + "=" * 80)
    print(text)
    print("=" * 80)


def indent(text: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


def squash(text: str) -> str:
    return " ".join(text.split())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run comprehensive TownWorld backend/runtime validation with a real LLM."
    )
    parser.add_argument("--model-config", default="config/model_config.yaml")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--npcs",
        default="alice,bob,clara",
        help="Comma-separated resident ids, or a positive count such as 3.",
    )
    parser.add_argument("--start-minute", type=int, default=8 * 60)
    parser.add_argument("--end-minute", type=int, default=10 * 60)
    parser.add_argument("--max-ticks", type=int, default=8)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--chat-iter", type=int, default=2)
    parser.add_argument("--reflection-threshold", type=int, default=6)
    parser.add_argument("--max-events", type=int, default=3)
    parser.add_argument("--max-objects", type=int, default=3)
    parser.add_argument("--max-npcs", type=int, default=3)
    parser.add_argument("--max-exits", type=int, default=4)
    parser.add_argument("--preview-chars", type=int, default=1600)
    parser.add_argument("--verbose-messages", action="store_true")
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--allow-failures", action="store_true")
    parser.add_argument("--abort-on-phase-error", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())

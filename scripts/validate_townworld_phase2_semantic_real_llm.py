"""Real-LLM validation for Phase 2 TownWorld semantic affordances.

Run:
    python scripts/validate_townworld_phase2_semantic_real_llm.py

The script reads ``.env`` and ``config/model_config.yaml``. It writes the full
terminal trace and summary to:

    runs/town_phase2_semantic_real_llm/<timestamp>/
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
from annie.npc.config import load_model_config
from annie.npc.tools.base_tool import ToolContext
from annie.town import TownWorldEngine, create_small_town_state


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
    def __init__(
        self,
        model: Any,
        *,
        state: dict[str, Any] | None = None,
        bound_tool_names: list[str] | None = None,
        preview_chars: int = 1800,
    ) -> None:
        self._model = model
        self._state = state if state is not None else {"calls": 0}
        self._bound_tool_names = bound_tool_names or []
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
            preview_chars=self._preview_chars,
        )

    def invoke(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        self._state["calls"] += 1
        print_header(f"LLM call {self.call_count}")
        print(f"bound_tools={', '.join(self._bound_tool_names) or 'none'}")
        if messages:
            print("last_message:")
            print(indent(squash(str(messages[-1].content))[: self._preview_chars]))
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
class CheckBoard:
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    def add(self, label: str, ok: bool, detail: str = "") -> None:
        self.checks.append((label, ok, detail))
        print(f"{'PASS' if ok else 'FAIL'} {label}" + (f" | {detail}" if detail else ""))

    @property
    def ok(self) -> bool:
        return all(ok for _, ok, _ in self.checks)


def main() -> int:
    args = parse_args()
    run_dir = args.output_dir or default_run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)
    terminal_output = run_dir / "terminal_output.txt"
    with terminal_output.open("w", encoding="utf-8") as log_file:
        tee = Tee(sys.stdout, log_file)
        with redirect_stdout(tee), redirect_stderr(tee):
            code = run_validation(args, run_dir, terminal_output)
    return code


def run_validation(args: argparse.Namespace, run_dir: Path, terminal_output: Path) -> int:
    load_dotenv()
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    config = load_model_config(args.model_config)
    print_header("Phase 2 Real-LLM Semantic Town Validation")
    print(f"run_dir={run_dir}")
    print(f"terminal_output={terminal_output}")
    print(f"model={config.model.provider}/{config.model.model_name}")
    print(f"base_url={config.model.base_url}")
    print(f"api_key_env={config.model.api_key_env}")
    if not config.api_key:
        raise SystemExit(f"Missing API key environment variable: {config.model.api_key_env}")

    llm = TraceChatModel(
        ChatOpenAI(
            model=config.model.model_name,
            base_url=config.model.base_url,
            api_key=SecretStr(config.api_key),
            temperature=args.temperature,
            extra_body={"thinking": {"type": "disabled"}},
        ),
        preview_chars=args.preview_chars,
    )
    agent = NPCAgent(llm=llm, max_retries=args.max_retries)
    engine = TownWorldEngine(
        create_small_town_state(),
        chroma_client=chromadb.PersistentClient(path=str(run_dir / "vector_store")),
        history_dir=run_dir / "history",
    )
    checks = CheckBoard()

    engine.state.set_location(args.npc_id, "town_square")
    engine.plan_day_for_resident(
        args.npc_id,
        [_notice_board_segment(args.npc_id)],
    )
    context = engine.build_context(
        args.npc_id,
        (
            "请测试 Phase 2 语义工具：先根据上下文确认公告栏 notice_board 的可用 "
            "affordance，然后用 use_affordance 在 notice_board 上执行 post_notice，"
            "note 写成“市场九点有新鲜蔬果”。不要移动到其他地点。"
        ),
    )
    checks.add("context renders object affordances", "post_notice" in context.situation)
    checks.add("context has no tile map fields", "tile" not in str(context.extra["town"]).lower())

    print_header("Real LLM semantic action")
    response = agent.run(context)
    engine.handle_response(args.npc_id, response)
    semantic_actions = [
        item
        for item in engine.action_log
        if item.get("action_type") in {"use_affordance", "interact_with"}
    ]
    checks.add("real LLM was called", llm.call_count > 0, str(llm.call_count))
    checks.add("real LLM executed semantic object action", bool(semantic_actions))
    checks.add(
        "semantic action stayed local",
        engine.state.location_id_for(args.npc_id) == "town_square",
        str(engine.state.location_id_for(args.npc_id)),
    )

    print_header("Deterministic rejection checks")
    tool_context = ToolContext(agent_context=context, runtime={})
    use_tool = next(tool for tool in context.tools if tool.name == "use_affordance")
    before_events = len(engine.state.events)
    unsupported = use_tool.safe_call(
        {"target_id": "notice_board", "affordance_id": "brew_coffee"},
        tool_context,
    )
    unknown = use_tool.safe_call(
        {"target_id": "missing_kiosk", "affordance_id": "read_notices"},
        tool_context,
    )
    checks.add(
        "unsupported affordance rejected",
        unsupported["result"]["status"] == "failed"
        and unsupported["result"]["reason"] == "unsupported_affordance",
    )
    checks.add(
        "unknown target rejected",
        unknown["result"]["status"] == "failed"
        and unknown["result"]["reason"] == "target_not_visible",
    )
    checks.add("failed affordances did not mutate events", len(engine.state.events) == before_events)

    replay_paths = engine.write_replay_artifacts(run_dir / "replay")
    print_header("Replay Paths")
    for name, path in replay_paths.items():
        print(f"{name}: {path}")

    summary = {
        "ok": checks.ok,
        "llm_call_count": llm.call_count,
        "action_log_count": len(engine.action_log),
        "semantic_action_count": len(semantic_actions),
        "replay_paths": {name: str(path) for name, path in replay_paths.items()},
        "terminal_output": str(terminal_output),
        "checks": [
            {"label": label, "ok": ok, "detail": detail}
            for label, ok, detail in checks.checks
        ],
    }
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print_header("Summary")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"summary_json={summary_path}")
    print("RESULT PASS phase2 semantic real-LLM validation" if checks.ok else "RESULT FAIL")
    return 0 if checks.ok else 1


def _notice_board_segment(npc_id: str):
    from annie.town import ScheduleSegment

    return ScheduleSegment(
        npc_id=npc_id,
        start_minute=8 * 60,
        duration_minutes=30,
        location_id="town_square",
        intent="查看并张贴公告",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Phase 2 semantic affordance validation with a real LLM."
    )
    parser.add_argument("--model-config", default="config/model_config.yaml")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--npc-id", default="alice")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--preview-chars", type=int, default=1800)
    return parser.parse_args()


def default_run_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("runs") / "town_phase2_semantic_real_llm" / stamp


def print_header(text: str) -> None:
    print("\n" + "=" * 80)
    print(text)
    print("=" * 80)


def indent(text: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


def squash(text: str) -> str:
    return " ".join(text.split())


if __name__ == "__main__":
    raise SystemExit(main())

"""Trace the action loop with the configured real LLM.

Usage:
    conda run -n annie python scripts/trace_action_loop_real_llm.py

The script reads ``.env`` and ``config/model_config.yaml`` through the
project's normal model factory. It intentionally uses a tiny deterministic
world:

    study -> hallway -> kitchen

The expected behavior is that the Executor keeps using ``world_action`` until
the move result says the NPC reached ``kitchen``. If the model stops at
``hallway`` or gives up too early, the trace will make that visible.
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any

import chromadb
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from annie.npc import NPCAgent
from annie.npc.config import load_model_config
from annie.npc.response import ActionRequest, ActionResult, AgentResponse
from annie.world_engine import DefaultWorldEngine
from annie.world_engine.profile import NPCProfile
from langchain_openai import ChatOpenAI
from pydantic import SecretStr


class TraceChatModel:
    """Thin duck-typed wrapper that traces invoke/bind_tools calls."""

    def __init__(
        self,
        model: Any,
        *,
        state: dict[str, Any] | None = None,
        bound_tool_names: list[str] | None = None,
    ) -> None:
        self._model = model
        self._state = state if state is not None else {"calls": 0}
        self._bound_tool_names = bound_tool_names or []

    def bind_tools(self, tools: list[dict]) -> "TraceChatModel":
        bound = self._model.bind_tools(tools)
        bound_tool_names = [
            t.get("function", {}).get("name", "<unknown>") for t in tools
        ]
        return TraceChatModel(
            bound,
            state=self._state,
            bound_tool_names=bound_tool_names,
        )

    def invoke(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        self._state["calls"] += 1
        call_no = self._state["calls"]
        node = infer_node(messages[-1])

        print_header(f"LLM call {call_no} · {node}")
        print(f"bound tools: {', '.join(self._bound_tool_names) or '(none)'}")
        print(f"last input message type: {type(messages[-1]).__name__}")
        print("last input message content:")
        print(indent(str(messages[-1].content)))

        response = self._model.invoke(messages, **kwargs)
        if not isinstance(response, AIMessage):
            response = AIMessage(content=str(getattr(response, "content", response)))

        print("real response:")
        if response.tool_calls:
            print(indent(json.dumps(response.tool_calls, ensure_ascii=False, indent=2)))
        else:
            print(indent(str(response.content)))
        return response


class TraceWorldEngine(DefaultWorldEngine):
    def build_context(self, npc_id: str, event: str):
        print_header("WorldEngine.build_context")
        print(f"npc_id: {npc_id}")
        print("event:")
        print(indent(event))
        return super().build_context(npc_id, event)

    def execute_action(self, npc_id: str, action: ActionRequest) -> ActionResult:
        print_header("WorldEngine.execute_action")
        print("action request:")
        print(indent(json.dumps(action.model_dump(), ensure_ascii=False, indent=2)))
        result = super().execute_action(npc_id, action)
        print("action result:")
        print(indent(json.dumps(result.model_dump(), ensure_ascii=False, indent=2)))
        return result

    def handle_response(self, npc_id: str, response: AgentResponse) -> None:
        print_header("WorldEngine.handle_response")
        print(f"npc_id: {npc_id}")
        print(f"dialogue: {response.dialogue}")
        print(f"actions: {len(response.actions)}")
        print(f"memory_updates: {len(response.memory_updates)}")
        super().handle_response(npc_id, response)


def print_header(title: str) -> None:
    print("\n" + "=" * 10 + f" {title} " + "=" * 10)


def indent(text: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


def infer_node(message: BaseMessage) -> str:
    content = str(message.content)
    if isinstance(message, ToolMessage):
        return "executor ReAct observation"
    if "请根据以下上下文判断是否需要多步骤计划" in content:
        return "planner"
    if "请基于当前事件继续扮演角色" in content:
        return "executor"
    if "请只根据以下上下文复盘本轮执行结果" in content:
        return "reflector"
    return "executor"


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.ERROR)

    config = load_model_config("config/model_config.yaml")
    print(f"model: provider={config.model.provider}, name={config.model.model_name}")
    if not config.api_key:
        raise SystemExit(f"Missing API key env var: {config.model.api_key_env}")

    real_model = ChatOpenAI(
        model=config.model.model_name,
        base_url=config.model.base_url,
        api_key=SecretStr(config.api_key),
        temperature=config.model.temperature,
        # DeepSeek v4 thinking mode currently requires provider-specific
        # reasoning_content handling across tool-call turns. This trace is
        # testing the ReAct/tool loop, so disable thinking for compatibility.
        extra_body={"thinking": {"type": "disabled"}},
    )
    llm = TraceChatModel(real_model)

    tmp = Path(tempfile.mkdtemp(prefix="annie_action_trace_real_"))
    print(f"scratch dir: {tmp}")

    engine = TraceWorldEngine(
        chroma_client=chromadb.PersistentClient(path=str(tmp / "vs")),
        history_dir=tmp / "hist",
        world_rules=(
            "Locations are connected by explicit exits only. "
            "For this test, the current objective is complete only after the "
            "world_action move result has status=succeeded and facts.to='kitchen'. "
            "Do not produce a final answer at hallway; continue with world_action "
            "if kitchen is listed as reachable."
        ),
    )
    engine.register_profile("alice", NPCProfile(name="Alice"))
    engine.set_location("alice", "study")
    engine.set_exits("study", ["hallway"])
    engine.set_exits("hallway", ["study", "kitchen"])

    agent = NPCAgent(llm=llm)

    print_header("Initial world state")
    print("alice.location = study")
    print("exits.study = [hallway]")
    print("exits.hallway = [study, kitchen]")
    print("goal = move to kitchen")

    ctx = engine.build_context(
        "alice",
        (
            "目标：从 study 移动到 kitchen。必须使用 world_action 执行移动。"
            "如果 move 到 kitchen 返回 unreachable，请根据 facts.reachable 选择下一步。"
            "只有当 ActionResult 显示 status=succeeded 且 facts.to 为 kitchen 后，"
            "才可以输出最终回复。"
        ),
    )
    response = agent.run(ctx)
    engine.handle_response("alice", response)

    print_header("Final AgentResponse")
    print(indent(response.model_dump_json(indent=2)))
    print(f"\nscratch dir preserved at: {tmp}")


if __name__ == "__main__":
    main()

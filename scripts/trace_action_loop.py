"""Trace the NPC Executor -> WorldEngine ActionResult loop.

Usage:
    conda run -n annie python scripts/trace_action_loop.py

This script uses a deterministic stub LLM, so it does not call any external
model API. It prints each important handoff:

1. WorldEngine builds AgentContext once.
2. NPCAgent Planner decides this can skip high-level planning.
3. Executor calls the injected ``world_action`` tool.
4. WorldEngine executes the action and returns ActionResult as ToolMessage observation.
5. Executor reacts to that observation inside the same ReAct loop.
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any

import chromadb
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from annie.npc import NPCAgent
from annie.npc.response import ActionRequest, ActionResult, AgentResponse
from annie.world_engine import DefaultWorldEngine
from annie.world_engine.profile import NPCProfile


class TraceLLM:
    """Deterministic chat model stub that prints every model invocation."""

    def __init__(
        self,
        responses: list[Any],
        *,
        state: dict[str, Any] | None = None,
        bound_tool_names: list[str] | None = None,
    ) -> None:
        self._responses = responses
        self._state = state if state is not None else {"calls": 0}
        self._bound_tool_names = bound_tool_names or []

    def bind_tools(self, tools: list[dict]) -> "TraceLLM":
        bound_tool_names = [
            t.get("function", {}).get("name", "<unknown>") for t in tools
        ]
        return TraceLLM(
            self._responses,
            state=self._state,
            bound_tool_names=bound_tool_names,
        )

    def invoke(self, messages: list[BaseMessage], **_: Any) -> AIMessage:
        self._state["calls"] += 1
        call_no = self._state["calls"]
        node = infer_node(messages[-1])
        print_header(f"LLM call {call_no} · {node}")
        print(f"bound tools: {', '.join(self._bound_tool_names) or '(none)'}")
        print(f"last input message type: {type(messages[-1]).__name__}")
        print("last input message content:")
        print(indent(str(messages[-1].content)))

        if not self._responses:
            response = AIMessage(content="")
        else:
            nxt = self._responses.pop(0)
            response = nxt if isinstance(nxt, AIMessage) else AIMessage(content=str(nxt))

        print("stub response:")
        if response.tool_calls:
            print(indent(json.dumps(response.tool_calls, ensure_ascii=False, indent=2)))
        else:
            print(indent(str(response.content)))
        return response


class TraceWorldEngine(DefaultWorldEngine):
    """DefaultWorldEngine with trace prints around the new action API."""

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


def tool_call(name: str, args: dict[str, Any], call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.ERROR)

    tmp = Path(tempfile.mkdtemp(prefix="annie_action_trace_"))
    print(f"scratch dir: {tmp}")

    llm = TraceLLM([
        '{"decision":"skip","reason":"需要先尝试移动","tasks":[]}',
        tool_call("world_action", {"type": "move", "payload": {"to": "kitchen"}}, "move_1"),
        tool_call("world_action", {"type": "move", "payload": {"to": "hallway"}}, "move_2"),
        tool_call("world_action", {"type": "move", "payload": {"to": "kitchen"}}, "move_3"),
        "我已经到厨房了。书房不能直达厨房，所以我先到走廊，再从走廊进入厨房。",
        '{"reflection":"Alice learned that kitchen is not directly reachable from study, then reached kitchen via hallway.","facts":[],"relationship_notes":[]}',
    ])

    engine = TraceWorldEngine(
        chroma_client=chromadb.PersistentClient(path=str(tmp / "vs")),
        history_dir=tmp / "hist",
        world_rules="Locations are connected by explicit exits only.",
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
        "目标：去 kitchen。请通过 world_action 请求世界动作，并根据结果继续。",
    )
    response = agent.run(ctx)
    engine.handle_response("alice", response)

    print_header("Final AgentResponse")
    print(indent(response.model_dump_json(indent=2)))
    print(f"\nscratch dir preserved at: {tmp}")


if __name__ == "__main__":
    main()

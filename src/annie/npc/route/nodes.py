"""Global registry of business-agnostic NPC route nodes."""

from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any, cast

from langchain_core.messages import AIMessage, ToolMessage

from annie.npc.core.context import AgentContext
from annie.npc.cognition.context_budget import ContextBudget
from annie.npc.cognition.executor import SKIP_TASK_MARKER, _tool_to_schema
from annie.npc.cognition.prompts import (
    build_direct_dialogue_messages,
    build_direct_json_messages,
    build_direct_reflection_messages,
)
from annie.npc.route.route_model import NodeID, RouteRuntime
from annie.npc.runtime import MemoryContextBuilder
from annie.npc.core.state import AgentState, Task

RouteNode = Callable[[AgentState, RouteRuntime], dict[str, Any]]

_DIALOGUE_MAX_TOOL_LOOPS = 2


class UnknownRouteNodeError(ValueError):
    """Raised when a route references an unregistered node id."""


_NODE_REGISTRY: dict[NodeID, RouteNode] = {}


def register_node(node_id: NodeID, node: RouteNode) -> None:
    _NODE_REGISTRY[node_id] = node


def get_node(node_id: NodeID) -> RouteNode:
    try:
        return _NODE_REGISTRY[node_id]
    except KeyError as exc:
        raise UnknownRouteNodeError(f"Unknown NPC route node: {node_id}") from exc


def list_node_ids() -> list[str]:
    return [str(node_id) for node_id in _NODE_REGISTRY]


def build_action_route_state(
    context: AgentContext,
    *,
    tracer: Any,
    runtime: dict[str, Any],
    max_retries: int,
    model_ctx_limit: int,
) -> AgentState:
    return {
        "agent_context": context,
        "input_event": context.input_event,
        "tasks": [],
        "current_task": None,
        "execution_results": [],
        "reflection": "",
        "working_memory": "",
        "tracer": tracer,
        "retry_count": 0,
        "max_retries": max_retries,
        "loop_reason": "",
        "last_tasks": [],
        "react_steps": [],
        "messages": [],
        "context_budget": ContextBudget(model_ctx_limit=model_ctx_limit),
        "runtime": runtime,
        "todo_list_text": context.todo,
        "active_skills": [],
        "memory_updates": [],
        "debug_route_nodes": [],
        "dialogue_output": "",
        "structured_output": "",
        "bound_tools": [],
    }


def build_direct_route_state(
    context: AgentContext,
    *,
    runtime: dict[str, Any] | None = None,
) -> AgentState:
    return {
        "agent_context": context,
        "input_event": context.input_event,
        "runtime": runtime or {},
        "debug_route_nodes": [],
        "dialogue_output": "",
        "structured_output": "",
        "reflection": "",
        "bound_tools": [],
    }


def prepare_action_node(state: AgentState, _runtime: RouteRuntime) -> dict[str, Any]:
    task = skip_task()
    return {"tasks": [task], "last_tasks": [task]}


def memory_context_node(state: AgentState, _runtime: RouteRuntime) -> dict[str, Any]:
    context = cast(AgentContext, state.get("agent_context"))
    runtime = state.get("runtime", {})
    seen_ids: set[str] = runtime.setdefault("recall_seen_ids", set())
    memory_context = MemoryContextBuilder(context.memory)
    return {
        "working_memory": memory_context.build_context(context.input_event, seen_ids=seen_ids)
    }


def planning_node(state: AgentState, runtime: RouteRuntime) -> dict[str, Any]:
    out = dict(runtime.planner(state))
    out["last_tasks"] = list(out.get("tasks", []))
    return out


def action_execution_node(state: AgentState, runtime: RouteRuntime) -> dict[str, Any]:
    if not state.get("tasks"):
        task = skip_task()
        state["tasks"] = [task]
        state["last_tasks"] = [task]
    else:
        state["last_tasks"] = list(state.get("tasks", []))
    return dict(runtime.executor(state))


def dialogue_generation_node(state: AgentState, runtime: RouteRuntime) -> dict[str, Any]:
    context = cast(AgentContext, state.get("agent_context"))
    messages = build_direct_dialogue_messages(context)
    tool_registry = runtime.tool_registry
    dispatcher = runtime.dispatcher
    bound_tool_names: list[str] = []
    last_response: AIMessage | None = None

    for step in range(_DIALOGUE_MAX_TOOL_LOOPS + 1):
        tool_defs = [tool_registry.get(n) for n in tool_registry.list_tools()]
        tool_defs = [t for t in tool_defs if t is not None]
        bound_tool_names = [t.name for t in tool_defs]
        tool_schemas = [_tool_to_schema(t) for t in tool_defs]
        try:
            bound_llm = runtime.llm.bind_tools(tool_schemas) if tool_schemas else runtime.llm
        except (NotImplementedError, AttributeError):
            bound_llm = runtime.llm
        response = bound_llm.invoke(messages)
        if not isinstance(response, AIMessage):
            response = AIMessage(content=str(getattr(response, "content", response) or ""))
        messages.append(response)
        last_response = response
        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls or step >= _DIALOGUE_MAX_TOOL_LOOPS:
            break
        for call in tool_calls:
            call_id = call.get("id") or f"dialogue_call_{step}_{call.get('name', '')}"
            dispatch = dispatcher.dispatch_result(call, context)
            messages.append(ToolMessage(content=dispatch.content, tool_call_id=call_id))

    raw = str(getattr(last_response, "content", "") or "").strip()
    return {
        "dialogue_output": _extract_direct_dialogue_text(raw),
        "bound_tools": bound_tool_names,
    }


def structured_json_generation_node(state: AgentState, runtime: RouteRuntime) -> dict[str, Any]:
    context = cast(AgentContext, state.get("agent_context"))
    response = runtime.llm.invoke(build_direct_json_messages(context))
    raw = str(getattr(response, "content", response) or "").strip()
    return {"structured_output": raw}


def reflection_generation_node(state: AgentState, runtime: RouteRuntime) -> dict[str, Any]:
    context = cast(AgentContext, state.get("agent_context"))
    response = runtime.llm.invoke(build_direct_reflection_messages(context))
    raw = str(getattr(response, "content", response) or "").strip()
    return {"reflection": _sanitize_reflection_text(_extract_direct_reflection_text(raw))}


def skip_task() -> Task:
    return Task(description=SKIP_TASK_MARKER, priority=5)


def _extract_direct_reflection_text(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(parsed, dict):
            for key in ("reflection", "content", "text"):
                value = parsed.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return text


def _extract_direct_dialogue_text(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    if text.startswith("```"):
        text = text.strip("`").strip()
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(parsed, dict):
            for key in ("dialogue", "text", "utterance", "content"):
                value = parsed.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return text


_REFLECTION_FORBIDDEN_TERMS = (
    "start_conversation",
    "conversation_session",
    "input_event",
    "tool",
    "route",
    "planner",
    "executor",
    "reflector",
    "JSON",
    "json",
)


def _sanitize_reflection_text(text: str) -> str:
    if any(term in text for term in _REFLECTION_FORBIDDEN_TERMS):
        return ""
    return text


register_node(NodeID.PREPARE_ACTION, prepare_action_node)
register_node(NodeID.MEMORY_CONTEXT, memory_context_node)
register_node(NodeID.PLANNING_RUN_LOCAL, planning_node)
register_node(NodeID.ACTION_TOOL_EXECUTION, action_execution_node)
register_node(NodeID.DIALOGUE_GENERATION, dialogue_generation_node)
register_node(NodeID.STRUCTURED_JSON_GENERATION, structured_json_generation_node)
register_node(NodeID.REFLECTION_GENERATION, reflection_generation_node)

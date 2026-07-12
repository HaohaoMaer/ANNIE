"""Project completed NPC route state into AgentResponse objects."""

from __future__ import annotations

from typing import Any

from annie.npc.route.registry import RouteEntry
from annie.npc.core.response import AgentResponse
from annie.npc.route.route_runner import route_node_path
from annie.npc.core.state import AgentState
from annie.npc.tools.tool_registry import ToolRegistry


def build_action_response(
    state: AgentState,
    runtime: dict[str, Any],
    *,
    entry: RouteEntry,
) -> AgentResponse:
    results = state.get("execution_results", [])
    dialogue_parts = [r["action"] for r in results if r.get("action")]
    dialogue = "\n".join(dialogue_parts)
    thoughts = runtime.get("inner_thoughts", []) or []
    memory_updates = [
        *runtime.get("memory_updates", []),
        *state.get("memory_updates", []),
    ]
    tool_registry = runtime.get("tool_registry")
    bound_tools = tool_registry.list_tools() if isinstance(tool_registry, ToolRegistry) else []
    return AgentResponse(
        route=entry.route_kind,
        route_id=str(entry.id),
        dialogue=dialogue,
        inner_thought="\n".join(str(t) for t in thoughts),
        tool_statuses=list(runtime.get("tool_statuses", [])),
        memory_updates=memory_updates,
        reflection=state.get("reflection", ""),
        debug=route_debug(
            entry,
            bound_tools=bound_tools,
            node_path=route_node_path(state),
        ),
    )


def build_reflection_response(
    state: AgentState,
    *,
    entry: RouteEntry,
) -> AgentResponse:
    return AgentResponse(
        route=entry.route_kind,
        route_id=str(entry.id),
        reflection=state.get("reflection", ""),
        debug=route_debug(entry, bound_tools=[], node_path=route_node_path(state)),
    )


def build_structured_json_response(
    state: AgentState,
    *,
    entry: RouteEntry,
) -> AgentResponse:
    return AgentResponse(
        route=entry.route_kind,
        route_id=str(entry.id),
        structured_output=state.get("structured_output", ""),
        debug=route_debug(entry, bound_tools=[], node_path=route_node_path(state)),
    )


def build_dialogue_response(
    state: AgentState,
    runtime: dict[str, Any],
    *,
    entry: RouteEntry,
) -> AgentResponse:
    thoughts = runtime.get("inner_thoughts", []) or []
    return AgentResponse(
        route=entry.route_kind,
        route_id=str(entry.id),
        dialogue=state.get("dialogue_output", ""),
        inner_thought="\n".join(str(t) for t in thoughts),
        tool_statuses=list(runtime.get("tool_statuses", [])),
        debug=route_debug(
            entry,
            bound_tools=list(state.get("bound_tools", [])),
            node_path=route_node_path(state),
        ),
    )


def route_debug(
    entry: RouteEntry,
    *,
    bound_tools: list[str],
    node_path: list[str],
) -> dict[str, Any]:
    return {
        "route_id": str(entry.id),
        "route_kind": entry.route_kind.value,
        "node_path": node_path,
        "node_composition": list(entry.node_composition),
        "bound_tools": bound_tools,
    }

"""Thin Python runner for NPC route-local state machines."""

from __future__ import annotations

from typing import Any, cast

from annie.npc.route.nodes import get_node
from annie.npc.route.route_model import (
    RouteDefinitionError,
    RouteExecutionError,
    RouteRuntime,
    RouteSpec,
)
from annie.npc.core.state import AgentState

_MAX_ROUTE_STEPS = 16


def run_route(
    spec: RouteSpec,
    state: AgentState,
    runtime: RouteRuntime,
    *,
    max_steps: int = _MAX_ROUTE_STEPS,
) -> AgentState:
    validate_route_spec(spec)
    current = spec.entry_node
    path: list[str] = []

    for _ in range(max_steps):
        path.append(str(current))
        state["debug_route_nodes"] = path[-max_steps:]
        node = get_node(current)
        updates = node(state, runtime)
        if updates:
            cast(dict[str, Any], state).update(updates)
        state["debug_route_nodes"] = path[-max_steps:]

        matched = [
            edge for edge in spec.edges
            if edge.source == current and edge.condition(state)
        ]
        if not matched:
            if current in spec.exit_nodes:
                return state
            raise RouteExecutionError(
                f"Route {spec.id} has no matching transition from {current}"
            )
        target = matched[0].target
        if target not in spec.allowed_nodes:
            raise RouteDefinitionError(
                f"Route {spec.id} transition {current}->{target} leaves allowed nodes"
            )
        current = target

    raise RouteExecutionError(f"Route {spec.id} exceeded max_steps={max_steps}")


def validate_route_spec(spec: RouteSpec) -> None:
    if spec.entry_node not in spec.allowed_nodes:
        raise RouteDefinitionError(f"Route {spec.id} entry node is not allowed")
    missing_exits = spec.exit_nodes.difference(spec.allowed_nodes)
    if missing_exits:
        raise RouteDefinitionError(f"Route {spec.id} exit nodes are not allowed: {missing_exits}")
    for edge in spec.edges:
        if edge.source not in spec.allowed_nodes:
            raise RouteDefinitionError(f"Route {spec.id} edge source is not allowed: {edge.source}")
        if edge.target not in spec.allowed_nodes:
            raise RouteDefinitionError(f"Route {spec.id} edge target is not allowed: {edge.target}")


def route_node_path(state: AgentState) -> list[str]:
    raw = state.get("debug_route_nodes", [])
    return [str(item) for item in raw]

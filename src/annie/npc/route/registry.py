"""NPC-owned registry mapping route ids to route specifications."""

from __future__ import annotations

from dataclasses import dataclass

from annie.npc.route.edge_conditions import always, consume_replan_retry, has_tasks
from annie.npc.route.route_model import NodeID, RouteEdge, RouteID, RouteSpec
from annie.npc.core.routes import AgentRoute


@dataclass(frozen=True)
class RouteEntry:
    """Minimal registry entry for a legal NPC cognitive route selector."""

    id: RouteID
    route_kind: AgentRoute
    response_kind: str
    node_composition: tuple[str, ...]
    route_spec: RouteSpec


class UnknownRouteIDError(ValueError):
    """Raised when an unregistered route id is requested."""


def _action_executor_default_spec() -> RouteSpec:
    return RouteSpec(
        id=RouteID.ACTION_EXECUTOR_DEFAULT,
        route_kind=AgentRoute.ACTION,
        response_kind="action",
        entry_node=NodeID.PREPARE_ACTION,
        exit_nodes=frozenset({NodeID.ACTION_TOOL_EXECUTION}),
        allowed_nodes=frozenset({
            NodeID.PREPARE_ACTION,
            NodeID.MEMORY_CONTEXT,
            NodeID.ACTION_TOOL_EXECUTION,
        }),
        edges=(
            RouteEdge(NodeID.PREPARE_ACTION, NodeID.MEMORY_CONTEXT, always, "prepared"),
            RouteEdge(NodeID.MEMORY_CONTEXT, NodeID.ACTION_TOOL_EXECUTION, always, "memory_loaded"),
        ),
        node_composition=("preparation", "memory", "action"),
        tool_policy="action",
    )


def _action_plan_execute_spec() -> RouteSpec:
    return RouteSpec(
        id=RouteID.ACTION_PLAN_EXECUTE,
        route_kind=AgentRoute.ACTION,
        response_kind="action",
        entry_node=NodeID.MEMORY_CONTEXT,
        exit_nodes=frozenset({NodeID.ACTION_TOOL_EXECUTION}),
        allowed_nodes=frozenset({
            NodeID.PREPARE_ACTION,
            NodeID.MEMORY_CONTEXT,
            NodeID.PLANNING_RUN_LOCAL,
            NodeID.ACTION_TOOL_EXECUTION,
        }),
        edges=(
            RouteEdge(NodeID.MEMORY_CONTEXT, NodeID.PLANNING_RUN_LOCAL, always, "memory_loaded"),
            RouteEdge(NodeID.PLANNING_RUN_LOCAL, NodeID.ACTION_TOOL_EXECUTION, has_tasks, "planned"),
            RouteEdge(NodeID.PLANNING_RUN_LOCAL, NodeID.PREPARE_ACTION, always, "default_task"),
            RouteEdge(NodeID.PREPARE_ACTION, NodeID.ACTION_TOOL_EXECUTION, always, "prepared"),
            RouteEdge(NodeID.ACTION_TOOL_EXECUTION, NodeID.PLANNING_RUN_LOCAL, consume_replan_retry, "replan"),
        ),
        node_composition=("memory", "planning", "preparation", "action"),
        tool_policy="action",
    )


def _dialogue_spec() -> RouteSpec:
    return RouteSpec(
        id=RouteID.DIALOGUE_MEMORY_THEN_OUTPUT,
        route_kind=AgentRoute.DIALOGUE,
        response_kind="dialogue",
        entry_node=NodeID.DIALOGUE_GENERATION,
        exit_nodes=frozenset({NodeID.DIALOGUE_GENERATION}),
        allowed_nodes=frozenset({NodeID.DIALOGUE_GENERATION}),
        edges=(),
        node_composition=("dialogue",),
        tool_policy="dialogue",
    )


def _structured_json_spec() -> RouteSpec:
    return RouteSpec(
        id=RouteID.OUTPUT_STRUCTURED_JSON,
        route_kind=AgentRoute.STRUCTURED_JSON,
        response_kind="structured_json",
        entry_node=NodeID.STRUCTURED_JSON_GENERATION,
        exit_nodes=frozenset({NodeID.STRUCTURED_JSON_GENERATION}),
        allowed_nodes=frozenset({NodeID.STRUCTURED_JSON_GENERATION}),
        edges=(),
        node_composition=("structured_output",),
        tool_policy="structured_json",
    )


def _reflection_spec() -> RouteSpec:
    return RouteSpec(
        id=RouteID.REFLECTION_EVIDENCE_TO_MEMORY_CANDIDATE,
        route_kind=AgentRoute.REFLECTION,
        response_kind="reflection",
        entry_node=NodeID.REFLECTION_GENERATION,
        exit_nodes=frozenset({NodeID.REFLECTION_GENERATION}),
        allowed_nodes=frozenset({NodeID.REFLECTION_GENERATION}),
        edges=(),
        node_composition=("reflection",),
        tool_policy="reflection",
    )


_REGISTRY: dict[RouteID, RouteEntry] = {
    RouteID.ACTION_EXECUTOR_DEFAULT: RouteEntry(
        id=RouteID.ACTION_EXECUTOR_DEFAULT,
        route_kind=AgentRoute.ACTION,
        response_kind="action",
        node_composition=("preparation", "memory", "action"),
        route_spec=_action_executor_default_spec(),
    ),
    RouteID.ACTION_PLAN_EXECUTE: RouteEntry(
        id=RouteID.ACTION_PLAN_EXECUTE,
        route_kind=AgentRoute.ACTION,
        response_kind="action",
        node_composition=("memory", "planning", "preparation", "action"),
        route_spec=_action_plan_execute_spec(),
    ),
    RouteID.DIALOGUE_MEMORY_THEN_OUTPUT: RouteEntry(
        id=RouteID.DIALOGUE_MEMORY_THEN_OUTPUT,
        route_kind=AgentRoute.DIALOGUE,
        response_kind="dialogue",
        node_composition=("dialogue",),
        route_spec=_dialogue_spec(),
    ),
    RouteID.OUTPUT_STRUCTURED_JSON: RouteEntry(
        id=RouteID.OUTPUT_STRUCTURED_JSON,
        route_kind=AgentRoute.STRUCTURED_JSON,
        response_kind="structured_json",
        node_composition=("structured_output",),
        route_spec=_structured_json_spec(),
    ),
    RouteID.REFLECTION_EVIDENCE_TO_MEMORY_CANDIDATE: RouteEntry(
        id=RouteID.REFLECTION_EVIDENCE_TO_MEMORY_CANDIDATE,
        route_kind=AgentRoute.REFLECTION,
        response_kind="reflection",
        node_composition=("reflection",),
        route_spec=_reflection_spec(),
    ),
}


def get_route_entry(route_id: str | RouteID) -> RouteEntry:
    """Return the registry entry for a route id or raise a clear error."""

    try:
        parsed = route_id if isinstance(route_id, RouteID) else RouteID(str(route_id))
    except ValueError as exc:
        raise UnknownRouteIDError(f"Unknown NPC route_id: {route_id!r}") from exc
    try:
        return _REGISTRY[parsed]
    except KeyError as exc:
        raise UnknownRouteIDError(f"Unknown NPC route_id: {route_id!r}") from exc


def get_route_spec(route_id: str | RouteID) -> RouteSpec:
    return get_route_entry(route_id).route_spec


def list_route_ids() -> list[str]:
    return [str(route_id) for route_id in _REGISTRY]


ROUTE_DEFAULT_IDS: dict[AgentRoute, RouteID] = {
    AgentRoute.ACTION: RouteID.ACTION_EXECUTOR_DEFAULT,
    AgentRoute.DIALOGUE: RouteID.DIALOGUE_MEMORY_THEN_OUTPUT,
    AgentRoute.STRUCTURED_JSON: RouteID.OUTPUT_STRUCTURED_JSON,
    AgentRoute.REFLECTION: RouteID.REFLECTION_EVIDENCE_TO_MEMORY_CANDIDATE,
}

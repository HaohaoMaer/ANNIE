"""NPC-owned cognitive graph registry.

World engines select a registered graph by id. They do not construct graph
nodes, edges, or policies themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Literal

from annie.npc.routes import AgentRoute


class AgentGraphID(StrEnum):
    """Stable public identifiers for NPC cognitive graphs."""

    ACTION_EXECUTOR_DEFAULT = "action.executor_default"
    ACTION_PLAN_EXECUTE = "action.plan_execute"
    DIALOGUE_MEMORY_THEN_OUTPUT = "dialogue.memory_then_output"
    OUTPUT_STRUCTURED_JSON = "output.structured_json"
    REFLECTION_EVIDENCE_TO_MEMORY_CANDIDATE = "reflection.evidence_to_memory_candidate"


GraphRunner = Literal["action", "dialogue", "structured_json", "reflection"]


@dataclass(frozen=True)
class CognitiveGraph:
    """Run-neutral graph descriptor produced by a registry builder."""

    id: AgentGraphID
    runner: GraphRunner
    node_path: tuple[str, ...]


@dataclass(frozen=True)
class GraphEntry:
    """Minimal registry entry for a legal NPC cognitive graph."""

    id: AgentGraphID
    route_kind: AgentRoute
    response_kind: str
    build: Callable[[], CognitiveGraph]


class UnknownAgentGraphError(ValueError):
    """Raised when a world engine requests an unregistered graph id."""


def _build_action_executor_default() -> CognitiveGraph:
    return CognitiveGraph(
        id=AgentGraphID.ACTION_EXECUTOR_DEFAULT,
        runner="action",
        node_path=("executor",),
    )


def _build_action_plan_execute() -> CognitiveGraph:
    return CognitiveGraph(
        id=AgentGraphID.ACTION_PLAN_EXECUTE,
        runner="action",
        node_path=("planner", "executor"),
    )


def _build_dialogue_memory_then_output() -> CognitiveGraph:
    return CognitiveGraph(
        id=AgentGraphID.DIALOGUE_MEMORY_THEN_OUTPUT,
        runner="dialogue",
        node_path=("dialogue_tool_loop", "dialogue_output"),
    )


def _build_structured_json() -> CognitiveGraph:
    return CognitiveGraph(
        id=AgentGraphID.OUTPUT_STRUCTURED_JSON,
        runner="structured_json",
        node_path=("json_output",),
    )


def _build_reflection() -> CognitiveGraph:
    return CognitiveGraph(
        id=AgentGraphID.REFLECTION_EVIDENCE_TO_MEMORY_CANDIDATE,
        runner="reflection",
        node_path=("reflection_output",),
    )


_REGISTRY: dict[AgentGraphID, GraphEntry] = {
    AgentGraphID.ACTION_EXECUTOR_DEFAULT: GraphEntry(
        id=AgentGraphID.ACTION_EXECUTOR_DEFAULT,
        route_kind=AgentRoute.ACTION,
        response_kind="action",
        build=_build_action_executor_default,
    ),
    AgentGraphID.ACTION_PLAN_EXECUTE: GraphEntry(
        id=AgentGraphID.ACTION_PLAN_EXECUTE,
        route_kind=AgentRoute.ACTION,
        response_kind="action",
        build=_build_action_plan_execute,
    ),
    AgentGraphID.DIALOGUE_MEMORY_THEN_OUTPUT: GraphEntry(
        id=AgentGraphID.DIALOGUE_MEMORY_THEN_OUTPUT,
        route_kind=AgentRoute.DIALOGUE,
        response_kind="dialogue",
        build=_build_dialogue_memory_then_output,
    ),
    AgentGraphID.OUTPUT_STRUCTURED_JSON: GraphEntry(
        id=AgentGraphID.OUTPUT_STRUCTURED_JSON,
        route_kind=AgentRoute.STRUCTURED_JSON,
        response_kind="structured_json",
        build=_build_structured_json,
    ),
    AgentGraphID.REFLECTION_EVIDENCE_TO_MEMORY_CANDIDATE: GraphEntry(
        id=AgentGraphID.REFLECTION_EVIDENCE_TO_MEMORY_CANDIDATE,
        route_kind=AgentRoute.REFLECTION,
        response_kind="reflection",
        build=_build_reflection,
    ),
}

_GRAPH_CACHE: dict[AgentGraphID, CognitiveGraph] = {}


def get_graph_entry(graph_id: str | AgentGraphID) -> GraphEntry:
    """Return the registry entry for a graph id or raise a clear error."""

    try:
        parsed = graph_id if isinstance(graph_id, AgentGraphID) else AgentGraphID(str(graph_id))
    except ValueError as exc:
        raise UnknownAgentGraphError(f"Unknown NPC graph_id: {graph_id!r}") from exc
    try:
        return _REGISTRY[parsed]
    except KeyError as exc:
        raise UnknownAgentGraphError(f"Unknown NPC graph_id: {graph_id!r}") from exc


def build_registered_graph(entry: GraphEntry) -> CognitiveGraph:
    """Build or fetch a run-neutral graph descriptor for a registry entry."""

    graph = _GRAPH_CACHE.get(entry.id)
    if graph is None:
        graph = entry.build()
        _GRAPH_CACHE[entry.id] = graph
    return graph


def list_graph_ids() -> list[str]:
    return [str(graph_id) for graph_id in _REGISTRY]


ROUTE_DEFAULT_GRAPHS: dict[AgentRoute, AgentGraphID] = {
    AgentRoute.ACTION: AgentGraphID.ACTION_EXECUTOR_DEFAULT,
    AgentRoute.DIALOGUE: AgentGraphID.DIALOGUE_MEMORY_THEN_OUTPUT,
    AgentRoute.STRUCTURED_JSON: AgentGraphID.OUTPUT_STRUCTURED_JSON,
    AgentRoute.REFLECTION: AgentGraphID.REFLECTION_EVIDENCE_TO_MEMORY_CANDIDATE,
}

DIRECT_MODE_DEFAULT_GRAPHS: dict[str, AgentGraphID] = {
    "dialogue": AgentGraphID.DIALOGUE_MEMORY_THEN_OUTPUT,
    "json": AgentGraphID.OUTPUT_STRUCTURED_JSON,
    "reflection": AgentGraphID.REFLECTION_EVIDENCE_TO_MEMORY_CANDIDATE,
}

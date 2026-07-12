"""Run-neutral route model for NPC-owned state machines."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from annie.npc.core.routes import AgentRoute
from annie.npc.core.state import AgentState


class RouteID(StrEnum):
    ACTION_EXECUTOR_DEFAULT = "action.executor_default"
    ACTION_PLAN_EXECUTE = "action.plan_execute"
    DIALOGUE_MEMORY_THEN_OUTPUT = "dialogue.memory_then_output"
    OUTPUT_STRUCTURED_JSON = "output.structured_json"
    REFLECTION_EVIDENCE_TO_MEMORY_CANDIDATE = "reflection.evidence_to_memory_candidate"


class NodeID(StrEnum):
    PREPARE_ACTION = "preparation.action"
    MEMORY_CONTEXT = "memory.context"
    PLANNING_RUN_LOCAL = "planning.run_local"
    ACTION_TOOL_EXECUTION = "action.tool_execution"
    DIALOGUE_GENERATION = "dialogue.generation"
    STRUCTURED_JSON_GENERATION = "structured_json.generation"
    REFLECTION_GENERATION = "reflection.generation"


EdgeCondition = Callable[[AgentState], bool]


@dataclass(frozen=True)
class RouteEdge:
    source: NodeID
    target: NodeID
    condition: EdgeCondition
    label: str = ""


@dataclass(frozen=True)
class RouteSpec:
    id: RouteID
    route_kind: AgentRoute
    response_kind: str
    entry_node: NodeID
    exit_nodes: frozenset[NodeID]
    allowed_nodes: frozenset[NodeID]
    edges: tuple[RouteEdge, ...]
    node_composition: tuple[str, ...]
    tool_policy: str


@dataclass(frozen=True)
class RouteRuntime:
    llm: Any
    planner: Any = None
    executor: Any = None
    tool_registry: Any = None
    dispatcher: Any = None


class RouteExecutionError(RuntimeError):
    """Raised when a route cannot complete with its declared edges."""


class RouteDefinitionError(ValueError):
    """Raised when a route spec references nodes outside its boundary."""

from __future__ import annotations

import pytest

from annie.npc.route.edge_conditions import always
from annie.npc.route.route_model import (
    NodeID,
    RouteDefinitionError,
    RouteEdge,
    RouteExecutionError,
    RouteID,
    RouteRuntime,
    RouteSpec,
)
from annie.npc.route.route_runner import run_route
from annie.npc.core.routes import AgentRoute


def _spec(*, edges, exit_nodes, allowed_nodes=None):
    return RouteSpec(
        id=RouteID.ACTION_EXECUTOR_DEFAULT,
        route_kind=AgentRoute.ACTION,
        response_kind="action",
        entry_node=NodeID.PREPARE_ACTION,
        exit_nodes=frozenset(exit_nodes),
        allowed_nodes=frozenset(allowed_nodes or {
            NodeID.PREPARE_ACTION,
            NodeID.MEMORY_CONTEXT,
            NodeID.ACTION_TOOL_EXECUTION,
        }),
        edges=tuple(edges),
        node_composition=("test",),
        tool_policy="action",
    )


def test_route_runner_executes_successful_transitions():
    state = run_route(
        _spec(
            edges=[
                RouteEdge(NodeID.PREPARE_ACTION, NodeID.ACTION_TOOL_EXECUTION, always),
            ],
            exit_nodes={NodeID.ACTION_TOOL_EXECUTION},
        ),
        {"runtime": {}, "agent_context": None, "input_event": ""},
        RouteRuntime(llm=None, executor=lambda state: {"execution_results": [{"action": "ok"}]}),
    )

    assert state["debug_route_nodes"] == [
        "preparation.action",
        "action.tool_execution",
    ]


def test_route_runner_stops_at_route_exit_without_outgoing_edge():
    state = run_route(
        _spec(edges=[], exit_nodes={NodeID.PREPARE_ACTION}),
        {},
        RouteRuntime(llm=None),
    )

    assert state["debug_route_nodes"] == ["preparation.action"]


def test_route_runner_fails_on_missing_transition():
    with pytest.raises(RouteExecutionError, match="no matching transition"):
        run_route(
            _spec(edges=[], exit_nodes={NodeID.ACTION_TOOL_EXECUTION}),
            {},
            RouteRuntime(llm=None),
        )


def test_route_runner_rejects_disallowed_target():
    spec = _spec(
        edges=[RouteEdge(NodeID.PREPARE_ACTION, NodeID.PLANNING_RUN_LOCAL, always)],
        exit_nodes={NodeID.ACTION_TOOL_EXECUTION},
    )

    with pytest.raises(RouteDefinitionError, match="edge target is not allowed"):
        run_route(spec, {}, RouteRuntime(llm=None))

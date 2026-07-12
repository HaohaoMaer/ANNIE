"""Route selection helpers for the NPC Agent facade."""

from __future__ import annotations

from annie.npc.core.context import AgentContext
from annie.npc.route.registry import ROUTE_DEFAULT_IDS
from annie.npc.route.route_model import RouteID
from annie.npc.core.routes import AgentRoute


def resolve_route_id(context: AgentContext) -> RouteID:
    """Resolve the registered route id for one NPC run."""

    planner_policy = str(context.extra.get("action_planning", "") or "").lower()
    if planner_policy in {"always", "complex", "plan"}:
        return RouteID.ACTION_PLAN_EXECUTE

    return ROUTE_DEFAULT_IDS[resolve_route(context)]


def resolve_route(context: AgentContext) -> AgentRoute:
    """Resolve the typed route requested by the context."""

    route = context.route
    if isinstance(route, AgentRoute):
        return route
    return AgentRoute(str(route))

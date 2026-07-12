"""NPCAgent: stateless facade over NPC-owned route execution."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel

from annie.npc.core.context import AgentContext
from annie.npc.route.edge_conditions import consume_replan_retry
from annie.npc.cognition.executor import Executor
from annie.npc.route.registry import RouteEntry, get_route_entry
from annie.npc.route.selection import resolve_route_id
from annie.npc.route.nodes import build_action_route_state, build_direct_route_state
from annie.npc.cognition.planner import Planner
from annie.npc.core.response import AgentResponse
from annie.npc.route.response_projection import (
    build_action_response,
    build_dialogue_response,
    build_reflection_response,
    build_structured_json_response,
)
from annie.npc.route.route_model import RouteRuntime
from annie.npc.route.route_runner import run_route
from annie.npc.core.routes import AgentRoute
from annie.npc.skills.base_skill import SkillRegistry
from annie.npc.skills.registry import load_dir as load_skill_dir
from annie.npc.runtime import SkillRuntime, ToolDispatcher, new_run_runtime
from annie.npc.core.state import AgentState
from annie.npc.tools.tool_registry import ToolRegistry
from annie.npc.observability.tracing import Tracer

logger = logging.getLogger(__name__)

_DEFAULT_MAX_RETRIES = 1
_DEFAULT_MODEL_CTX_LIMIT = 128_000


def _after_executor(state: AgentState) -> str:
    """Compatibility helper for tests of the retry condition."""

    return "retry" if consume_replan_retry(state) else "done"


class NPCAgent:
    """Stateless NPC runner driven by AgentContext/AgentResponse."""

    def __init__(
        self,
        llm: BaseChatModel,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        model_ctx_limit: int = _DEFAULT_MODEL_CTX_LIMIT,
        skills_dir: str | None = None,
    ):
        self.llm = llm
        self.max_retries = max_retries
        self.model_ctx_limit = model_ctx_limit
        self._skill_registry: SkillRegistry = (
            load_skill_dir(skills_dir) if skills_dir else SkillRegistry()
        )

    def run(self, context: AgentContext) -> AgentResponse:
        """Run one registered cognitive route for a single NPC."""

        route_id = resolve_route_id(context)
        entry = get_route_entry(route_id)
        state, runtime, run_runtime = self._create_run(entry, context)
        final_state = run_route(entry.route_spec, state, runtime)
        return self._project_response(final_state, run_runtime, entry)

    def _create_run(
        self,
        entry: RouteEntry,
        context: AgentContext,
    ) -> tuple[AgentState, RouteRuntime, dict[str, Any]]:
        if entry.route_kind == AgentRoute.ACTION:
            return self._create_action_run(entry, context)
        if entry.route_kind == AgentRoute.DIALOGUE:
            return self._create_dialogue_run(entry, context)
        return self._create_direct_run(context)

    def _create_action_run(
        self,
        entry: RouteEntry,
        context: AgentContext,
    ) -> tuple[AgentState, RouteRuntime, dict[str, Any]]:
        tracer = Tracer(agent_name=context.npc_id)
        tool_registry = ToolRegistry(
            injected=list(context.tools),
            disabled_tools=set(context.extra.get("disabled_tools", []) or []),
            route=entry.route_kind.value,
        )
        run_skills = SkillRegistry()
        for skill in self._skill_registry.list_skills():
            run_skills.add(skill)
        for skill in context.skills:
            run_skills.add(skill)

        run_runtime = new_run_runtime(
            tool_registry,
            skill_runtime=SkillRuntime(run_skills),
        )
        dispatcher = ToolDispatcher(tool_registry, runtime=run_runtime)
        executor = Executor(self.llm, dispatcher)
        state = build_action_route_state(
            context,
            tracer=tracer,
            runtime=run_runtime,
            max_retries=self.max_retries,
            model_ctx_limit=self.model_ctx_limit,
        )
        route_runtime = RouteRuntime(
            llm=self.llm,
            planner=Planner(self.llm),
            executor=executor,
            tool_registry=tool_registry,
            dispatcher=dispatcher,
        )
        return state, route_runtime, run_runtime

    def _create_dialogue_run(
        self,
        entry: RouteEntry,
        context: AgentContext,
    ) -> tuple[AgentState, RouteRuntime, dict[str, Any]]:
        tool_registry = ToolRegistry(
            injected=list(context.tools),
            disabled_tools=set(context.extra.get("disabled_tools", []) or []),
            route=entry.route_kind.value,
        )
        run_runtime = new_run_runtime(tool_registry)
        dispatcher = ToolDispatcher(tool_registry, runtime=run_runtime)
        state = build_direct_route_state(context, runtime=run_runtime)
        route_runtime = RouteRuntime(
            llm=self.llm,
            tool_registry=tool_registry,
            dispatcher=dispatcher,
        )
        return state, route_runtime, run_runtime

    def _create_direct_run(
        self,
        context: AgentContext,
    ) -> tuple[AgentState, RouteRuntime, dict[str, Any]]:
        state = build_direct_route_state(context)
        run_runtime = state.get("runtime", {})
        return state, RouteRuntime(llm=self.llm), run_runtime

    def _project_response(
        self,
        state: AgentState,
        runtime: dict[str, Any],
        entry: RouteEntry,
    ) -> AgentResponse:
        if entry.response_kind == "action":
            return build_action_response(state, runtime, entry=entry)
        if entry.response_kind == "dialogue":
            return build_dialogue_response(state, runtime, entry=entry)
        if entry.response_kind == "structured_json":
            return build_structured_json_response(state, entry=entry)
        return build_reflection_response(state, entry=entry)

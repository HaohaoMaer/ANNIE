"""NPCAgent — stateless, AgentContext-driven LangGraph runner.

One ``NPCAgent`` instance can drive any number of NPCs: all per-NPC data
flows in through ``AgentContext`` on each ``run()`` call; nothing persists
on ``self`` between runs except stateless LLM / graph wiring.

Flow (LangGraph): Planner → Executor → Reflector, with retry from
Executor→Planner when the Executor produces no usable results.
"""

from __future__ import annotations

import logging
from typing import cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from annie.npc.context import AgentContext
from annie.npc.context_budget import ContextBudget
from annie.npc.executor import SKIP_TASK_MARKER, Executor, _tool_to_schema
from annie.npc.graph_registry import (
    DIRECT_MODE_DEFAULT_GRAPHS,
    ROUTE_DEFAULT_GRAPHS,
    AgentGraphID,
    CognitiveGraph,
    GraphEntry,
    build_registered_graph,
    get_graph_entry,
)
from annie.npc.prompts import (
    build_direct_dialogue_messages,
    build_direct_json_messages,
    build_direct_reflection_messages,
)
from annie.npc.planner import Planner
from annie.npc.reflector import Reflector
from annie.npc.response import AgentResponse
from annie.npc.routes import AgentRoute
from annie.npc.state import AgentState, Task, TaskStatus
from annie.npc.skills.base_skill import SkillRegistry
from annie.npc.skills.registry import load_dir as load_skill_dir
from annie.npc.runtime import MemoryContextBuilder, SkillRuntime, ToolDispatcher
from annie.npc.tools.tool_registry import ToolRegistry
from annie.npc.tracing import Tracer

logger = logging.getLogger(__name__)

_DEFAULT_MAX_RETRIES = 1
_DEFAULT_MODEL_CTX_LIMIT = 128_000
_DIALOGUE_MAX_TOOL_LOOPS = 2


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

    # ------------------------------------------------------------------
    def run(self, context: AgentContext) -> AgentResponse:
        """Run one registered cognitive graph for a single NPC."""
        graph_id = _resolve_graph_id(context)
        entry = get_graph_entry(graph_id)
        graph = build_registered_graph(entry)
        if graph.runner == "reflection":
            return self._run_direct_reflection(context, entry, graph)
        if graph.runner == "structured_json":
            return self._run_direct_json(context, entry, graph)
        if graph.runner == "dialogue":
            return self._run_direct_dialogue(context, entry, graph)
        return self._run_action(context, entry, graph)

    def _run_action(
        self,
        context: AgentContext,
        entry: GraphEntry,
        graph: CognitiveGraph,
    ) -> AgentResponse:
        tracer = Tracer(agent_name=context.npc_id)

        memory_context = MemoryContextBuilder(context.memory)
        disabled_tools = set(context.extra.get("disabled_tools", []) or [])
        tool_registry = ToolRegistry(
            injected=list(context.tools),
            disabled_tools=disabled_tools,
            route=entry.route_kind.value,
        )
        runtime = _new_runtime(tool_registry)
        tool_dispatcher = ToolDispatcher(tool_registry, runtime=runtime)

        # Merge global skill registry with AgentContext.skills (context wins).
        run_skills = SkillRegistry()
        for s in self._skill_registry.list_skills():
            run_skills.add(s)
        for s in context.skills:
            run_skills.add(s)
        skill_runtime = SkillRuntime(run_skills)

        runtime["skill_runtime"] = skill_runtime

        executor = Executor(self.llm, tool_dispatcher)

        seen_ids: set[str] = runtime["recall_seen_ids"]

        initial: AgentState = {
            "agent_context": context,
            "input_event": context.input_event,
            "tasks": [],
            "current_task": None,
            "execution_results": [],
            "reflection": "",
            "working_memory": memory_context.build_context(context.input_event, seen_ids=seen_ids),
            "tracer": tracer,
            "retry_count": 0,
            "max_retries": self.max_retries,
            "loop_reason": "",
            "last_tasks": [],
            "react_steps": [],
            "messages": [],
            "context_budget": ContextBudget(model_ctx_limit=self.model_ctx_limit),
            "runtime": runtime,
            "todo_list_text": context.todo,
            "active_skills": [],
            "memory_updates": [],
        }

        planner_policy = str(context.extra.get("action_planning", "") or "").lower()
        use_planner_first = (
            graph.id == AgentGraphID.ACTION_PLAN_EXECUTE
            or planner_policy in {"always", "complex", "plan"}
        )
        final_state = (
            _run_action_with_planner(
                initial,
                llm=self.llm,
                executor=executor,
                max_retries=self.max_retries,
            )
            if use_planner_first
            else _run_action_executor_first(
                initial,
                llm=self.llm,
                executor=executor,
                max_retries=self.max_retries,
            )
        )
        final_state["debug_graph_nodes"] = list(graph.node_path)
        return _build_response(dict(final_state), runtime, entry=entry, graph=graph)

    def _run_direct_reflection(
        self,
        context: AgentContext,
        entry: GraphEntry,
        graph: CognitiveGraph,
    ) -> AgentResponse:
        """Run one LLM call for cognition-only reflection contexts."""
        response = self.llm.invoke(build_direct_reflection_messages(context))
        raw = str(getattr(response, "content", response) or "").strip()
        return AgentResponse(
            route=entry.route_kind,
            graph_id=str(entry.id),
            reflection=_sanitize_reflection_text(_extract_direct_reflection_text(raw)),
            debug=_graph_debug(entry, graph, bound_tools=[]),
        )

    def _run_direct_json(
        self,
        context: AgentContext,
        entry: GraphEntry,
        graph: CognitiveGraph,
    ) -> AgentResponse:
        response = self.llm.invoke(build_direct_json_messages(context))
        raw = str(getattr(response, "content", response) or "").strip()
        return AgentResponse(
            route=entry.route_kind,
            graph_id=str(entry.id),
            structured_output=raw,
            debug=_graph_debug(entry, graph, bound_tools=[]),
        )

    def _run_direct_dialogue(
        self,
        context: AgentContext,
        entry: GraphEntry,
        graph: CognitiveGraph,
    ) -> AgentResponse:
        tool_registry = ToolRegistry(
            injected=list(context.tools),
            disabled_tools=set(context.extra.get("disabled_tools", []) or []),
            route=entry.route_kind.value,
        )
        runtime = _new_runtime(tool_registry)
        dispatcher = ToolDispatcher(tool_registry, runtime=runtime)
        messages = build_direct_dialogue_messages(context)
        bound_tool_names: list[str] = []
        last_response: AIMessage | None = None

        for step in range(_DIALOGUE_MAX_TOOL_LOOPS + 1):
            tool_defs = [tool_registry.get(n) for n in tool_registry.list_tools()]
            tool_defs = [t for t in tool_defs if t is not None]
            bound_tool_names = [t.name for t in tool_defs]
            tool_schemas = [_tool_to_schema(t) for t in tool_defs]
            try:
                llm = self.llm.bind_tools(tool_schemas) if tool_schemas else self.llm  # type: ignore[attr-defined]
            except (NotImplementedError, AttributeError):
                llm = self.llm
            response = llm.invoke(messages)
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
        thoughts = runtime.get("inner_thoughts", []) or []
        return AgentResponse(
            route=entry.route_kind,
            graph_id=str(entry.id),
            dialogue=_extract_direct_dialogue_text(raw),
            inner_thought="\n".join(str(t) for t in thoughts),
            debug=_graph_debug(entry, graph, bound_tools=bound_tool_names),
        )


# ----------------------------------------------------------------------
# Graph wiring
# ----------------------------------------------------------------------

def _build_graph(planner: Planner, executor: Executor, reflector: Reflector):
    sg: StateGraph = StateGraph(AgentState)
    sg.add_node("planner", planner)
    sg.add_node("executor", _executor_with_skip(executor))
    sg.add_node("reflector", reflector)

    sg.add_edge(START, "planner")
    sg.add_edge("planner", "executor")
    sg.add_conditional_edges(
        "executor",
        _after_executor,
        {"action": END, "retry": "planner", "done": "reflector"},
    )
    sg.add_edge("reflector", END)
    return sg.compile()


def _run_action_executor_first(
    initial: AgentState,
    *,
    llm: BaseChatModel,
    executor: Executor,
    max_retries: int,
) -> AgentState:
    state = cast(AgentState, dict(initial))
    state["tasks"] = [Task(description=SKIP_TASK_MARKER, priority=5)]
    state["last_tasks"] = list(state["tasks"])
    state.update(executor(state))
    if _after_executor(state) == "retry" and max_retries > 0:
        planner = Planner(llm)
        state.update(planner(state))
        state.update(_executor_with_skip(executor)(state))
    return state


def _run_action_with_planner(
    initial: AgentState,
    *,
    llm: BaseChatModel,
    executor: Executor,
    max_retries: int,
) -> AgentState:
    planner = Planner(llm)
    state = cast(AgentState, dict(initial))
    state.update(planner(state))
    state.update(_executor_with_skip(executor)(state))
    if _after_executor(state) == "retry" and max_retries > 0:
        state.update(planner(state))
        state.update(_executor_with_skip(executor)(state))
    return state


def _executor_with_skip(executor: Executor):
    """If Planner produced no tasks (skip), synthesize a marker task so the
    Executor renders only ``<input_event>`` (no redundant ``<task>``).

    Also snapshots the task list into ``state["last_tasks"]`` so Planner can
    reference the previous attempt if the retry edge fires.
    """
    def _run(state: AgentState) -> dict:
        tasks = state.get("tasks", [])
        if not tasks:
            tasks = [Task(description=SKIP_TASK_MARKER, priority=5)]
            state["tasks"] = tasks
        state["last_tasks"] = list(tasks)
        return executor(state)
    return _run


def _after_executor(state: AgentState) -> str:
    runtime = state.get("runtime", {})
    if runtime.get("pending_action_ids") and runtime.get("actions"):
        return "action"

    results = state.get("execution_results", [])
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 0)
    all_failed = bool(state.get("tasks")) and all(
        t.status == TaskStatus.FAILED for t in state.get("tasks", [])
    )
    if (not results or all_failed) and retry_count < max_retries:
        state["retry_count"] = retry_count + 1
        state["loop_reason"] = "executor produced no results"
        return "retry"
    return "done"


def _build_response(
    state: dict,
    runtime: dict,
    entry: GraphEntry,
    graph: CognitiveGraph,
) -> AgentResponse:
    results = state.get("execution_results", [])
    dialogue_parts = [r["action"] for r in results if r.get("action")]
    dialogue = "\n".join(dialogue_parts)
    thoughts = runtime.get("inner_thoughts", []) or []
    inner_thought = "\n".join(str(t) for t in thoughts)
    memory_updates = [
        *runtime.get("memory_updates", []),
        *state.get("memory_updates", []),
    ]
    tool_registry = runtime.get("tool_registry")
    bound_tools = tool_registry.list_tools() if isinstance(tool_registry, ToolRegistry) else []
    return AgentResponse(
        route=entry.route_kind,
        graph_id=str(entry.id),
        dialogue=dialogue,
        inner_thought=inner_thought,
        actions=list(runtime.get("actions", [])),
        memory_updates=memory_updates,
        reflection=state.get("reflection", ""),
        debug=_graph_debug(
            entry,
            graph,
            bound_tools=bound_tools,
            action_nodes=list(state.get("debug_action_nodes", []) or []),
        ),
    )


def _resolve_graph_id(context: AgentContext) -> str | AgentGraphID:
    if context.graph_id:
        return context.graph_id

    if "route" in context.model_fields_set:
        route = _resolve_route(context)
        return ROUTE_DEFAULT_GRAPHS[route]

    direct_mode = context.extra.get("npc_direct_mode")
    if isinstance(direct_mode, str) and direct_mode in DIRECT_MODE_DEFAULT_GRAPHS:
        return DIRECT_MODE_DEFAULT_GRAPHS[direct_mode]

    return ROUTE_DEFAULT_GRAPHS[AgentRoute.ACTION]


def _resolve_route(context: AgentContext) -> AgentRoute:
    direct_mode = context.extra.get("npc_direct_mode")
    if direct_mode == "reflection":
        return AgentRoute.REFLECTION
    if direct_mode == "json":
        return AgentRoute.STRUCTURED_JSON
    if direct_mode == "dialogue":
        return AgentRoute.DIALOGUE
    route = context.route
    if isinstance(route, AgentRoute):
        return route
    return AgentRoute(str(route))


def _graph_debug(
    entry: GraphEntry,
    graph: CognitiveGraph,
    *,
    bound_tools: list[str],
    action_nodes: list[str] | None = None,
) -> dict:
    debug = {
        "graph_id": str(entry.id),
        "route_kind": entry.route_kind.value,
        "node_path": list(graph.node_path),
        "bound_tools": bound_tools,
    }
    if action_nodes is not None:
        debug["action_nodes"] = action_nodes
    return debug


def _new_runtime(tool_registry: ToolRegistry) -> dict:
    return {
        "tool_registry": tool_registry,
        "recall_seen_ids": set(),
        "inner_thoughts": [],
        "memory_updates": [],
        "actions": [],
        "action_results": [],
        "pending_action_ids": [],
        "skill_frames": [],
    }


def _extract_direct_reflection_text(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    if text.startswith("{"):
        import json

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
        import json

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
    """Reject reflection text that leaks orchestration terms."""
    if any(term in text for term in _REFLECTION_FORBIDDEN_TERMS):
        return ""
    return text

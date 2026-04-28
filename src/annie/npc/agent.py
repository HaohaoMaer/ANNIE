"""NPCAgent — stateless, AgentContext-driven LangGraph runner.

One ``NPCAgent`` instance can drive any number of NPCs: all per-NPC data
flows in through ``AgentContext`` on each ``run()`` call; nothing persists
on ``self`` between runs except stateless LLM / graph wiring.

Flow (LangGraph): Planner → Executor → Reflector, with retry from
Executor→Planner when the Executor produces no usable results.
"""

from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from annie.npc.context import AgentContext
from annie.npc.context_budget import ContextBudget
from annie.npc.executor import SKIP_TASK_MARKER, Executor
from annie.npc.planner import Planner
from annie.npc.reflector import Reflector
from annie.npc.response import AgentResponse
from annie.npc.state import AgentState, Task, TaskStatus
from annie.npc.skills.base_skill import SkillRegistry
from annie.npc.skills.registry import load_dir as load_skill_dir
from annie.npc.runtime import MemoryContextBuilder, SkillRuntime, ToolDispatcher
from annie.npc.tools.tool_registry import ToolRegistry
from annie.npc.tracing import Tracer

logger = logging.getLogger(__name__)

_DEFAULT_MAX_RETRIES = 1
_DEFAULT_MODEL_CTX_LIMIT = 128_000


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
        """Run a full Planner→Executor→Reflector cycle for a single NPC."""
        tracer = Tracer(agent_name=context.npc_id)

        memory_context = MemoryContextBuilder(context.memory)
        tool_registry = ToolRegistry(injected=list(context.tools))
        runtime: dict = {
            "tool_registry": tool_registry,
            "recall_seen_ids": set(),
            "inner_thoughts": [],
            "memory_updates": [],
            "actions": [],
            "action_results": [],
            "pending_action_ids": [],
            "skill_frames": [],
        }
        tool_dispatcher = ToolDispatcher(tool_registry, runtime=runtime)

        # Merge global skill registry with AgentContext.skills (context wins).
        run_skills = SkillRegistry()
        for s in self._skill_registry.list_skills():
            run_skills.add(s)
        for s in context.skills:
            run_skills.add(s)
        skill_runtime = SkillRuntime(run_skills)

        runtime["skill_runtime"] = skill_runtime

        planner = Planner(self.llm)
        executor = Executor(self.llm, tool_dispatcher)
        reflector = Reflector(self.llm)

        graph = _build_graph(planner, executor, reflector)

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

        final_state = graph.invoke(initial)
        return _build_response(dict(final_state), runtime)


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


def _build_response(state: dict, runtime: dict) -> AgentResponse:
    results = state.get("execution_results", [])
    dialogue_parts = [r["action"] for r in results if r.get("action")]
    dialogue = "\n".join(dialogue_parts)
    thoughts = runtime.get("inner_thoughts", []) or []
    inner_thought = "\n".join(str(t) for t in thoughts)
    memory_updates = [
        *runtime.get("memory_updates", []),
        *state.get("memory_updates", []),
    ]
    return AgentResponse(
        dialogue=dialogue,
        inner_thought=inner_thought,
        actions=list(runtime.get("actions", [])),
        memory_updates=memory_updates,
        reflection=state.get("reflection", ""),
    )

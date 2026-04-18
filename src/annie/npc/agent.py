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
from annie.npc.prompts import render_todo_text
from annie.npc.reflector import Reflector
from annie.npc.response import AgentResponse
from annie.npc.state import AgentState, Task, TaskStatus
from annie.npc.skills.base_skill import SkillRegistry
from annie.npc.skills.registry import load_dir as load_skill_dir
from annie.npc.sub_agents.memory_agent import MemoryAgent
from annie.npc.sub_agents.skill_agent import SkillAgent
from annie.npc.sub_agents.tool_agent import ToolAgent
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

        memory_agent = MemoryAgent(context.memory)
        tool_registry = ToolRegistry(injected=list(context.tools))
        tool_agent = ToolAgent(tool_registry)

        # Merge global skill registry with AgentContext.skills (context wins).
        run_skills = SkillRegistry()
        for s in self._skill_registry.list_skills():
            run_skills.add(s)
        for s in context.skills:
            run_skills.add(s)
        skill_agent = SkillAgent(run_skills)

        # Expose to the use_skill built-in via AgentContext.extra.
        context.extra.setdefault("_skill_agent", skill_agent)
        context.extra.setdefault("_tool_registry", tool_registry)
        # Run-scoped recall dedup: records returned in <working_memory> won't
        # appear again in tool responses for the duration of this run.
        context.extra.setdefault("_recall_seen_ids", set())

        planner = Planner(self.llm)
        executor = Executor(self.llm, tool_agent)
        reflector = Reflector(self.llm, memory_agent)

        graph = _build_graph(planner, executor, reflector)

        seen_ids: set[str] = context.extra["_recall_seen_ids"]

        initial: AgentState = {
            "agent_context": context,
            "input_event": context.input_event,
            "tasks": [],
            "current_task": None,
            "execution_results": [],
            "reflection": "",
            "working_memory": memory_agent.build_context(context.input_event, seen_ids=seen_ids),
            "tracer": tracer,
            "retry_count": 0,
            "max_retries": self.max_retries,
            "loop_reason": "",
            "last_tasks": [],
            "react_steps": [],
            "messages": [],
            "context_budget": ContextBudget(model_ctx_limit=self.model_ctx_limit),
            "todo_list_text": render_todo_text(context.memory),
            "active_skills": [],
        }

        final_state = graph.invoke(initial)
        return _build_response(dict(final_state), context)


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
    sg.add_conditional_edges("executor", _should_retry, {"retry": "planner", "done": "reflector"})
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


def _should_retry(state: AgentState) -> str:
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


def _build_response(state: dict, context: AgentContext) -> AgentResponse:
    results = state.get("execution_results", [])
    dialogue_parts = [r["action"] for r in results if r.get("action")]
    dialogue = "\n".join(dialogue_parts)
    thoughts = context.extra.get("_inner_thoughts", []) or []
    inner_thought = "\n".join(str(t) for t in thoughts)
    return AgentResponse(
        dialogue=dialogue,
        inner_thought=inner_thought,
        actions=[],
        memory_updates=[],
        reflection=state.get("reflection", ""),
    )

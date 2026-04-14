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
from annie.npc.executor import Executor
from annie.npc.planner import Planner
from annie.npc.reflector import Reflector
from annie.npc.response import AgentResponse
from annie.npc.state import AgentState, Task, TaskStatus
from annie.npc.sub_agents.memory_agent import MemoryAgent
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
    ):
        self.llm = llm
        self.max_retries = max_retries
        self.model_ctx_limit = model_ctx_limit

    # ------------------------------------------------------------------
    def run(self, context: AgentContext) -> AgentResponse:
        """Run a full Planner→Executor→Reflector cycle for a single NPC."""
        tracer = Tracer(agent_name=context.npc_id)

        memory_agent = MemoryAgent(context.memory)
        tool_registry = ToolRegistry(injected=list(context.tools))
        tool_agent = ToolAgent(tool_registry)

        planner = Planner(self.llm)
        executor = Executor(self.llm, tool_agent)
        reflector = Reflector(self.llm, memory_agent)

        graph = _build_graph(planner, executor, reflector)

        initial: AgentState = {
            "agent_context": context,
            "input_event": context.input_event,
            "tasks": [],
            "current_task": None,
            "execution_results": [],
            "reflection": "",
            "memory_context": memory_agent.build_context(context.input_event),
            "tracer": tracer,
            "retry_count": 0,
            "max_retries": self.max_retries,
            "loop_reason": "",
            "react_steps": [],
            "messages": [],
            "context_budget": ContextBudget(model_ctx_limit=self.model_ctx_limit),
        }

        final_state = graph.invoke(initial)
        return _build_response(dict(final_state))


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
    """If Planner produced no tasks (skip), synthesize a single task from the event."""
    def _run(state: AgentState) -> dict:
        tasks = state.get("tasks", [])
        if not tasks:
            evt = state.get("input_event", "")
            tasks = [Task(description=evt or "Respond to the current situation.", priority=5)]
            state["tasks"] = tasks
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


def _build_response(state: dict) -> AgentResponse:
    results = state.get("execution_results", [])
    dialogue_parts = [r["action"] for r in results if r.get("action")]
    dialogue = "\n".join(dialogue_parts)
    return AgentResponse(
        dialogue=dialogue,
        inner_thought="",
        actions=[],
        memory_updates=[],
        reflection=state.get("reflection", ""),
    )

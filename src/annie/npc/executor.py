"""Executor — native tool-use loop over AgentContext.

For each planned task, assembles an initial message list (XML-sectioned
SystemMessage + rolling history turns + current task), then runs:

    while True:
        ContextBudget.check(messages, llm)        # Emergency fold if needed
        ai = llm.bind_tools(tools).invoke(messages)
        messages.append(ai)
        if not ai.tool_calls: break               # final answer
        for call in ai.tool_calls:
            result = ToolAgent.dispatch(call, ctx)   # Micro-compressed
            messages.append(ToolMessage(result, tool_call_id=call.id))

Skills are frozen in this change (see D7); the <available_skills/> XML
section is emitted as a placeholder with no names.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from annie.npc.prompts import MEMORY_CATEGORIES_BLOCK, render_identity
from annie.npc.state import AgentState, Task, TaskStatus
from annie.npc.tracing import EventType

SKIP_TASK_MARKER = "__skip__"

if TYPE_CHECKING:
    from annie.npc.sub_agents.tool_agent import ToolAgent

logger = logging.getLogger(__name__)

MAX_TOOL_LOOPS: int = 8

EXECUTOR_SYSTEM_TEMPLATE = """\
{identity}
<world_rules>
{world_rules}
</world_rules>
<situation>
{situation}
</situation>
<memory_categories>
{memory_categories}
</memory_categories>
<working_memory>
{working_memory}
</working_memory>
<available_skills>
{skills}
</available_skills>

You are acting as this NPC. Respond in-character. You may call the tools
listed in this turn's tool schema to ground your answer; when you have
everything you need, produce a final in-character reply with no further
tool calls.
"""


class Executor:
    def __init__(
        self,
        llm: BaseChatModel,
        tool_agent: "ToolAgent",
        max_loops: int = MAX_TOOL_LOOPS,
    ):
        self.llm = llm
        self.tool_agent = tool_agent
        self.max_loops = max_loops

    # ------------------------------------------------------------------
    def __call__(self, state: AgentState) -> dict:
        tracer = state.get("tracer")
        ctx = state.get("agent_context")
        tasks = state.get("tasks", [])
        budget = state.get("context_budget")
        working_memory = state.get("working_memory", "")

        span = tracer.node_span("executor") if tracer else _nullcontext()
        with span:
            all_messages: list[BaseMessage] = []
            results: list[dict[str, Any]] = []
            updated_tasks: list[Task] = []

            for task in tasks:
                task.status = TaskStatus.IN_PROGRESS
                messages = self._initial_messages(ctx, task, working_memory)
                final_ai = self._run_loop(messages, ctx, budget, tracer)

                task.status = TaskStatus.DONE
                content = _to_text(final_ai.content) if final_ai is not None else ""
                task.result = content
                updated_tasks.append(task)
                results.append({
                    "task_id": task.id,
                    "task_description": task.description,
                    "action": content,
                })
                all_messages.extend(messages)

        return {
            "tasks": updated_tasks,
            "execution_results": results,
            "messages": all_messages,
        }

    # ---- loop internals ------------------------------------------------
    def _run_loop(
        self,
        messages: list[BaseMessage],
        ctx: Any,
        budget: Any,
        tracer: Any,
    ) -> AIMessage | None:
        tool_registry = self.tool_agent.tool_registry
        tool_defs = [tool_registry.get(n) for n in tool_registry.list_tools()]
        tool_defs = [t for t in tool_defs if t is not None]
        tool_schemas = [_tool_to_schema(t) for t in tool_defs]

        try:
            llm = self.llm.bind_tools(tool_schemas) if tool_schemas else self.llm  # type: ignore[attr-defined]
        except (NotImplementedError, AttributeError):
            llm = self.llm  # StubLLM / models without bind_tools

        last_ai: AIMessage | None = None
        for step in range(self.max_loops):
            if budget is not None:
                messages[:] = budget.check(messages, self.llm)

            if tracer:
                tracer.trace(
                    "executor", EventType.LLM_CALL,
                    input_summary=f"loop step {step}, {len(messages)} msgs",
                )
            response = llm.invoke(messages)
            if not isinstance(response, AIMessage):
                response = AIMessage(content=_to_text(getattr(response, "content", response)))
            messages.append(response)
            last_ai = response

            if tracer:
                tracer.trace(
                    "executor", EventType.LLM_RESPONSE,
                    output_summary=_to_text(response.content)[:100],
                )

            tool_calls = getattr(response, "tool_calls", None) or []
            if not tool_calls:
                return response

            for call in tool_calls:
                name = call.get("name", "")
                call_id = call.get("id") or f"call_{step}_{name}"
                if tracer:
                    tracer.trace(
                        "executor", EventType.TOOL_INVOKE,
                        output_summary=f"tool={name}", metadata={"tool": name},
                    )
                result = self.tool_agent.dispatch(call, ctx)
                messages.append(ToolMessage(content=result, tool_call_id=call_id))

        logger.warning("Executor: hit MAX_TOOL_LOOPS=%d without a final answer", self.max_loops)
        return last_ai

    # ---- message assembly ----------------------------------------------
    def _initial_messages(
        self,
        ctx: Any,
        task: Task,
        working_memory: str = "",
    ) -> list[BaseMessage]:
        world_rules = getattr(ctx, "world_rules", "") or ""
        situation = getattr(ctx, "situation", "") or ""
        history = getattr(ctx, "history", "") or ""
        input_event = getattr(ctx, "input_event", "") or ""
        npc_id = getattr(ctx, "npc_id", "") or ""

        system = SystemMessage(content=EXECUTOR_SYSTEM_TEMPLATE.format(
            identity=render_identity(ctx),
            world_rules=world_rules,
            situation=situation,
            memory_categories=MEMORY_CATEGORIES_BLOCK,
            working_memory=working_memory.strip() or "(none)",
            skills="(none this run)",
        ))

        history_msgs = _history_to_messages(history, npc_id)

        if task.description == SKIP_TASK_MARKER:
            trigger_content = f"<input_event>{input_event}</input_event>"
        else:
            trigger_content = (
                f"<input_event>{input_event}</input_event>\n"
                f"<task>{task.description}</task>"
            )
        trigger = HumanMessage(content=trigger_content)
        return [system, *history_msgs, trigger]


# ----------------------------------------------------------------------
def _to_text(content: Any) -> str:
    if isinstance(content, list):
        return "".join(str(p) for p in content)
    return str(content) if content is not None else ""


def _tool_to_schema(tool: Any) -> dict:
    """Render a ToolDef as an OpenAI-function-style schema dict for bind_tools."""
    params = tool.input_schema.model_json_schema() if tool.input_schema else {
        "type": "object", "properties": {},
    }
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": params,
        },
    }


_HISTORY_LINE_RE = re.compile(r"^(\[folded\])?\[(?P<speaker>[^\]]+)\] (?P<content>.*)$")


def _history_to_messages(history: str, self_id: str) -> list[BaseMessage]:
    """Parse the engine-rendered rolling history into a message sequence.

    The DefaultWorldEngine formats each entry as ``[speaker] content`` (with an
    optional ``[folded]`` prefix). Entries whose speaker equals the NPC's own
    ``npc_id`` become AIMessage; everything else becomes HumanMessage.
    """
    if not history.strip():
        return []
    msgs: list[BaseMessage] = []
    for raw in history.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _HISTORY_LINE_RE.match(line)
        if not m:
            msgs.append(HumanMessage(content=line))
            continue
        speaker = m.group("speaker")
        content = m.group("content")
        if speaker == self_id:
            msgs.append(AIMessage(content=content))
        else:
            msgs.append(HumanMessage(content=f"{speaker}: {content}"))
    return msgs


class _nullcontext:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass

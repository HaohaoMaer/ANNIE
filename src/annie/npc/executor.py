"""Executor — native tool-use loop over AgentContext.

For each planned task, assembles an initial message list (XML-sectioned
SystemMessage + rolling history turns + current task), then runs:

    while True:
        ContextBudget.check(messages, llm)        # Emergency fold if needed
        ai = llm.bind_tools(tools).invoke(messages)
        messages.append(ai)
        if not ai.tool_calls: break               # final answer
        for call in ai.tool_calls:
            result = ToolDispatcher.dispatch(call, ctx)   # Micro-compressed
            messages.append(ToolMessage(result, tool_call_id=call.id))

Skills are exposed by the run-local SkillRuntime and activated through the
``use_skill`` built-in tool.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from typing import TYPE_CHECKING, Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    ToolMessage,
)

from annie.npc.prompts import (
    EXECUTOR_SYSTEM_PROMPT,
    build_executor_messages,
)
from annie.npc.state import AgentState, Task, TaskStatus
from annie.npc.tracing import EventType

SKIP_TASK_MARKER = "__skip__"

if TYPE_CHECKING:
    from annie.npc.runtime.tool_dispatcher import ToolDispatcher

logger = logging.getLogger(__name__)

MAX_TOOL_LOOPS: int = 8

EXECUTOR_SYSTEM_TEMPLATE = EXECUTOR_SYSTEM_PROMPT


@dataclass
class LoopResult:
    final_ai: AIMessage | None
    exhausted: bool = False
    productive_effect: bool = False
    failure_reason: str | None = None
    pending_action: bool = False


class Executor:
    def __init__(
        self,
        llm: BaseChatModel,
        tool_dispatcher: "ToolDispatcher",
        max_loops: int = MAX_TOOL_LOOPS,
    ):
        self.llm = llm
        self.tool_dispatcher = tool_dispatcher
        self.max_loops = max_loops

    # ------------------------------------------------------------------
    def __call__(self, state: AgentState) -> dict:
        tracer = state.get("tracer")
        ctx = state.get("agent_context")
        tasks = state.get("tasks", [])
        budget = state.get("context_budget")
        working_memory = state.get("working_memory", "")
        todo_text = state.get("todo_list_text", "")
        runtime = state.get("runtime", {})

        span = tracer.node_span("executor") if tracer else _nullcontext()
        with span:
            all_messages: list[BaseMessage] = []
            results: list[dict[str, Any]] = []
            updated_tasks: list[Task] = []
            prior_results: list[dict[str, Any]] = []

            for task in tasks:
                task.status = TaskStatus.IN_PROGRESS
                messages = self._initial_messages(
                    ctx,
                    task,
                    working_memory,
                    todo_text,
                    prior_results_text=_render_prior_results(prior_results),
                )
                action_results_baseline = len(runtime.get("action_results") or [])
                loop_result = self._run_loop(messages, ctx, budget, tracer, runtime)
                final_ai = loop_result.final_ai

                content = _to_text(final_ai.content) if final_ai is not None else ""
                if loop_result.exhausted:
                    task.status = TaskStatus.FAILED
                    task.result = loop_result.failure_reason or "executor reached max tool loops"
                elif not content.strip() and not loop_result.productive_effect:
                    task.status = TaskStatus.FAILED
                    task.result = "executor produced empty final answer"
                else:
                    task.status = TaskStatus.DONE
                    task.result = content
                updated_tasks.append(task)
                if task.status == TaskStatus.DONE:
                    result: dict[str, Any] = {
                        "task_id": task.id,
                        "task_description": task.description,
                        "action": content,
                    }
                    action_results = runtime.get("action_results") or []
                    task_action_results = action_results[action_results_baseline:]
                    if task_action_results:
                        result["action_results"] = [
                            r.model_dump() if hasattr(r, "model_dump") else r
                            for r in task_action_results
                        ]
                    results.append(result)
                    prior_results.append(result)
                all_messages.extend(messages)
                if loop_result.pending_action:
                    break

        return {
            "tasks": updated_tasks,
            "execution_results": results,
            "messages": all_messages,
            "runtime": runtime,
        }

    # ---- loop internals ------------------------------------------------
    def _run_loop(
        self,
        messages: list[BaseMessage],
        ctx: Any,
        budget: Any,
        tracer: Any,
        runtime: dict[str, Any],
    ) -> LoopResult:
        tool_registry = self.tool_dispatcher.tool_registry
        self.tool_dispatcher.runtime = runtime

        # Expose the running message list and tool registry to the use_skill
        # built-in so it can mutate both when activating a skill.
        prev_messages = runtime.get("messages")
        runtime["messages"] = messages
        runtime.setdefault("tool_registry", tool_registry)
        frames_before = len(getattr(tool_registry, "_frames", []))
        runtime["skill_frames"] = []

        last_ai: AIMessage | None = None
        productive_effect_baseline = _runtime_productive_effect_counts(runtime)
        pending_action_baseline = len(runtime.get("pending_action_ids") or [])
        productive_effect = False
        try:
            for step in range(self.max_loops):
                if budget is not None:
                    messages[:] = budget.check(messages, self.llm)

                # Re-read tools each iteration — a prior use_skill call may
                # have pushed a new frame whose extra_tools must now bind.
                tool_defs = [tool_registry.get(n) for n in tool_registry.list_tools()]
                tool_defs = [t for t in tool_defs if t is not None]
                tool_schemas = [_tool_to_schema(t) for t in tool_defs]
                try:
                    llm = self.llm.bind_tools(tool_schemas) if tool_schemas else self.llm  # type: ignore[attr-defined]
                except (NotImplementedError, AttributeError):
                    llm = self.llm  # StubLLM / models without bind_tools

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
                    return LoopResult(
                        final_ai=response,
                        productive_effect=(
                            productive_effect
                            or _has_runtime_productive_effect(
                                runtime,
                                productive_effect_baseline,
                            )
                        ),
                    )

                for call in tool_calls:
                    name = call.get("name", "")
                    call_id = call.get("id") or f"call_{step}_{name}"
                    if tracer:
                        tracer.trace(
                            "executor", EventType.TOOL_INVOKE,
                            output_summary=f"tool={name}", metadata={"tool": name},
                    )
                    tool = tool_registry.get(name)
                    dispatch = self.tool_dispatcher.dispatch_result(call, ctx)
                    productive_effect = (
                        productive_effect
                        or _has_runtime_productive_effect(
                            runtime,
                            productive_effect_baseline,
                        )
                    )
                    if _tool_has_productive_effect(tool, name):
                        productive_effect = True
                    messages.append(ToolMessage(content=dispatch.content, tool_call_id=call_id))
                    if len(runtime.get("pending_action_ids") or []) > pending_action_baseline:
                        return LoopResult(
                            final_ai=AIMessage(content=""),
                            productive_effect=True,
                            pending_action=True,
                        )
                    if _ends_activation_after_dispatch(dispatch):
                        return LoopResult(
                            final_ai=AIMessage(content=f"已提交动作：{name}"),
                            productive_effect=True,
                        )

            logger.warning(
                "Executor: hit MAX_TOOL_LOOPS=%d without a final answer",
                self.max_loops,
            )
            return LoopResult(
                final_ai=last_ai,
                exhausted=True,
                productive_effect=productive_effect,
                failure_reason=f"executor reached MAX_TOOL_LOOPS={self.max_loops}",
            )
        finally:
            # Pop any skill frames this task activated so their extra_tools
            # do not leak into subsequent tasks.
            for frame_id in reversed(runtime.get("skill_frames", [])):
                tool_registry.pop_frame(frame_id)
            # Safety net: if something skipped frame-id tracking, unwind any
            # residual frames pushed during this loop.
            while len(getattr(tool_registry, "_frames", [])) > frames_before:
                tool_registry.pop_frame()
            runtime["skill_frames"] = []
            if prev_messages is None:
                runtime.pop("messages", None)
            else:
                runtime["messages"] = prev_messages

    # ---- message assembly ----------------------------------------------
    def _initial_messages(
        self,
        ctx: Any,
        task: Task,
        working_memory: str = "",
        todo_text: str = "",
        prior_results_text: str = "",
    ) -> list[BaseMessage]:
        # Merge AgentContext.skills with any skills the running SkillRuntime
        # exposes via run-local state (global registry union, context wins).
        ctx_skills = list(getattr(ctx, "skills", []) or [])
        by_name = {s.name: s for s in ctx_skills}
        dispatcher_runtime = getattr(self.tool_dispatcher, "runtime", {})
        skill_runtime = dispatcher_runtime.get("skill_runtime")
        if skill_runtime is not None:
            for s in skill_runtime.skill_registry.list_skills():
                by_name.setdefault(s.name, s)
        messages = build_executor_messages(
            ctx,
            task,
            working_memory=working_memory,
            todo_text=todo_text,
            skills=list(by_name.values()),
        )
        if prior_results_text.strip():
            _append_prior_results(messages, prior_results_text)
        return messages


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


def _runtime_productive_effect_counts(runtime: dict[str, Any]) -> dict[str, int]:
    return {
        "actions": len(runtime.get("actions") or []),
        "action_results": len(runtime.get("action_results") or []),
        "memory_updates": len(runtime.get("memory_updates") or []),
        "pending_action_ids": len(runtime.get("pending_action_ids") or []),
    }


def _has_runtime_productive_effect(runtime: dict[str, Any], baseline: dict[str, int]) -> bool:
    return any(
        len(runtime.get(key) or []) > baseline.get(key, 0)
        for key in ("actions", "action_results", "memory_updates", "pending_action_ids")
    )


def _tool_has_productive_effect(tool: Any, name: str) -> bool:
    if tool is None or getattr(tool, "is_read_only", True):
        return False
    return name != "use_skill"


def _ends_activation_after_dispatch(dispatch: Any) -> bool:
    tool = getattr(dispatch, "tool", None)
    if tool is None or not getattr(tool, "ends_activation_on_success", False):
        return False
    payload = getattr(dispatch, "payload", None)
    if isinstance(payload, dict):
        return bool(payload.get("success"))
    return True


def _render_prior_results(results: list[dict[str, Any]]) -> str:
    if not results:
        return ""
    compact = [
        {
            "task_description": r.get("task_description"),
            "action": r.get("action"),
            "action_results": r.get("action_results", []),
        }
        for r in results
    ]
    return json.dumps(compact, ensure_ascii=False, default=str)


def _append_prior_results(messages: list[BaseMessage], prior_results_text: str) -> None:
    content = (
        "\n\n<prior_task_results>\n"
        "本轮中较早任务的执行结果：\n"
        f"{prior_results_text}\n"
        "</prior_task_results>"
    )
    if not messages:
        return
    messages[-1].content = _to_text(messages[-1].content) + content


class _nullcontext:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass

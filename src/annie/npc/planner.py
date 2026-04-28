"""Planner node for deciding whether an event needs multi-step execution."""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.language_models import BaseChatModel

from annie.npc.prompts import PLANNER_SYSTEM_PROMPT, build_planner_messages
from annie.npc.state import AgentState, Task, TaskStatus
from annie.npc.tracing import EventType

logger = logging.getLogger(__name__)

NPC_PLANNER_STATIC_PROMPT = PLANNER_SYSTEM_PROMPT


class Planner:
    def __init__(self, llm: BaseChatModel, static_prompt: str | None = None):
        self.llm = llm
        self._static_prompt: str = static_prompt if static_prompt is not None else NPC_PLANNER_STATIC_PROMPT

    def set_static_prompt(self, prompt: str) -> None:
        self._static_prompt = prompt

    def __call__(self, state: AgentState) -> dict:
        tracer = state.get("tracer")
        ctx = state.get("agent_context")
        input_event = state.get("input_event", "")
        working_memory = state.get("working_memory", "")
        retry_count = state.get("retry_count", 0)
        loop_reason = state.get("loop_reason", "")
        last_tasks = state.get("last_tasks", [])

        span = tracer.node_span("planner") if tracer else _nullcontext()
        with span:
            retry_context = None
            if retry_count > 0:
                prev_descs = [t.description for t in last_tasks] if last_tasks else []
                retry_context = {
                    "message": "Previous attempt produced no usable results. Revise the plan or skip.",
                    "reason": loop_reason or "unknown",
                    "previous_tasks": prev_descs,
                }

            messages = build_planner_messages(ctx, working_memory, retry_context=retry_context)
            if self._static_prompt != PLANNER_SYSTEM_PROMPT:
                messages[0].content = self._static_prompt

            if tracer:
                tracer.trace("planner", EventType.LLM_CALL, input_summary=input_event[:100])

            response = self.llm.invoke(messages)
            raw_text = _as_text(response.content)

            if tracer:
                tracer.trace("planner", EventType.LLM_RESPONSE, output_summary=raw_text[:100])

            tasks, planner_error = self._parse_output_with_error(raw_text)

            if tracer:
                tracer.trace(
                    "planner", EventType.TASK_CREATED,
                    output_summary=f"Created {len(tasks)} tasks" if tasks else "Planning skipped",
                )

        out: dict[str, Any] = {"tasks": tasks}
        if planner_error:
            out["planner_error"] = planner_error
            out["loop_reason"] = "planner parse failed"
        return out

    def _parse_output(self, raw_text: str) -> list[Task]:
        tasks, _ = self._parse_output_with_error(raw_text)
        return tasks

    def _parse_output_with_error(self, raw_text: str) -> tuple[list[Task], str | None]:
        try:
            text = raw_text.strip()
            parsed = json.loads(text.strip())
        except json.JSONDecodeError:
            logger.warning("Failed to parse planner output as JSON: %s", raw_text[:200])
            return [], "invalid JSON"

        if not isinstance(parsed, dict):
            return [], "planner output must be a JSON object"

        decision = parsed.get("decision")
        reason = parsed.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            return [], "planner output requires non-empty reason"
        if decision == "skip":
            if parsed.get("tasks") != []:
                return [], "skip decision must include empty tasks list"
            logger.debug("Planner skipped planning: %s", parsed.get("reason", ""))
            return [], None
        if decision != "plan":
            return [], "decision must be 'skip' or 'plan'"

        raw_tasks = parsed.get("tasks")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            return [], "plan decision requires non-empty tasks"
        if len(raw_tasks) > 3:
            return [], "planner returned more than 3 tasks"

        tasks: list[Task] = []
        for td in raw_tasks:
            if not isinstance(td, dict):
                return [], "task must be an object"
            description = td.get("description")
            priority = td.get("priority")
            if not isinstance(description, str) or not description.strip():
                return [], "task description must be non-empty"
            if not isinstance(priority, int) or not 0 <= priority <= 10:
                return [], "task priority must be an integer from 0 to 10"
            tasks.append(Task(
                description=description.strip(),
                priority=priority,
                status=TaskStatus.PENDING,
            ))
        return tasks, None


def _as_text(content: Any) -> str:
    if isinstance(content, list):
        return "".join(str(p) for p in content)
    return str(content) if content is not None else ""


class _nullcontext:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass

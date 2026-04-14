"""Planner — Phase 1 cleanup.

Dynamic prompt now pulled from AgentContext.character_prompt rather than
NPCProfile.personality. Phase 3 may further adjust the prompt composition.
"""

from __future__ import annotations

import json
import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from annie.npc.state import AgentState, Task, TaskStatus
from annie.npc.tracing import EventType

logger = logging.getLogger(__name__)

NPC_PLANNER_STATIC_PROMPT = """\
You are an NPC planning module. Your job is to decide whether the incoming
event needs multi-step decomposition.

DEFAULT: respond with {"skip": true, "reason": "<brief>"}.

Only return a task list when the event truly requires sequential stages
that cannot fit in a single in-character reply. Examples that warrant a
list: "先去厨房取证据再回来质询"; "连问三个人比对口供". Examples that
DO NOT: 单轮对话回应, 情绪反应, 表态, 内心活动.

Task list format (only when needed):
[{"description": "...", "priority": 0-10}]   // 最多 3 条，仅用于真正需要顺序推进的场景

Respond ONLY with valid JSON — no prose, no markdown fences.
"""


class Planner:
    def __init__(self, llm: BaseChatModel, static_prompt: str | None = None):
        self.llm = llm
        self._static_prompt: str = static_prompt if static_prompt is not None else NPC_PLANNER_STATIC_PROMPT

    def set_static_prompt(self, prompt: str) -> None:
        self._static_prompt = prompt

    def _build_dynamic_prompt(self, ctx) -> str:
        if ctx is None:
            return ""
        parts = []
        if ctx.character_prompt:
            parts.append(f"## Character\n{ctx.character_prompt}")
        if getattr(ctx, "world_rules", ""):
            parts.append(f"## World Rules\n{ctx.world_rules}")
        if getattr(ctx, "situation", ""):
            parts.append(f"## Current Situation\n{ctx.situation}")
        # NB: history is intentionally NOT rendered here. It is consumed only
        # by the Executor as a message sequence; rendering it twice would push
        # the Planner toward over-decomposition.
        return "\n\n".join(parts)

    def __call__(self, state: AgentState) -> dict:
        tracer = state.get("tracer")
        ctx = state.get("agent_context")
        input_event = state["input_event"]
        working_memory = state.get("working_memory", "")
        retry_count = state.get("retry_count", 0)
        loop_reason = state.get("loop_reason", "")
        last_tasks = state.get("last_tasks", [])

        span = tracer.node_span("planner") if tracer else _nullcontext()
        with span:
            dynamic_prompt = self._build_dynamic_prompt(ctx)
            system_prompt = self._static_prompt + ("\n\n" + dynamic_prompt if dynamic_prompt else "")

            user_content = f"Event: {input_event}\n\nWorking memory (pre-retrieved):\n{working_memory or '(none)'}"
            if retry_count > 0:
                prev_descs = [t.description for t in last_tasks] if last_tasks else []
                user_content += (
                    "\n\n<retry_context>\n"
                    "Previous attempt produced no usable results.\n"
                    f"Reason: {loop_reason or 'unknown'}\n"
                    f"Previous tasks: {json.dumps(prev_descs, ensure_ascii=False)}\n"
                    "Revise the plan or skip.\n"
                    "</retry_context>"
                )

            messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_content)]

            if tracer:
                tracer.trace("planner", EventType.LLM_CALL, input_summary=input_event[:100])

            response = self.llm.invoke(messages)
            raw_text = response.content

            if tracer:
                tracer.trace("planner", EventType.LLM_RESPONSE, output_summary=raw_text[:100])

            tasks = self._parse_output(raw_text)

            if tracer:
                tracer.trace(
                    "planner", EventType.TASK_CREATED,
                    output_summary=f"Created {len(tasks)} tasks" if tasks else "Planning skipped",
                )

        return {"tasks": tasks}

    def _parse_output(self, raw_text: str) -> list[Task]:
        try:
            text = raw_text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                text = text.rsplit("```", 1)[0]
            parsed = json.loads(text.strip())
            if isinstance(parsed, dict) and parsed.get("skip"):
                logger.debug("Planner skipped planning: %s", parsed.get("reason", ""))
                return []
            if not isinstance(parsed, list):
                parsed = [parsed]
        except (json.JSONDecodeError, IndexError):
            logger.warning("Failed to parse planner output as JSON: %s", raw_text[:200])
            return [Task(description=raw_text.strip(), priority=5)]

        tasks = []
        for td in parsed:
            tasks.append(Task(
                description=td.get("description", str(td)),
                priority=td.get("priority", 5),
                status=TaskStatus.PENDING,
            ))
        return tasks


class _nullcontext:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass

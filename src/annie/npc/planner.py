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
You are an NPC planning module. Your job is to analyze an incoming event and decide
whether it requires a multi-step plan or can be handled directly.

Choose ONE of these two response formats:

Option A — Create a task plan (for complex events requiring multiple steps):
[
  {"description": "clear actionable step", "priority": 8},
  {"description": "another step", "priority": 6}
]
1-5 tasks, priority 0-10 (higher = more important).

Option B — Skip planning (for simple, single-step events):
{"skip": true, "reason": "brief explanation of why no planning needed"}

Use Option B when: the event requires a single obvious response, is purely reactive,
or is straightforward enough to handle without decomposition.
Use Option A when: the event involves gathering information from multiple sources,
requires analysis before action, or has multiple distinct phases.

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
        if getattr(ctx, "history", ""):
            parts.append(f"## Recent History\n{ctx.history}")
        return "\n\n".join(parts)

    def __call__(self, state: AgentState) -> dict:
        tracer = state.get("tracer")
        ctx = state.get("agent_context")
        input_event = state["input_event"]
        memory_context = state.get("memory_context", "")

        span = tracer.node_span("planner") if tracer else _nullcontext()
        with span:
            dynamic_prompt = self._build_dynamic_prompt(ctx)
            system_prompt = self._static_prompt + ("\n\n" + dynamic_prompt if dynamic_prompt else "")

            user_content = f"Event: {input_event}"
            if memory_context:
                user_content += f"\n\nMemory context:\n{memory_context}"

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

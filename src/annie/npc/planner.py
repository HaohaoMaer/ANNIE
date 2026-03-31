"""Planner - Decomposes incoming events/interactions into actionable tasks.

LangGraph node function that takes AgentState and returns a partial state
update with the generated task list.
"""

from __future__ import annotations

import json
import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from annie.npc.state import AgentState, Task, TaskStatus
from annie.npc.tracing import EventType

logger = logging.getLogger(__name__)

PLANNER_SYSTEM_PROMPT = """\
You are the planning module for an NPC named {name}.

Personality: {traits}
Values: {values}
Short-term goals: {short_term_goals}
Long-term goals: {long_term_goals}

Your job is to analyze an incoming event and decompose it into 1-5 concrete tasks
that this NPC should perform in response. Consider the NPC's personality, goals,
and any available memory context.

Respond ONLY with a JSON array of task objects. Each task has:
- "description": a clear, actionable description of what to do
- "priority": an integer 0-10 (higher = more important)

Example response:
[
  {{"description": "Observe the stranger's appearance and demeanor", "priority": 8}},
  {{"description": "Recall any past encounters with travelers", "priority": 6}}
]
"""


class Planner:
    """Decomposes events into tasks using LLM reasoning."""

    def __init__(self, llm: BaseChatModel):
        self.llm = llm

    def __call__(self, state: AgentState) -> dict:
        """LangGraph node function. Returns partial state with tasks."""
        tracer = state.get("tracer")
        npc = state["npc_profile"]
        input_event = state["input_event"]
        memory_context = state.get("memory_context", "")

        span = tracer.node_span("planner") if tracer else _nullcontext()
        with span:
            system_prompt = PLANNER_SYSTEM_PROMPT.format(
                name=npc.name,
                traits=", ".join(npc.personality.traits),
                values=", ".join(npc.personality.values),
                short_term_goals=", ".join(npc.goals.short_term) or "none",
                long_term_goals=", ".join(npc.goals.long_term) or "none",
            )

            user_content = f"Event: {input_event}"
            if memory_context:
                user_content += f"\n\nMemory context:\n{memory_context}"

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_content),
            ]

            if tracer:
                tracer.trace(
                    "planner",
                    EventType.LLM_CALL,
                    input_summary=input_event[:100],
                )

            response = self.llm.invoke(messages)
            raw_text = response.content

            if tracer:
                tracer.trace(
                    "planner",
                    EventType.LLM_RESPONSE,
                    output_summary=raw_text[:100],
                )

            tasks = self._parse_tasks(raw_text)

            if tracer:
                tracer.trace(
                    "planner",
                    EventType.TASK_CREATED,
                    output_summary=f"Created {len(tasks)} tasks",
                )

        return {"tasks": tasks}

    def _parse_tasks(self, raw_text: str) -> list[Task]:
        """Parse LLM output into Task objects."""
        try:
            # Extract JSON from the response (handle markdown code blocks)
            text = raw_text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                text = text.rsplit("```", 1)[0]
            task_dicts = json.loads(text)
            if not isinstance(task_dicts, list):
                task_dicts = [task_dicts]
        except (json.JSONDecodeError, IndexError):
            logger.warning("Failed to parse planner output as JSON: %s", raw_text[:200])
            return [Task(description=raw_text.strip(), priority=5)]

        tasks = []
        for td in task_dicts:
            tasks.append(
                Task(
                    description=td.get("description", str(td)),
                    priority=td.get("priority", 5),
                    status=TaskStatus.PENDING,
                )
            )
        return tasks


class _nullcontext:
    """Minimal no-op context manager for when tracer is None."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

"""Executor - Carries out planned tasks via memory lookup, skills, tools, and LLM.

LangGraph node function that processes each task from the Planner,
gathering context and generating actions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from annie.npc.state import AgentState, TaskStatus
from annie.npc.sub_agents.memory_agent import MemoryAgent
from annie.npc.tracing import EventType

if TYPE_CHECKING:
    from annie.npc.sub_agents.skill_agent import SkillAgent
    from annie.npc.sub_agents.tool_agent import ToolAgent
    from annie.social_graph.event_log import SocialEventLog

logger = logging.getLogger(__name__)

EXECUTOR_SYSTEM_PROMPT = """\
You are the execution module for an NPC named {name}.

Personality: {traits}
Values: {values}

You are given a task to carry out. Use the provided memory context to inform
your actions. Respond with a concise description of what the NPC does, says,
or decides. Stay in character.
"""


class Executor:
    """Processes tasks one by one, querying memory and optionally invoking skills and tools."""

    def __init__(
        self,
        llm: BaseChatModel,
        memory_agent: MemoryAgent,
        skill_agent: SkillAgent | None = None,
        tool_agent: ToolAgent | None = None,
        event_log: SocialEventLog | None = None,
        all_npc_names: list[str] | None = None,
    ):
        self.llm = llm
        self.memory_agent = memory_agent
        self.skill_agent = skill_agent
        self.tool_agent = tool_agent
        self._event_log = event_log
        self._all_npc_names = all_npc_names or []

    def __call__(self, state: AgentState) -> dict:
        """LangGraph node function. Returns partial state with execution results."""
        tracer = state.get("tracer")
        npc = state["npc_profile"]
        tasks = state.get("tasks", [])

        span = tracer.node_span("executor") if tracer else _nullcontext()
        with span:
            system_prompt = EXECUTOR_SYSTEM_PROMPT.format(
                name=npc.name,
                traits=", ".join(npc.personality.traits),
                values=", ".join(npc.personality.values),
            )

            results = []
            updated_tasks = []

            for task in tasks:
                task.status = TaskStatus.IN_PROGRESS

                # Retrieve memory context for this task
                if tracer:
                    tracer.trace(
                        "executor",
                        EventType.MEMORY_READ,
                        input_summary=task.description[:80],
                    )
                memory_context = self.memory_agent.build_context(task.description)

                # Check if a skill matches
                skill_output = None
                if self.skill_agent:
                    skill_output = self.skill_agent.try_skill(task.description, npc, tracer)

                # Check if a tool can help
                tool_output = None
                if self.tool_agent:
                    tool_output = self.tool_agent.try_tool(task.description, npc.name, tracer)

                # Build the user prompt
                user_content = f"Task: {task.description}\n\nMemory context:\n{memory_context}"
                if skill_output:
                    user_content += f"\n\nSkill output:\n{skill_output}"
                if tool_output:
                    user_content += f"\n\nTool output:\n{tool_output}"

                if tracer:
                    tracer.trace(
                        "executor",
                        EventType.LLM_CALL,
                        input_summary=task.description[:80],
                    )

                messages = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_content),
                ]
                response = self.llm.invoke(messages)

                if tracer:
                    tracer.trace(
                        "executor",
                        EventType.LLM_RESPONSE,
                        output_summary=response.content[:100],
                    )

                task.status = TaskStatus.DONE
                task.result = response.content
                updated_tasks.append(task)
                result_entry = {
                    "task_id": task.id,
                    "task_description": task.description,
                    "action": response.content,
                }
                results.append(result_entry)

                # Phase 2: log social events when actions involve other NPCs.
                self._maybe_log_social_event(npc, task.description, response.content)

        return {"tasks": updated_tasks, "execution_results": results}


    def _maybe_log_social_event(self, npc, task_desc: str, action: str) -> None:
        """If the action mentions another NPC, log a SocialEvent."""
        if self._event_log is None:
            return

        # Detect mentioned NPCs by name matching.
        mentioned = [
            name for name in self._all_npc_names
            if name != npc.name and name.lower() in action.lower()
        ]
        if not mentioned:
            return

        from annie.social_graph.models import EventVisibility, SocialEvent

        evt = SocialEvent(
            actor=npc.name,
            target=mentioned[0],
            action=task_desc[:80],
            description=action[:300],
            witnesses=mentioned[1:],
            visibility=EventVisibility.WITNESSED,
        )
        self._event_log.append(evt)


class _nullcontext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

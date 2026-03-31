"""Executor - Carries out planned tasks via memory lookup, skills, and LLM.

LangGraph node function that processes each task from the Planner,
gathering context and generating actions.
"""

from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from annie.npc.skills.base_skill import SkillRegistry
from annie.npc.state import AgentState, TaskStatus
from annie.npc.sub_agents.memory_agent import MemoryAgent
from annie.npc.tracing import EventType

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
    """Processes tasks one by one, querying memory and optionally invoking skills."""

    def __init__(
        self,
        llm: BaseChatModel,
        memory_agent: MemoryAgent,
        skill_registry: SkillRegistry | None = None,
    ):
        self.llm = llm
        self.memory_agent = memory_agent
        self.skill_registry = skill_registry

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
                if self.skill_registry:
                    skill_output = self._try_skill(task.description, npc, tracer)

                # Build the user prompt
                user_content = f"Task: {task.description}\n\nMemory context:\n{memory_context}"
                if skill_output:
                    user_content += f"\n\nSkill output:\n{skill_output}"

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
                results.append(
                    {
                        "task_id": task.id,
                        "task_description": task.description,
                        "action": response.content,
                    }
                )

        return {"tasks": updated_tasks, "execution_results": results}

    def _try_skill(self, task_description: str, npc, tracer) -> str | None:
        """Try to find and invoke a matching skill for the task."""
        if not self.skill_registry:
            return None

        descs = self.skill_registry.get_descriptions()
        # Simple keyword matching - find the first skill whose description
        # shares significant words with the task
        best_skill = None
        best_overlap = 0
        task_words = set(task_description.lower().split())
        for name, desc in descs.items():
            desc_words = set(desc.lower().split())
            overlap = len(task_words & desc_words)
            if overlap > best_overlap:
                best_overlap = overlap
                best_skill = name

        if best_skill and best_overlap >= 2:
            skill = self.skill_registry.get(best_skill)
            if skill:
                if tracer:
                    tracer.trace(
                        "executor",
                        EventType.SKILL_INVOKE,
                        output_summary=f"skill={best_skill}",
                        metadata={"skill": best_skill},
                    )
                try:
                    result = skill.execute({"task": task_description, "npc_name": npc.name})
                    return str(result) if result else None
                except Exception as e:
                    logger.warning("Skill '%s' failed: %s", best_skill, e)
        return None


class _nullcontext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

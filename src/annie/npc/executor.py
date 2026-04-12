"""Executor — Phase 1 cleanup.

social_graph / cognitive dependencies removed. Full ToolDef-aware rewrite
lands in Phase 3 (see openspec/changes/decouple-npc-world-engine/tasks.md).
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

logger = logging.getLogger(__name__)

EXECUTOR_SYSTEM_PROMPT = """\
You are the execution module for an NPC named {name}.

{character_prompt}

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
    ):
        self.llm = llm
        self.memory_agent = memory_agent
        self.skill_agent = skill_agent
        self.tool_agent = tool_agent

    def __call__(self, state: AgentState) -> dict:
        tracer = state.get("tracer")
        ctx = state.get("agent_context")
        npc_name = ctx.npc_id if ctx is not None else "npc"
        character_prompt = ctx.character_prompt if ctx is not None else ""
        tasks = state.get("tasks", [])

        span = tracer.node_span("executor") if tracer else _nullcontext()
        with span:
            system_prompt = EXECUTOR_SYSTEM_PROMPT.format(
                name=npc_name, character_prompt=character_prompt,
            )

            results = []
            updated_tasks = []

            for task in tasks:
                task.status = TaskStatus.IN_PROGRESS

                if tracer:
                    tracer.trace("executor", EventType.MEMORY_READ, input_summary=task.description[:80])
                memory_context = self.memory_agent.build_context(task.description)

                skill_output = None
                if self.skill_agent:
                    skill_output = self.skill_agent.try_skill(task.description, npc_name, tracer)

                tool_output = None
                if self.tool_agent:
                    tool_output = self.tool_agent.try_tool(task.description, npc_name, tracer)

                user_content = f"Task: {task.description}\n\nMemory context:\n{memory_context}"
                if skill_output:
                    user_content += f"\n\nSkill output:\n{skill_output}"
                if tool_output:
                    user_content += f"\n\nTool output:\n{tool_output}"

                if tracer:
                    tracer.trace("executor", EventType.LLM_CALL, input_summary=task.description[:80])

                messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_content)]
                response = self.llm.invoke(messages)

                if tracer:
                    tracer.trace("executor", EventType.LLM_RESPONSE, output_summary=response.content[:100])

                task.status = TaskStatus.DONE
                task.result = response.content
                updated_tasks.append(task)
                results.append({
                    "task_id": task.id,
                    "task_description": task.description,
                    "action": response.content,
                })

        return {"tasks": updated_tasks, "execution_results": results}


class _nullcontext:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass

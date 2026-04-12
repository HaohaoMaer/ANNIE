"""Reflector — Phase 1 cleanup.

social_graph / belief_system coupling removed. Reflection writes go through
MemoryInterface (wired in Phase 3).
"""

from __future__ import annotations

import json
import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from annie.npc.state import AgentState
from annie.npc.sub_agents.memory_agent import MemoryAgent
from annie.npc.tracing import EventType

logger = logging.getLogger(__name__)

NPC_REFLECTOR_STATIC_PROMPT = """\
You are an NPC reflection module. Review the actions just taken and generate a brief reflection.

Consider:
1. What happened and what was the outcome?
2. What did the NPC learn from this experience?
3. How does this affect the NPC's goals or relationships with other characters?

Respond with:
REFLECTION: <2-4 sentence reflection from the NPC's perspective>
FACTS: ["new fact learned", "another fact"]
RELATIONSHIP_NOTES: [{"person": "Name", "observation": "text"}]
"""


class Reflector:
    """Reviews execution results, generates reflection, writes memory."""

    def __init__(
        self,
        llm: BaseChatModel,
        memory_agent: MemoryAgent,
        static_prompt: str | None = None,
    ):
        self.llm = llm
        self.memory_agent = memory_agent
        self._static_prompt = static_prompt if static_prompt is not None else NPC_REFLECTOR_STATIC_PROMPT

    def set_static_prompt(self, prompt: str) -> None:
        self._static_prompt = prompt

    def __call__(self, state: AgentState) -> dict:
        tracer = state.get("tracer")
        ctx = state.get("agent_context")
        npc_name = ctx.npc_id if ctx is not None else "npc"
        character_prompt = ctx.character_prompt if ctx is not None else ""
        results = state.get("execution_results", [])
        input_event = state.get("input_event", "")

        span = tracer.node_span("reflector") if tracer else _nullcontext()
        with span:
            system_prompt = self._static_prompt + f"\n\n## NPC Identity\nName: {npc_name}\n{character_prompt}"

            actions_summary = "\n".join(
                f"- Task: {r['task_description']}\n  Action: {r['action']}" for r in results
            )
            user_content = f"Original event: {input_event}\n\nActions taken:\n{actions_summary}"

            if tracer:
                tracer.trace(
                    "reflector", EventType.LLM_CALL,
                    input_summary=f"{len(results)} actions to reflect on",
                )

            messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_content)]
            response = self.llm.invoke(messages)
            raw = response.content

            if tracer:
                tracer.trace("reflector", EventType.LLM_RESPONSE, output_summary=raw[:100])

            reflection, facts, rel_notes = self._parse_response(raw)

            episode = f"Event: {input_event}. Reflection: {reflection}"
            self.memory_agent.store_episodic(episode)
            if tracer:
                tracer.trace("reflector", EventType.MEMORY_WRITE, output_summary="stored episodic memory")

            for fact in facts:
                self.memory_agent.store_semantic(fact, category="learned")
            if facts and tracer:
                tracer.trace(
                    "reflector", EventType.MEMORY_WRITE,
                    output_summary=f"stored {len(facts)} semantic facts",
                )

            for note in rel_notes:
                person = note.get("person", "")
                obs = note.get("observation", "")
                if person and obs:
                    self.memory_agent.store_relationship_note(person, obs)
            if rel_notes and tracer:
                tracer.trace(
                    "reflector", EventType.MEMORY_WRITE,
                    output_summary=f"stored {len(rel_notes)} relationship notes",
                )

        return {"reflection": reflection}

    def _parse_response(self, raw: str) -> tuple[str, list[str], list[dict]]:
        reflection = raw
        facts: list[str] = []
        rel_notes: list[dict] = []

        if "REFLECTION:" in raw:
            parts = raw.split("REFLECTION:", 1)[1]
            section = parts
            if "FACTS:" in parts:
                reflection_part, rest = parts.split("FACTS:", 1)
                reflection = reflection_part.strip()
                if "RELATIONSHIP_NOTES:" in rest:
                    facts_part, rel_part = rest.split("RELATIONSHIP_NOTES:", 1)
                else:
                    facts_part, rel_part = rest, ""
                try:
                    facts = json.loads(facts_part.strip())
                    if not isinstance(facts, list):
                        facts = []
                except (json.JSONDecodeError, ValueError):
                    facts = []
                if rel_part.strip():
                    try:
                        rel_notes = json.loads(rel_part.strip())
                        if not isinstance(rel_notes, list):
                            rel_notes = []
                    except (json.JSONDecodeError, ValueError):
                        rel_notes = []
            else:
                reflection = section.strip()

        return reflection, facts, rel_notes


class _nullcontext:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass

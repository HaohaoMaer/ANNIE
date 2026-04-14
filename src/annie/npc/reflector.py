"""Reflector — Phase 1 cleanup.

Reflection writes go through
MemoryInterface (wired in Phase 3).
"""

from __future__ import annotations

import json
import logging
import re

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from annie.npc.prompts import render_identity
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
        results = state.get("execution_results", [])
        input_event = state.get("input_event", "")

        span = tracer.node_span("reflector") if tracer else _nullcontext()
        with span:
            system_prompt = self._static_prompt + "\n\n" + render_identity(ctx)

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
            self.memory_agent.store_reflection(episode)
            if tracer:
                tracer.trace("reflector", EventType.MEMORY_WRITE, output_summary="stored reflection memory")

            for fact in facts:
                self.memory_agent.store_semantic(fact)
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
                facts = _parse_list(facts_part)
                rel_notes = _parse_rel_notes(rel_part)
            else:
                reflection = section.strip()

        return reflection, facts, rel_notes


_BULLET_PREFIX_RE = re.compile(r"^\s*(?:[-*•]\s+|\d+[.)]\s+)")


def _parse_list(raw: str) -> list[str]:
    """Tolerant list parser: JSON array → bullet lines → []."""
    text = raw.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    except (json.JSONDecodeError, ValueError):
        pass
    items: list[str] = []
    for line in text.splitlines():
        stripped = _BULLET_PREFIX_RE.sub("", line).strip()
        if stripped:
            items.append(stripped)
    return items


def _parse_rel_notes(raw: str) -> list[dict]:
    """Tolerant parse for RELATIONSHIP_NOTES.

    JSON list of dicts preferred; otherwise try JSON list of strings or bullet
    list (each becomes ``{"person": "", "observation": item}`` — the empty
    person makes them fall through Reflector's write guard).
    """
    text = raw.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        parsed = None
    if isinstance(parsed, list):
        out: list[dict] = []
        for item in parsed:
            if isinstance(item, dict):
                out.append(item)
            else:
                out.append({"person": "", "observation": str(item)})
        return out
    # Bullet fallback.
    return [{"person": "", "observation": s} for s in _parse_list(text)]


class _nullcontext:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass

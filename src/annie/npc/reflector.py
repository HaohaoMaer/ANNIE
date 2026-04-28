"""Reflector — produces declarative reflection and memory-update intents."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.language_models import BaseChatModel

from annie.npc.prompts import REFLECTOR_SYSTEM_PROMPT, build_reflector_messages
from annie.npc.response import MemoryUpdate
from annie.npc.state import AgentState
from annie.npc.tracing import EventType

logger = logging.getLogger(__name__)

NPC_REFLECTOR_STATIC_PROMPT = REFLECTOR_SYSTEM_PROMPT


class Reflector:
    """Reviews execution results and generates memory updates without persisting."""

    def __init__(
        self,
        llm: BaseChatModel,
        static_prompt: str | None = None,
    ):
        self.llm = llm
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
            if tracer:
                tracer.trace(
                    "reflector", EventType.LLM_CALL,
                    input_summary=f"{len(results)} actions to reflect on",
                )

            messages = build_reflector_messages(ctx, input_event, results)
            if self._static_prompt != REFLECTOR_SYSTEM_PROMPT:
                messages[0].content = self._static_prompt
            response = self.llm.invoke(messages)
            raw = _as_text(response.content)

            if tracer:
                tracer.trace("reflector", EventType.LLM_RESPONSE, output_summary=raw[:100])

            reflection, facts, rel_notes = self._parse_response(raw)

            episode = f"Event: {input_event}. Reflection: {reflection}"
            memory_updates = [
                MemoryUpdate(content=episode, type="reflection", metadata={}),
            ]
            for fact in facts:
                memory_updates.append(MemoryUpdate(content=fact, type="semantic", metadata={}))

            for note in rel_notes:
                person = note.get("person", "")
                obs = note.get("observation", "")
                if person and obs:
                    memory_updates.append(
                        MemoryUpdate(content=obs, type="reflection", metadata={"person": person}),
                    )
            if memory_updates and tracer:
                tracer.trace(
                    "reflector", EventType.MEMORY_WRITE,
                    output_summary=f"declared {len(memory_updates)} memory updates",
                )

        return {"reflection": reflection, "memory_updates": memory_updates}

    def _parse_response(self, raw: str) -> tuple[str, list[str], list[dict]]:
        try:
            parsed = json.loads(raw.strip())
        except json.JSONDecodeError:
            logger.warning("Failed to parse reflector output as JSON: %s", raw[:200])
            return _legacy_reflection_text(raw), [], []

        if not isinstance(parsed, dict):
            return raw, [], []

        reflection = parsed.get("reflection")
        facts = parsed.get("facts", [])
        rel_notes = parsed.get("relationship_notes", [])
        if not isinstance(reflection, str) or not reflection.strip():
            return raw, [], []
        if not isinstance(facts, list):
            facts = []
        if not isinstance(rel_notes, list):
            rel_notes = []
        clean_facts = [str(f).strip() for f in facts if str(f).strip()]
        clean_notes = [
            n for n in rel_notes
            if isinstance(n, dict)
            and isinstance(n.get("person"), str)
            and isinstance(n.get("observation"), str)
        ]
        return reflection.strip(), clean_facts, clean_notes


def _legacy_reflection_text(raw: str) -> str:
    if "REFLECTION:" not in raw:
        return raw
    part = raw.split("REFLECTION:", 1)[1]
    for marker in ("FACTS:", "RELATIONSHIP_NOTES:"):
        if marker in part:
            part = part.split(marker, 1)[0]
    return part.strip() or raw


def _as_text(content: Any) -> str:
    if isinstance(content, list):
        return "".join(str(p) for p in content)
    return str(content) if content is not None else ""


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

"""Reflector - Updates memory and generates reflections after execution.

LangGraph node function that reviews execution results, generates insights,
and stores new memories.
"""

from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from typing import TYPE_CHECKING

from annie.npc.state import AgentState
from annie.npc.sub_agents.memory_agent import MemoryAgent
from annie.npc.tracing import EventType

if TYPE_CHECKING:
    from annie.social_graph.graph import SocialGraph

logger = logging.getLogger(__name__)

REFLECTOR_SYSTEM_PROMPT = """\
You are the reflection module for an NPC named {name}.

Personality: {traits}
Values: {values}

Review the actions that were just taken and generate a brief reflection.
Consider:
1. What happened and what was the outcome?
2. What did {name} learn from this experience?
3. How does this affect {name}'s goals or relationships?

Respond with a concise reflection (2-4 sentences) from {name}'s perspective.
Also list any new facts learned, as a JSON array of strings under the key "facts".
{relationship_update_section}
Format your response as:
REFLECTION: <your reflection text>
FACTS: ["fact 1", "fact 2"]{relationship_update_format}
"""

_RELATIONSHIP_UPDATE_SECTION = """
If any relationships changed as a result of these events, list the changes.
Each change should specify a target NPC, a field (trust, emotional_valence,
intensity, or familiarity), a delta (positive or negative float), and a reason.
"""

_RELATIONSHIP_UPDATE_FORMAT = """
RELATIONSHIP_UPDATES: [{"target": "NPC Name", "field": "trust", "delta": 0.1, "reason": "They helped me"}]"""


class Reflector:
    """Reviews execution results, generates reflection, and stores memories."""

    def __init__(
        self,
        llm: BaseChatModel,
        memory_agent: MemoryAgent,
        social_graph: SocialGraph | None = None,
    ):
        self.llm = llm
        self.memory_agent = memory_agent
        self._social_graph = social_graph

    def __call__(self, state: AgentState) -> dict:
        """LangGraph node function. Returns partial state with reflection."""
        tracer = state.get("tracer")
        npc = state["npc_profile"]
        results = state.get("execution_results", [])
        input_event = state.get("input_event", "")

        span = tracer.node_span("reflector") if tracer else _nullcontext()
        with span:
            has_graph = self._social_graph is not None
            system_prompt = REFLECTOR_SYSTEM_PROMPT.format(
                name=npc.name,
                traits=", ".join(npc.personality.traits),
                values=", ".join(npc.personality.values),
                relationship_update_section=_RELATIONSHIP_UPDATE_SECTION if has_graph else "",
                relationship_update_format=_RELATIONSHIP_UPDATE_FORMAT if has_graph else "",
            )

            actions_summary = "\n".join(
                f"- Task: {r['task_description']}\n  Action: {r['action']}" for r in results
            )
            user_content = f"Original event: {input_event}\n\nActions taken:\n{actions_summary}"

            if tracer:
                tracer.trace(
                    "reflector",
                    EventType.LLM_CALL,
                    input_summary=f"{len(results)} actions to reflect on",
                )

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_content),
            ]
            response = self.llm.invoke(messages)
            raw = response.content

            if tracer:
                tracer.trace(
                    "reflector",
                    EventType.LLM_RESPONSE,
                    output_summary=raw[:100],
                )

            # Parse reflection and facts
            reflection, facts = self._parse_response(raw)

            # Store the event as an episodic memory
            episode = f"Event: {input_event}. Reflection: {reflection}"
            self.memory_agent.store_episodic(episode)
            if tracer:
                tracer.trace(
                    "reflector",
                    EventType.MEMORY_WRITE,
                    output_summary="stored episodic memory",
                )

            # Store any new facts as semantic memories
            for fact in facts:
                self.memory_agent.store_semantic(fact, category="learned")
            if facts and tracer:
                tracer.trace(
                    "reflector",
                    EventType.MEMORY_WRITE,
                    output_summary=f"stored {len(facts)} semantic facts",
                )

            # Phase 2: apply relationship updates to SocialGraph.
            if self._social_graph is not None:
                rel_updates = self._parse_relationship_updates(raw, npc.name)
                if rel_updates:
                    self._social_graph.apply_deltas(rel_updates)
                    if tracer:
                        tracer.trace(
                            "reflector",
                            EventType.MEMORY_WRITE,
                            output_summary=f"applied {len(rel_updates)} relationship deltas",
                        )

        return {"reflection": reflection}

    def _parse_response(self, raw: str) -> tuple[str, list[str]]:
        """Parse the LLM reflection response into reflection text and facts."""
        reflection = raw
        facts: list[str] = []

        if "REFLECTION:" in raw:
            parts = raw.split("REFLECTION:", 1)[1]
            if "FACTS:" in parts:
                reflection_part, facts_part = parts.split("FACTS:", 1)
                reflection = reflection_part.strip()
                try:
                    import json

                    facts = json.loads(facts_part.strip())
                    if not isinstance(facts, list):
                        facts = []
                except (json.JSONDecodeError, ValueError):
                    facts = []
            else:
                reflection = parts.strip()

        return reflection, facts

    @staticmethod
    def _parse_relationship_updates(raw: str, npc_name: str) -> list:
        """Parse RELATIONSHIP_UPDATES from the LLM response into GraphDeltas."""
        if "RELATIONSHIP_UPDATES:" not in raw:
            return []
        try:
            import json

            from annie.social_graph.models import GraphDelta

            parts = raw.split("RELATIONSHIP_UPDATES:", 1)[1].strip()
            bracket_depth = 0
            end_idx = 0
            for i, ch in enumerate(parts):
                if ch == "[":
                    bracket_depth += 1
                elif ch == "]":
                    bracket_depth -= 1
                    if bracket_depth == 0:
                        end_idx = i + 1
                        break
            if end_idx == 0:
                return []
            updates_raw = json.loads(parts[:end_idx])
            if not isinstance(updates_raw, list):
                return []

            deltas = []
            for u in updates_raw:
                if not isinstance(u, dict):
                    continue
                target = u.get("target", "")
                field = u.get("field", "")
                delta = u.get("delta", 0)
                reason = u.get("reason", "")
                if target and field and delta:
                    deltas.append(GraphDelta(
                        source=npc_name, target=target,
                        field=field, delta=float(delta), reason=reason,
                    ))
            return deltas
        except (json.JSONDecodeError, ValueError):
            return []


class _nullcontext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

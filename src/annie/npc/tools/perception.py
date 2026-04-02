"""Perception Tool - Structures environmental input into categorized observations."""

from __future__ import annotations

import re

from annie.npc.tools.base_tool import BaseTool


class PerceptionTool(BaseTool):
    """Parses event text into structured environmental observations.

    In Phase 1 this is a heuristic text parser. Future phases may
    integrate with the World Engine's SceneManager for richer data.
    """

    name = "perception"
    description = "Structures environmental input into categorized observations (entities, environment, threat level)."

    # Simple keyword sets for heuristic classification
    _THREAT_WORDS = frozenset(
        {"attack", "danger", "threat", "hostile", "weapon", "fight", "enemy", "bandit", "wolf"}
    )
    _ENTITY_PATTERNS = re.compile(
        r"\b(stranger|traveler|merchant|villager|guard|elder|child|woman|man|warrior|knight)\b",
        re.IGNORECASE,
    )

    def execute(self, context: dict) -> dict:
        task = context.get("task", "")
        event = context.get("event", task)
        text = f"{task} {event}".lower()

        # Extract entities
        entities = list({m.group(0).lower() for m in self._ENTITY_PATTERNS.finditer(text)})

        # Determine threat level
        threat_count = sum(1 for w in self._THREAT_WORDS if w in text)
        if threat_count >= 2:
            threat_level = "high"
        elif threat_count >= 1:
            threat_level = "medium"
        else:
            threat_level = "low"

        return {
            "tool": self.name,
            "entities": entities,
            "environment": task,
            "threat_level": threat_level,
        }

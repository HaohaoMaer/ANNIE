"""Skill Agent - Selects and invokes skills from the skill registry."""

from __future__ import annotations

import logging
from typing import Any

from annie.npc.skills.base_skill import SkillRegistry
from annie.npc.state import NPCProfile
from annie.npc.tracing import EventType

logger = logging.getLogger(__name__)

# Common stop words filtered out during keyword matching
_STOP_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "and",
        "but",
        "or",
        "nor",
        "not",
        "so",
        "yet",
        "both",
        "either",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "i",
        "you",
        "he",
        "she",
        "we",
        "they",
        "me",
        "him",
        "her",
        "us",
        "them",
        "my",
        "your",
    }
)


def _meaningful_words(text: str) -> set[str]:
    """Extract meaningful (non-stop) words from text, stripping punctuation."""
    import re

    words = re.findall(r"[a-z]+", text.lower())
    return {w for w in words if w not in _STOP_WORDS and len(w) > 2}


class SkillAgent:
    """Selects and invokes the best matching skill for a task."""

    def __init__(self, skill_registry: SkillRegistry):
        self.skill_registry = skill_registry

    def select_skill(self, task_description: str) -> str | None:
        """Return the name of the best-matching skill, or None."""
        descs = self.skill_registry.get_descriptions()
        if not descs:
            return None

        task_words = _meaningful_words(task_description)
        if not task_words:
            return None

        best_skill = None
        best_overlap = 0

        for name, desc in descs.items():
            desc_words = _meaningful_words(desc)
            overlap = len(task_words & desc_words)
            if overlap > best_overlap:
                best_overlap = overlap
                best_skill = name

        return best_skill if best_skill and best_overlap >= 2 else None

    def invoke(self, skill_name: str, context: dict, npc: NPCProfile) -> dict:
        """Execute the named skill and return its output."""
        skill = self.skill_registry.get(skill_name)
        if not skill:
            return {}
        try:
            return skill.execute(context)
        except Exception as e:
            logger.warning("Skill '%s' failed: %s", skill_name, e)
            return {}

    def try_skill(
        self,
        task_description: str,
        npc: NPCProfile,
        tracer: Any | None = None,
    ) -> str | None:
        """Select + invoke a skill, returning the result string or None."""
        skill_name = self.select_skill(task_description)
        if not skill_name:
            return None

        if tracer:
            tracer.trace(
                "skill_agent",
                EventType.SKILL_INVOKE,
                output_summary=f"skill={skill_name}",
                metadata={"skill": skill_name},
            )

        result = self.invoke(
            skill_name,
            {"task": task_description, "npc_name": npc.name},
            npc,
        )
        return str(result) if result else None

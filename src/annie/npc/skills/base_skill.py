"""SkillDef — manifest for a prompt + extra-tools bundle.

Skills are *not* LLM-callable tools. They are activated through the built-in
``use_skill(skill_name, args)`` tool, which appends ``skill.prompt`` as a
SystemMessage and temporarily unlocks ``skill.extra_tools`` in the current
Executor tool loop. ``one_line`` is the only detail surfaced in the
``<available_skills>`` XML section (progressive disclosure, layer 1).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SkillDef(BaseModel):
    """A skill manifest: prompt + extra-tool whitelist."""

    name: str
    one_line: str = ""
    prompt: str = ""
    extra_tools: list[str] = Field(default_factory=list)
    triggers: list[str] = Field(default_factory=list)


class SkillRegistry:
    """In-memory index of SkillDef by name."""

    def __init__(self, skills: list[SkillDef] | None = None) -> None:
        self.skills: dict[str, SkillDef] = {}
        if skills:
            for s in skills:
                self.skills[s.name] = s

    def add(self, skill: SkillDef) -> None:
        self.skills[skill.name] = skill

    def get(self, name: str) -> SkillDef | None:
        return self.skills.get(name)

    def list_skills(self) -> list[SkillDef]:
        return list(self.skills.values())

    def names(self) -> list[str]:
        return list(self.skills.keys())

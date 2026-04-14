"""SkillDef — the contract skills must satisfy.

Skills are *not* LLM-callable tools. They are prompt-template + allowed-tool
bundles. The Executor activates a skill by injecting its ``prompt_template``
into the LLM system prompt and restricting the tool set to ``allowed_tools``.

Concrete Skill instances live in the world-engine layer; this module only
defines the contract and a small registry used for matching / injection.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SkillDef:
    """A skill: a prompt template plus a whitelist of allowed tools."""

    name: str
    description: str
    prompt_template: str
    allowed_tools: list[str] = field(default_factory=list)


class SkillRegistry:
    """Minimal registry for SkillDef instances injected via AgentContext."""

    def __init__(self, skills: list[SkillDef] | None = None) -> None:
        self.skills: dict[str, SkillDef] = {}
        if skills:
            for s in skills:
                self.skills[s.name] = s

    def get(self, name: str) -> SkillDef | None:
        return self.skills.get(name)

    def list_skills(self) -> list[str]:
        return list(self.skills.keys())

    def get_descriptions(self) -> dict[str, str]:
        return {name: s.description for name, s in self.skills.items()}

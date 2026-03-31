"""Skill base class and loader.

Each skill is a directory containing:
  - description.md   (what the skill does)
  - script.py        (execution logic)
  - prompt.j2        (Jinja2 prompt template)
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import jinja2

from annie.npc.state import NPCProfile


class BaseSkill:
    """A single skill loaded from a data/skills/<name>/ directory."""

    def __init__(self, skill_dir: str | Path):
        self._dir = Path(skill_dir)
        if not self._dir.is_dir():
            raise FileNotFoundError(f"Skill directory not found: {self._dir}")

        self.name: str = self._dir.name
        self.description: str = self._load_description()
        self._script_module: ModuleType = self._load_script()
        self._prompt_template: jinja2.Template = self._load_prompt()

    def _load_description(self) -> str:
        desc_path = self._dir / "description.md"
        if desc_path.exists():
            return desc_path.read_text(encoding="utf-8")
        return ""

    def _load_script(self) -> ModuleType:
        script_path = self._dir / "script.py"
        if not script_path.exists():
            raise FileNotFoundError(f"Skill script not found: {script_path}")
        spec = importlib.util.spec_from_file_location(f"annie.skills.{self.name}", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _load_prompt(self) -> jinja2.Template:
        prompt_path = self._dir / "prompt.j2"
        if not prompt_path.exists():
            raise FileNotFoundError(f"Skill prompt template not found: {prompt_path}")
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(self._dir)),
            undefined=jinja2.StrictUndefined,
        )
        return env.get_template("prompt.j2")

    def execute(self, context: dict) -> dict:
        """Run the skill's script.py execute() function."""
        if not hasattr(self._script_module, "execute"):
            raise AttributeError(f"Skill '{self.name}' script has no execute() function")
        result = self._script_module.execute(context)
        return result if result is not None else {}

    def render_prompt(self, npc: NPCProfile, **kwargs) -> str:
        """Render the Jinja2 prompt template with NPC profile and extra context."""
        return self._prompt_template.render(npc=npc, **kwargs)


class SkillRegistry:
    """Discovers and manages all available skills from a directory."""

    def __init__(self, skills_dir: str | Path = "data/skills"):
        self._dir = Path(skills_dir)
        self.skills: dict[str, BaseSkill] = {}
        self._load_all()

    def _load_all(self) -> None:
        if not self._dir.is_dir():
            return
        for child in sorted(self._dir.iterdir()):
            if child.is_dir() and (child / "script.py").exists():
                try:
                    skill = BaseSkill(child)
                    self.skills[skill.name] = skill
                except Exception:
                    pass  # Skip malformed skill directories

    def get(self, name: str) -> BaseSkill | None:
        """Get a skill by name."""
        return self.skills.get(name)

    def list_skills(self) -> list[str]:
        """Return all available skill names."""
        return list(self.skills.keys())

    def get_descriptions(self) -> dict[str, str]:
        """Return {name: description} for all skills, useful for LLM context."""
        return {name: skill.description for name, skill in self.skills.items()}

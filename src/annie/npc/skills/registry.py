"""SkillRegistry loader — scans ``<root>/<name>/skill.yaml`` manifests.

Each skill directory must contain:

* ``skill.yaml`` — name / one_line / triggers / extra_tools
* ``prompt.md`` — the SystemMessage appended on activation

Missing ``prompt.md`` or malformed ``skill.yaml`` raises at load time.
Validation that ``extra_tools`` ids resolve is deferred to activation time
(when a ToolRegistry is available).
"""

from __future__ import annotations

import importlib
from pathlib import Path

from annie.npc.skills.base_skill import SkillDef, SkillRegistry


def load_dir(path: str | Path) -> SkillRegistry:
    root = Path(path)
    registry = SkillRegistry()
    if not root.exists():
        return registry
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        yaml_path = entry / "skill.yaml"
        prompt_path = entry / "prompt.md"
        if not yaml_path.exists():
            # Not a skill directory — silently skip. The repo root `skills/`
            # may host unrelated per-tool subdirectories.
            continue
        if not prompt_path.exists():
            raise FileNotFoundError(
                f"Skill directory '{entry}' missing prompt.md"
            )
        raw = importlib.import_module("yaml").safe_load(
            yaml_path.read_text(encoding="utf-8"),
        ) or {}
        raw.setdefault("name", entry.name)
        raw["prompt"] = prompt_path.read_text(encoding="utf-8")
        skill = SkillDef(**raw)
        registry.add(skill)
    return registry

"""SkillAgent — FROZEN in this change.

Skills (``SkillDef`` / ``SkillRegistry``) remain defined for future use, but
the Agent no longer activates them. ``try_activate`` always returns ``None``
and emits a one-shot DeprecationWarning per process. The Executor has no
skill-related code path.
"""

from __future__ import annotations

import logging
import warnings
from typing import Any

from annie.npc.skills.base_skill import SkillDef, SkillRegistry

logger = logging.getLogger(__name__)

_WARNED_ONCE: bool = False


class SkillAgent:
    """Frozen — see D7. Kept so world engines / tests can still import the name."""

    def __init__(self, skill_registry: SkillRegistry | None = None):
        self.skill_registry = skill_registry or SkillRegistry()

    def try_activate(
        self,
        task_description: str,
        tracer: Any | None = None,
    ) -> SkillDef | None:
        global _WARNED_ONCE
        if not _WARNED_ONCE:
            warnings.warn(
                "SkillAgent is frozen in this change; try_activate always returns None. "
                "A future change will reintroduce skills via a use_skill(name) tool.",
                DeprecationWarning,
                stacklevel=2,
            )
            _WARNED_ONCE = True
        return None

    def match(self, task_description: str) -> SkillDef | None:
        return None

    @staticmethod
    def render_injection(skill: SkillDef) -> str:
        return ""

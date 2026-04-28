"""SkillRuntime — activates skills within a running Executor tool loop.

Activation has three side effects:

1. Resolves the skill's ``extra_tools`` ids against the active ``ToolRegistry``
   and pushes them as a new frame (``push_frame`` → ``frame_id``).
2. Appends a ``SystemMessage`` containing ``skill.prompt`` (plus any user
   ``args`` as a JSON suffix) to the running Executor message list so the
   next ``llm.invoke`` sees the skill guidance.
3. Returns the ``frame_id`` so the Executor can pop the frame at loop end.

Skills are *not* LLM-callable tools. They are opened via the built-in
``use_skill`` tool which delegates here.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from langchain_core.messages import SystemMessage

from annie.npc.skills.base_skill import SkillDef, SkillRegistry

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

    from annie.npc.tools.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


class SkillRuntime:
    """Runtime component that resolves and activates ``SkillDef``s in-loop."""

    def __init__(self, skill_registry: SkillRegistry | None = None):
        self.skill_registry = skill_registry or SkillRegistry()

    def get(self, name: str) -> SkillDef | None:
        return self.skill_registry.get(name)

    def activate(
        self,
        skill_name: str,
        args: dict | None,
        messages: list["BaseMessage"],
        tool_registry: "ToolRegistry",
    ) -> str:
        """Activate ``skill_name`` against the given message list and registry.

        Raises ``ValueError`` when the skill is unknown or one of its
        ``extra_tools`` ids is not currently resolvable in ``tool_registry``.
        Returns the pushed ``frame_id`` so the caller can pop it later.
        """
        skill = self.skill_registry.get(skill_name)
        if skill is None:
            raise ValueError(f"unknown skill: {skill_name!r}")

        extra_tools = []
        for tid in skill.extra_tools:
            tool = tool_registry.get(tid)
            if tool is None:
                raise ValueError(
                    f"skill '{skill.name}' references unknown tool '{tid}'",
                )
            extra_tools.append(tool)

        frame_id = tool_registry.push_frame(extra_tools)

        prompt_text = skill.prompt or ""
        if args:
            prompt_text = (
                f"{prompt_text}\n\nUser args: "
                f"{json.dumps(args, ensure_ascii=False)}"
            )
        messages.append(SystemMessage(content=prompt_text))
        logger.debug(
            "Skill '%s' activated (frame_id=%s, extra_tools=%s)",
            skill.name, frame_id, skill.extra_tools,
        )
        return frame_id

"""Shared prompt fragments used by Executor and Reflector.

Keeping these in one place avoids drift between the two nodes' view of
"who this NPC is".
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from annie.npc.memory.interface import MEMORY_CATEGORY_TODO

if TYPE_CHECKING:
    from annie.npc.memory.interface import MemoryInterface
    from annie.npc.skills.base_skill import SkillDef

MEMORY_CATEGORIES_BLOCK = """\
- episodic: 原始经历（对话落盘、事件观察）
- semantic: 客观事实
- reflection: 自我反思与人物印象
- impression: 折叠产生的模糊印象
- todo: 跨回合未完成目标（可能为空）"""


def render_identity(ctx: Any) -> str:
    """Return the ``<character>...</character>`` XML block.

    Used by Executor (in the system template) and Reflector (appended to
    its system prompt) so both nodes see an identical character framing.
    """
    npc_id = getattr(ctx, "npc_id", "") or ""
    character_prompt = getattr(ctx, "character_prompt", "") or ""
    inner = f"Name: {npc_id}\n{character_prompt}".strip()
    return f"<character>\n{inner}\n</character>"


def render_skills_text(skills: list["SkillDef"]) -> str:
    """One-line-per-skill summary for the ``<available_skills>`` XML block."""
    if not skills:
        return "(none)"
    return "\n".join(
        f"- {s.name}: {s.one_line}" if s.one_line else f"- {s.name}"
        for s in skills
    )


def render_todo_text(memory: "MemoryInterface") -> str:
    """Render currently-open todos for the ``<todo>`` XML block."""
    opens = memory.grep(
        "", category=MEMORY_CATEGORY_TODO,
        metadata_filters={"status": "open"}, k=50,
    )
    closeds = memory.grep(
        "", category=MEMORY_CATEGORY_TODO,
        metadata_filters={"status": "closed"}, k=50,
    )
    closed_ids = {r.metadata.get("closes") for r in closeds}
    alive = [r for r in opens if r.metadata.get("todo_id") not in closed_ids]
    if not alive:
        return "(none)"
    return "\n".join(
        f"- [{r.metadata.get('todo_id', '?')}] {r.content}" for r in alive
    )

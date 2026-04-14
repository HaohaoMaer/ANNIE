"""Shared prompt fragments used by Executor and Reflector.

Keeping these in one place avoids drift between the two nodes' view of
"who this NPC is".
"""

from __future__ import annotations

from typing import Any

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

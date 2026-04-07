"""Deduction skill execution logic.

Analyzes clues and performs logical reasoning.
"""

from __future__ import annotations

from typing import Any


def execute(context: dict) -> dict[str, Any]:
    """Execute deduction skill.

    Args:
        context: Dict with:
            - 'npc': NPCProfile
            - 'clues': list of known clues
            - 'question': optional specific question to reason about

    Returns:
        Dict with:
            - 'reasoning_steps': list of reasoning steps
            - 'conclusion': the deduced conclusion
            - 'confidence': confidence level 0-1
    """
    npc = context.get("npc")
    clues = context.get("clues", [])
    question = context.get("question", "")

    reasoning_steps = []

    if clues:
        reasoning_steps.append(f"分析{len(clues)}条已知线索")

        for i, clue in enumerate(clues[:5]):
            reasoning_steps.append(f"线索{i+1}: {clue}")

    if question:
        reasoning_steps.append(f"针对问题进行分析: {question}")

    reasoning_steps.append("进行逻辑推理...")

    return {
        "reasoning_steps": reasoning_steps,
        "conclusion": "基于现有线索的推理结果",
        "confidence": 0.7,
        "npc_name": npc.name if npc else "Unknown",
    }

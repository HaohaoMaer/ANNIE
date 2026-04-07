"""Interrogation skill execution logic.

Generates questions and analyzes responses for contradictions.
"""

from __future__ import annotations

from typing import Any


def execute(context: dict) -> dict[str, Any]:
    """Execute interrogation skill.

    Args:
        context: Dict with:
            - 'npc': NPCProfile
            - 'target': name of NPC to interrogate
            - 'known_info': list of known information
            - 'previous_responses': optional previous responses from target

    Returns:
        Dict with:
            - 'questions': list of questions to ask
            - 'focus_areas': areas to focus on
            - 'contradictions': any detected contradictions
    """
    npc = context.get("npc")
    target = context.get("target", "未知对象")
    known_info = context.get("known_info", [])
    previous_responses = context.get("previous_responses", [])

    questions = []
    focus_areas = []

    questions.append(f"请问{target}，你能描述一下案发时你的行踪吗？")

    if known_info:
        for info in known_info[:3]:
            questions.append(f"关于{info}，你能详细说明一下吗？")

    if previous_responses:
        focus_areas.append("验证之前的陈述是否一致")

    focus_areas.extend(["时间线", "动机", "机会"])

    return {
        "questions": questions,
        "focus_areas": focus_areas,
        "contradictions": [],
        "npc_name": npc.name if npc else "Unknown",
        "target": target,
    }

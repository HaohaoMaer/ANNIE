"""Execution logic for conversation skill."""


def execute(context: dict) -> dict:
    """Process conversation context and return metadata for the LLM prompt."""
    return {
        "skill_type": "conversation",
        "task": context.get("task", ""),
        "npc_name": context.get("npc_name", "Unknown"),
    }

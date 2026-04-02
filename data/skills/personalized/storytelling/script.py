"""Execution logic for storytelling skill."""


def execute(context: dict) -> dict:
    """Provide storytelling context and guidance."""
    task = context.get("task", "")
    return {
        "skill_type": "storytelling",
        "topic": task,
        "guidance": (
            "Draw from your knowledge and experience to tell a relevant story. "
            "The story should convey wisdom, teach a lesson, or illuminate the "
            "current situation. Use language and imagery natural to your background."
        ),
    }

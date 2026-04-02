"""Execution logic for observation skill."""


def execute(context: dict) -> dict:
    """Analyze the scene and return structured observations."""
    task = context.get("task", "")
    return {
        "skill_type": "observation",
        "focus": task,
        "guidance": (
            "Carefully observe the scene. Note: who is present, their appearance "
            "and demeanor, notable objects or environmental details, the general "
            "mood and atmosphere, and any potential threats or opportunities."
        ),
    }

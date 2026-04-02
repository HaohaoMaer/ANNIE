"""Execution logic for reasoning skill."""


def execute(context: dict) -> dict:
    """Provide a reasoning framework for decision-making."""
    task = context.get("task", "")
    return {
        "skill_type": "reasoning",
        "dilemma": task,
        "guidance": (
            "Think through this step by step: 1) Identify the key decision or problem. "
            "2) List the available options. 3) Weigh each option against your core values "
            "and goals. 4) Consider potential consequences. 5) Reach a conclusion."
        ),
    }

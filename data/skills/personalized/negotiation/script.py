"""Execution logic for negotiation skill."""


def execute(context: dict) -> dict:
    """Provide negotiation strategy and guidance."""
    task = context.get("task", "")
    return {
        "skill_type": "negotiation",
        "situation": task,
        "guidance": (
            "Approach this negotiation by: 1) Understanding each party's core needs. "
            "2) Identifying common ground. 3) Proposing a fair compromise. "
            "4) Using persuasion appropriate to your authority and relationships."
        ),
    }

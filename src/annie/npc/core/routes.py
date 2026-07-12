"""Public execution route contract for NPCAgent."""

from __future__ import annotations

from enum import StrEnum


class AgentRoute(StrEnum):
    """Execution intent requested by a world engine for one NPC run."""

    ACTION = "action"
    DIALOGUE = "dialogue"
    STRUCTURED_JSON = "structured_json"
    REFLECTION = "reflection"


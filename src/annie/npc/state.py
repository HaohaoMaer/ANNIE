"""State models for ANNIE NPC system.

Defines the core data structures shared across all NPC components:
- NPCProfile: structured NPC character definition loaded from YAML
- Task: a decomposed unit of work for the Executor
- AgentState: the LangGraph TypedDict flowing between nodes
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, TypedDict

import yaml
from pydantic import BaseModel, Field


class Personality(BaseModel):
    traits: list[str] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)


class Background(BaseModel):
    biography: str = ""
    past_events: list[str] = Field(default_factory=list)


class Goals(BaseModel):
    short_term: list[str] = Field(default_factory=list)
    long_term: list[str] = Field(default_factory=list)


class NPCProfile(BaseModel):
    """Minimal NPC identity carrier after decouple refactor.

    `relationships` and `cognitive_*` fields have been removed — world engines
    parse those from YAML and fold them into the natural-language
    ``character_prompt`` injected via ``AgentContext``.
    """

    name: str
    personality: Personality = Field(default_factory=Personality)
    background: Background = Field(default_factory=Background)
    goals: Goals = Field(default_factory=Goals)
    memory_seed: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"


class Task(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    description: str
    priority: int = 0
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    result: str | None = None


class AgentState(TypedDict, total=False):
    agent_context: Any  # AgentContext instance — forward-declared to avoid import cycle
    input_event: str
    tasks: list[Task]
    current_task: Task | None
    execution_results: list[dict[str, Any]]
    reflection: str
    memory_context: str
    tracer: Any  # Tracer instance, typed as Any to avoid circular import with LangGraph
    # Loop control (dimension 1)
    retry_count: int
    max_retries: int
    loop_reason: str
    react_steps: list[dict[str, Any]]
    # Executor tool-use loop (per-run working memory)
    messages: list[Any]  # list[BaseMessage]; Any to keep state module free of langchain import
    context_budget: Any  # ContextBudget | None


def load_npc_profile(path: str | Path) -> NPCProfile:
    """Load an NPC profile from a YAML definition file.

    Args:
        path: Path to the NPC YAML file.

    Returns:
        A validated NPCProfile instance.

    Raises:
        FileNotFoundError: If the YAML file does not exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"NPC definition file not found: {path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    npc_data = raw.get("npc", raw)
    return NPCProfile(**npc_data)

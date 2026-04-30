"""State models for ANNIE NPC system.

Defines the core data structures shared across all NPC components:
- Task: a decomposed unit of work for the Executor
- AgentState: the LangGraph TypedDict flowing between nodes
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any, TypedDict

from pydantic import BaseModel, Field


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
    working_memory: str
    tracer: Any  # Tracer instance, typed as Any to avoid circular import with LangGraph
    # Loop control (dimension 1)
    retry_count: int
    max_retries: int
    loop_reason: str
    last_tasks: list[Task]
    react_steps: list[dict[str, Any]]
    # Executor tool-use loop (per-run working memory)
    messages: list[Any]  # list[BaseMessage]; Any to keep state module free of langchain import
    context_budget: Any  # ContextBudget | None
    runtime: dict[str, Any]
    # Prompt-time pre-renders
    todo_list_text: str
    active_skills: list[str]
    memory_updates: list[Any]
    debug_graph_nodes: list[str]

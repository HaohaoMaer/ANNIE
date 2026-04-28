"""Tool contract for the NPC Agent layer.

Only the new ToolDef lives here. All tools (built-in and world-engine-
injected) must satisfy this single contract.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from annie.npc.context import AgentContext

logger = logging.getLogger(__name__)


class ToolContext(BaseModel):
    """Execution-time context handed to ToolDef.call().

    Exposes the live AgentContext so tools can reach ``memory`` and the open
    ``extra`` dict without constructor-time injection.
    """

    model_config = {"arbitrary_types_allowed": True}

    agent_context: "AgentContext"
    runtime: dict[str, Any] = Field(default_factory=dict)


class ToolDef(ABC):
    """The unified Tool contract.

    Required class attributes: ``name``, ``description``. Subclasses should
    also set ``input_schema`` (a Pydantic model) and optionally
    ``output_schema``.
    """

    name: str
    description: str
    input_schema: type[BaseModel] | None = None
    output_schema: type[BaseModel] | None = None
    is_read_only: bool = True
    is_concurrency_safe: bool = True

    @abstractmethod
    def call(self, input: BaseModel | dict, ctx: ToolContext) -> Any:
        """Execute the tool; returns arbitrary JSON-serializable output."""

    def json_schema(self) -> dict:
        """Expose the LLM-facing JSON Schema for this tool's input."""
        if self.input_schema is not None:
            return self.input_schema.model_json_schema()
        return {"type": "object", "properties": {}}

    def safe_call(self, input_data: BaseModel | dict, ctx: ToolContext) -> dict:
        """Validate input against input_schema, call, catch exceptions."""
        try:
            if self.input_schema is not None and not isinstance(input_data, BaseModel):
                input_obj = self.input_schema(**(input_data or {}))
            else:
                input_obj = input_data
            result = self.call(input_obj, ctx)
            if isinstance(result, BaseModel):
                result = result.model_dump()
            return {"tool": self.name, "success": True, "result": result}
        except Exception as exc:
            logger.warning("Tool '%s' failed: %s", self.name, exc)
            return {"tool": self.name, "success": False, "error": str(exc)}

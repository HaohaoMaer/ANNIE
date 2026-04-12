"""Tool definitions for the NPC Agent layer.

Two classes coexist here during the refactor:

* ``BaseTool`` — the legacy abstract tool still used by existing Executor /
  ToolAgent paths. Retained unchanged so current tests keep running until
  Phase 3 migrates call sites to ``ToolDef``.
* ``ToolDef`` — the new ToolDef contract defined in
  ``specs/tool-skill-system/spec.md``. Tools created from Phase 3 onwards
  must conform to this.

A ``ToolContext`` is supplied to ``ToolDef.call`` so tools can reach the live
``AgentContext`` (for ``memory``, ``extra``, etc.) without ctor injection.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from annie.npc.context import AgentContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Legacy tool (kept until Phase 3 completes the migration)
# ---------------------------------------------------------------------------


class BaseTool(ABC):
    """Legacy abstract tool. Do not add new tools against this; use ToolDef."""

    name: str
    description: str
    parameters_schema: dict = {}
    requires_action: bool = False

    @abstractmethod
    def execute(self, context: dict) -> dict: ...

    def get_brief(self) -> str:
        return f"{self.name}: {self.description}"

    def get_full_schema(self) -> dict:
        return {"name": self.name, "description": self.description, "parameters": self.parameters_schema}

    def validate_context(self, context: dict) -> list[str]:
        errors: list[str] = []
        schema = self.parameters_schema
        if not schema:
            return errors
        required = schema.get("required", [])
        props = schema.get("properties", {})
        for key in required:
            if key not in context or context[key] is None:
                errors.append(f"Missing required parameter '{key}'")
            elif props.get(key, {}).get("type") == "string":
                val = context[key]
                if not isinstance(val, str) or not val.strip():
                    errors.append(f"Parameter '{key}' must be a non-empty string")
        return errors

    def safe_execute(self, context: dict) -> dict:
        errors = self.validate_context(context)
        if errors:
            return {"tool": self.name, "error": "; ".join(errors), "success": False}
        try:
            result = self.execute(context)
            return {**result, "success": True}
        except Exception as exc:
            logger.warning("Tool '%s' raised an exception: %s", self.name, exc)
            return {"tool": self.name, "error": str(exc), "success": False}


# ---------------------------------------------------------------------------
# New ToolDef — the Phase-3 spec contract
# ---------------------------------------------------------------------------


class ToolContext(BaseModel):
    """Execution-time context for a ToolDef.call().

    Exposes the live AgentContext so tools can reach ``memory`` and the open
    ``extra`` dict without constructor-time injection (which is brittle when
    the same NPCAgent instance is reused across runs).
    """

    model_config = {"arbitrary_types_allowed": True}

    agent_context: "AgentContext"


class ToolDef(ABC):
    """The unified Tool contract. Both built-in and world-engine-injected
    tools must satisfy this.

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

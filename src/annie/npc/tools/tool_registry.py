"""ToolRegistry — merges built-in ToolDefs with AgentContext-injected ones.

Conflict policy: **built-in wins**. A warning is logged when a world-engine-
injected tool would shadow a built-in, and the injected one is dropped.

In addition to the base layer, the registry supports a stack of *frames*
(``push_frame`` / ``pop_frame``) used by the ``use_skill`` built-in to
temporarily expose a skill's ``extra_tools`` within the current Executor
loop iteration only.
"""

from __future__ import annotations

import logging
import uuid

from annie.npc.tools.base_tool import ToolDef
from annie.npc.tools.builtin import default_builtin_tools

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Unified registry exposed to the Executor / LLM."""

    def __init__(
        self,
        injected: list[ToolDef] | None = None,
        builtins: list[ToolDef] | None = None,
        disabled_tools: set[str] | list[str] | tuple[str, ...] | None = None,
        route: str = "action",
    ) -> None:
        self._disabled_tools = set(disabled_tools or [])
        self._route = route
        self._base: dict[str, ToolDef] = {}
        for t in builtins if builtins is not None else default_builtin_tools():
            if not _tool_allowed_for_route(t, route, default_action_only=False):
                continue
            if t.name in self._disabled_tools:
                continue
            self._base[t.name] = t
        if injected:
            for t in injected:
                if not _tool_allowed_for_route(t, route, default_action_only=True):
                    continue
                if t.name in self._disabled_tools:
                    continue
                if t.name in self._base:
                    logger.warning(
                        "Tool '%s' is built-in; injected version ignored.", t.name,
                    )
                    continue
                self._base[t.name] = t
        self._frames: list[tuple[str, dict[str, ToolDef]]] = []

    # ---- Read API ------------------------------------------------------
    def get(self, name: str) -> ToolDef | None:
        if name in self._disabled_tools:
            return None
        # Frames shadow base so skills can temporarily add tools, but never
        # override built-ins in `_base` (built-in wins at construction).
        for _, frame in reversed(self._frames):
            if name in frame:
                return frame[name]
        return self._base.get(name)

    def list_tools(self) -> list[str]:
        merged: dict[str, None] = dict.fromkeys(self._base)
        for _, frame in self._frames:
            for n in frame:
                if n not in self._disabled_tools:
                    merged.setdefault(n, None)
        return list(merged)

    def get_descriptions(self) -> dict[str, str]:
        result: dict[str, str] = {n: t.description for n, t in self._base.items()}
        for _, frame in self._frames:
            for n, t in frame.items():
                if n not in self._disabled_tools:
                    result.setdefault(n, t.description)
        return result

    # ---- Frame stack ---------------------------------------------------
    def push_frame(self, tools: list[ToolDef]) -> str:
        """Push a new frame of temporarily-visible tools; returns a frame id.

        Tools whose name collides with an existing base built-in are silently
        ignored on the frame (built-in wins). Duplicate names within the frame
        keep the last occurrence.
        """
        frame: dict[str, ToolDef] = {}
        for t in tools:
            if not _tool_allowed_for_route(t, self._route, default_action_only=True):
                continue
            if t.name in self._disabled_tools:
                continue
            if t.name in self._base and self._base[t.name] is not t:
                logger.warning(
                    "Skill frame tool '%s' shadows built-in; ignored.", t.name,
                )
                continue
            frame[t.name] = t
        frame_id = uuid.uuid4().hex[:8]
        self._frames.append((frame_id, frame))
        return frame_id

    def pop_frame(self, frame_id: str | None = None) -> None:
        """Pop the top frame (default) or the frame with the given id.

        No-op (with a warning) if the stack is empty or the id is not found.
        """
        if not self._frames:
            logger.warning("pop_frame called on empty frame stack")
            return
        if frame_id is None:
            self._frames.pop()
            return
        for i in range(len(self._frames) - 1, -1, -1):
            if self._frames[i][0] == frame_id:
                self._frames.pop(i)
                return
        logger.warning("pop_frame: frame id '%s' not found", frame_id)


def _tool_allowed_for_route(
    tool: ToolDef,
    route: str,
    *,
    default_action_only: bool,
) -> bool:
    allowed = getattr(tool, "allowed_routes", None)
    if allowed is None:
        return route == "action" if default_action_only else True
    return route in {str(item) for item in allowed}

from __future__ import annotations

from annie.npc.core.context import AgentContext
from annie.npc.core.response import ActionRequest, ActionResult
from annie.npc.runtime.tool_dispatcher import ToolDispatcher
from annie.npc.tools.tool_registry import ToolRegistry
from annie.world_engine.tools import WorldActionTool


class _Memory:
    def recall(self, query, categories=None, k=5):
        return []

    def grep(self, pattern, category=None, metadata_filters=None, k=20):
        return []

    def remember(self, content, category="semantic", metadata=None):
        return None

    def build_context(self, query):
        return ""


def _ctx() -> AgentContext:
    return AgentContext(npc_id="npc1", input_event="event", memory=_Memory())


def test_world_tool_statuses_cover_success_failure_running_and_invalid():
    results = {
        "ok": ActionResult(
            action_id="a1",
            action_type="ok",
            status="succeeded",
            observation="done",
        ),
        "blocked": ActionResult(
            action_id="a2",
            action_type="blocked",
            status="failed",
            reason="unreachable",
            observation="blocked",
        ),
        "long": ActionResult(
            action_id="a3",
            action_type="long",
            status="deferred",
            observation="still running",
        ),
        "bad": ActionResult(
            action_id="a4",
            action_type="bad",
            status="failed",
            reason="invalid_payload",
            observation="bad payload",
        ),
    }

    def execute(_npc_id: str, action: ActionRequest) -> ActionResult:
        return results[action.type]

    runtime = {"action_results": [], "tool_statuses": []}
    dispatcher = ToolDispatcher(
        ToolRegistry(injected=[WorldActionTool("npc1", execute)], builtins=[]),
        runtime=runtime,
    )
    context = _ctx()

    for name in ("ok", "blocked", "long", "bad"):
        dispatcher.dispatch_result(
            {
                "name": "world_action",
                "args": {"type": name, "payload": {}},
                "id": f"call_{name}",
            },
            context,
        )

    statuses = runtime["tool_statuses"]
    assert [status.status for status in statuses] == [
        "success",
        "rejected",
        "running",
        "invalid",
    ]
    assert [status.call_id for status in statuses] == [
        "call_ok",
        "call_blocked",
        "call_long",
        "call_bad",
    ]
    assert statuses[0].world_state_changed is True

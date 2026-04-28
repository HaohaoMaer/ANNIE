"""Unit tests for game-specific tools."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from annie.npc.context import AgentContext
from annie.npc.tools.base_tool import ToolContext
from annie.war_game.tools import (
    DeclareIntentTool,
    DeployForcesTool,
    FinalDecisionTool,
    NegotiateResponseTool,
    SendMessageTool,
)


def _make_ctx(**extra: object) -> ToolContext:
    """Build a ToolContext with a mock AgentContext carrying given extra dict."""
    agent_ctx = MagicMock(spec=AgentContext)
    agent_ctx.extra = dict(extra)
    return ToolContext(agent_context=agent_ctx)


class TestDeclareIntentTool:
    def test_valid(self) -> None:
        tool = DeclareIntentTool()
        ctx = _make_ctx()
        result = tool.call({"statement": "本轮我将防守"}, ctx)
        assert result == "本轮我将防守"
        assert ctx.agent_context.extra["_declaration"] == "本轮我将防守"

    def test_empty_rejected(self) -> None:
        tool = DeclareIntentTool()
        ctx = _make_ctx()
        with pytest.raises(ValueError, match="empty"):
            tool.call({"statement": "   "}, ctx)


class TestSendMessageTool:
    def test_valid(self) -> None:
        tool = SendMessageTool()
        ctx = _make_ctx()
        result = tool.call({"message": "联手？"}, ctx)
        assert result == "联手？"
        assert ctx.agent_context.extra["_message"] == "联手？"


class TestDeployForcesTool:
    def _ctx(self) -> ToolContext:
        return _make_ctx(
            force_pool=1000,
            owned_city_ids=["A1", "A2", "A3", "A4", "A5"],
            adjacent_enemy_ids=["P4", "P2", "B5", "B3"],
        )

    def test_valid_deployment(self) -> None:
        tool = DeployForcesTool()
        ctx = self._ctx()
        allocations = [
            {"target": "A1", "troops": 100, "action": "defend"},
            {"target": "A2", "troops": 100, "action": "defend"},
            {"target": "A3", "troops": 100, "action": "defend"},
            {"target": "A4", "troops": 100, "action": "defend"},
            {"target": "A5", "troops": 100, "action": "defend"},
            {"target": "P4", "troops": 500, "action": "attack"},
        ]
        result = tool.call({"allocations": allocations}, ctx)
        assert "accepted" in result.lower()
        assert len(ctx.agent_context.extra["_deployments"]) == 6

    def test_total_mismatch(self) -> None:
        tool = DeployForcesTool()
        ctx = self._ctx()
        allocations = [
            {"target": "A1", "troops": 100, "action": "defend"},
            {"target": "A2", "troops": 100, "action": "defend"},
            {"target": "A3", "troops": 100, "action": "defend"},
            {"target": "A4", "troops": 100, "action": "defend"},
            {"target": "A5", "troops": 100, "action": "defend"},
        ]
        with pytest.raises(ValueError, match="does not match"):
            tool.call({"allocations": allocations}, ctx)

    def test_non_adjacent_attack(self) -> None:
        tool = DeployForcesTool()
        ctx = self._ctx()
        allocations = [
            {"target": "A1", "troops": 0, "action": "defend"},
            {"target": "A2", "troops": 0, "action": "defend"},
            {"target": "A3", "troops": 0, "action": "defend"},
            {"target": "A4", "troops": 0, "action": "defend"},
            {"target": "A5", "troops": 0, "action": "defend"},
            {"target": "B1", "troops": 1000, "action": "attack"},  # not adjacent
        ]
        with pytest.raises(ValueError, match="not adjacent"):
            tool.call({"allocations": allocations}, ctx)

    def test_missing_defense(self) -> None:
        tool = DeployForcesTool()
        ctx = self._ctx()
        allocations = [
            {"target": "A1", "troops": 500, "action": "defend"},
            # Missing A2, A3, A4, A5
            {"target": "P4", "troops": 500, "action": "attack"},
        ]
        with pytest.raises(ValueError, match="Missing defense"):
            tool.call({"allocations": allocations}, ctx)

    def test_negative_troops(self) -> None:
        tool = DeployForcesTool()
        ctx = self._ctx()
        allocations = [
            {"target": "A1", "troops": -100, "action": "defend"},
        ]
        with pytest.raises(ValueError, match="non-negative"):
            tool.call({"allocations": allocations}, ctx)


class TestNegotiateResponseTool:
    def test_valid(self) -> None:
        tool = NegotiateResponseTool()
        ctx = _make_ctx()
        result = tool.call({"message": "我撤你也撤"}, ctx)
        assert result == "我撤你也撤"

    def test_schema_exists(self) -> None:
        tool = NegotiateResponseTool()
        schema = tool.json_schema()
        assert "message" in schema.get("properties", {})


class TestFinalDecisionTool:
    def test_withdraw(self) -> None:
        tool = FinalDecisionTool()
        ctx = _make_ctx()
        result = tool.call({"choice": "withdraw"}, ctx)
        assert "withdraw" in result
        assert ctx.agent_context.extra["_final_decision"] == "withdraw"

    def test_fight(self) -> None:
        tool = FinalDecisionTool()
        ctx = _make_ctx()
        result = tool.call({"choice": "fight"}, ctx)
        assert "fight" in result
        assert ctx.agent_context.extra["_final_decision"] == "fight"

    def test_invalid_choice(self) -> None:
        tool = FinalDecisionTool()
        ctx = _make_ctx()
        with pytest.raises(ValueError, match="withdraw.*fight"):
            tool.call({"choice": "maybe"}, ctx)

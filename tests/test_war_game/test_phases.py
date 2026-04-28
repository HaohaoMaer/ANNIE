"""Integration test: full round cycle with stubbed agent."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import chromadb
import pytest

from annie.npc.context import AgentContext
from annie.npc.response import AgentResponse
from annie.war_game.config import GameConfig
from annie.war_game.engine import WarGameEngine
from annie.war_game.game_state import Deployment
from annie.war_game.map_preset import FACTION_A, FACTION_B, PLAYER
from annie.war_game.phases import (
    declaration_phase,
    deployment_phase,
    diplomacy_phase,
    generate_round_report,
    resolution_phase,
)


class _MockAgent:
    """Mock NPCAgent that sets tool-result extras based on the phase."""

    def __init__(self) -> None:
        self.run_count = 0

    def run(self, ctx: AgentContext) -> AgentResponse:
        self.run_count += 1
        phase = ctx.extra.get("phase", "")
        faction_id = ctx.extra.get("faction_id", "")

        if phase == "declaration":
            ctx.extra["_declaration"] = f"{faction_id} 宣言：本轮防守"

        elif phase == "diplomacy":
            ctx.extra["_message"] = f"{faction_id} 外交消息"

        elif phase == "deployment":
            # Deploy all to defense equally
            owned = ctx.extra.get("owned_city_ids", [])
            pool = ctx.extra.get("force_pool", 0)
            per_city = pool // len(owned) if owned else 0
            remainder = pool - per_city * len(owned) if owned else 0
            deployments = []
            for i, cid in enumerate(owned):
                troops = per_city + (1 if i < remainder else 0)
                deployments.append(Deployment(target=cid, troops=troops, action="defend"))
            ctx.extra["_deployments"] = deployments

        elif phase == "final_decision":
            ctx.extra["_final_decision"] = "withdraw"

        return AgentResponse(dialogue=f"{faction_id} response")


@pytest.fixture
def tmp_chroma(tmp_path):
    return chromadb.PersistentClient(path=str(tmp_path / "vs"))


@pytest.fixture
def engine(tmp_path, tmp_chroma):
    return WarGameEngine(
        config=GameConfig(max_diplomacy_rounds=2),
        chroma_client=tmp_chroma,
        history_dir=tmp_path / "hist",
    )


@pytest.fixture
def agent():
    return _MockAgent()


class TestDeclarationPhase:
    def test_collects_all_declarations(self, engine, agent) -> None:
        state = engine.state
        state.round_number = 1
        declaration_phase(
            state, engine, agent,
            player_input_fn=lambda _: "我要进攻甲方",
        )
        assert PLAYER in state.declarations
        assert FACTION_A in state.declarations
        assert FACTION_B in state.declarations
        assert "进攻甲方" in state.declarations[PLAYER]

    def test_skips_eliminated(self, engine, agent) -> None:
        state = engine.state
        state.factions[FACTION_B].is_eliminated = True
        declaration_phase(state, engine, agent, player_input_fn=lambda _: "test")
        assert FACTION_B not in state.declarations


class TestDiplomacyPhase:
    def test_runs_conversations(self, engine, agent) -> None:
        state = engine.state
        messages_received: list[tuple[str, str]] = []

        def on_msg(name: str, msg: str) -> None:
            messages_received.append((name, msg))

        round_count = 0
        def player_input(_prompt: str) -> str:
            nonlocal round_count
            round_count += 1
            if round_count > 2:
                return "end"
            return "你好"

        diplomacy_phase(
            state, engine, agent,
            player_input_fn=player_input,
            on_ai_message=on_msg,
        )
        # Should have at least some AI responses
        assert agent.run_count > 0


class TestDeploymentPhase:
    def test_ai_deploys(self, engine, agent) -> None:
        state = engine.state
        deployment_phase(state, engine, agent)
        assert FACTION_A in state.deployments
        assert FACTION_B in state.deployments
        # All forces accounted for
        for fid in [FACTION_A, FACTION_B]:
            total = sum(d.troops for d in state.deployments[fid])
            assert total == state.factions[fid].force_pool


class TestResolutionPhase:
    def test_no_battles(self, engine, agent) -> None:
        state = engine.state
        # All defend → no battles
        for fid in [PLAYER, FACTION_A, FACTION_B]:
            owned = state.owned_cities(fid)
            pool = state.factions[fid].force_pool
            per_city = pool // len(owned)
            remainder = pool - per_city * len(owned)
            deps = []
            for i, c in enumerate(owned):
                deps.append(Deployment(
                    target=c.id,
                    troops=per_city + (1 if i < remainder else 0),
                    action="defend",
                ))
            state.deployments[fid] = deps

        results = resolution_phase(state, engine)
        assert len(results) == 0

    def test_1v1_battle(self, engine, agent) -> None:
        state = engine.state
        state.round_number = 1
        # A attacks P4, everyone else defends
        state.deployments = {
            FACTION_A: [
                Deployment(target="A1", troops=100, action="defend"),
                Deployment(target="A2", troops=100, action="defend"),
                Deployment(target="A3", troops=100, action="defend"),
                Deployment(target="A4", troops=100, action="defend"),
                Deployment(target="A5", troops=100, action="defend"),
                Deployment(target="P4", troops=500, action="attack"),
            ],
            PLAYER: [
                Deployment(target="P1", troops=200, action="defend"),
                Deployment(target="P2", troops=200, action="defend"),
                Deployment(target="P3", troops=200, action="defend"),
                Deployment(target="P4", troops=200, action="defend"),
                Deployment(target="P5", troops=200, action="defend"),
            ],
            FACTION_B: [
                Deployment(target="B1", troops=200, action="defend"),
                Deployment(target="B2", troops=200, action="defend"),
                Deployment(target="B3", troops=200, action="defend"),
                Deployment(target="B4", troops=200, action="defend"),
                Deployment(target="B5", troops=200, action="defend"),
            ],
        }
        results = resolution_phase(state, engine)
        assert len(results) == 1
        r = results[0]
        assert r.city_id == "P4"
        assert r.city_captured is True
        assert r.winner == FACTION_A
        # P4 now belongs to A
        assert state.cities["P4"].owner == FACTION_A
        # A gets 300 remaining back + production
        # B gets production for 5 cities

    def test_production_applies(self, engine, agent) -> None:
        state = engine.state
        initial_pool = state.factions[PLAYER].force_pool
        # All defend
        for fid in [PLAYER, FACTION_A, FACTION_B]:
            owned = state.owned_cities(fid)
            pool = state.factions[fid].force_pool
            per_city = pool // len(owned)
            remainder = pool - per_city * len(owned)
            deps = []
            for i, c in enumerate(owned):
                deps.append(Deployment(
                    target=c.id,
                    troops=per_city + (1 if i < remainder else 0),
                    action="defend",
                ))
            state.deployments[fid] = deps

        resolution_phase(state, engine)
        # After resolution, pool should have production added
        # All troops returned from defense + 5 cities * 50 production
        expected = initial_pool + 5 * engine.config.production_per_city
        assert state.factions[PLAYER].force_pool == expected


class TestFullRoundCycle:
    def test_declaration_diplomacy_deployment_resolution(self, engine, agent) -> None:
        """Full round: declaration → diplomacy → deployment → resolution → report."""
        state = engine.state
        state.round_number = 1

        # 1. Declaration
        declaration_phase(state, engine, agent, player_input_fn=lambda _: "防守")
        assert len(state.declarations) == 3

        # 2. Diplomacy
        msg_count = 0
        def player_diplo(_: str) -> str:
            nonlocal msg_count
            msg_count += 1
            return "end"  # end immediately

        diplomacy_phase(state, engine, agent, player_input_fn=player_diplo)

        # 3. Deployment
        deployment_phase(state, engine, agent)
        for fid in [FACTION_A, FACTION_B]:
            assert fid in state.deployments

        # 4. Resolution
        results = resolution_phase(state, engine)

        # 5. Report
        report = generate_round_report(state, results)
        assert "第1回合" in report
        assert "宣言 vs 实际" in report


class TestGenerateRoundReport:
    def test_report_includes_battle_details(self, engine) -> None:
        from annie.war_game.game_state import BattleResult
        state = engine.state
        state.round_number = 2
        state.declarations = {
            PLAYER: "防守",
            FACTION_A: "防守",
            FACTION_B: "联合进攻",
        }
        battles = [
            BattleResult(
                city_id="P4",
                attacker_id=FACTION_A,
                defender_id=PLAYER,
                attacker_troops=500,
                defender_troops=300,
                winner=FACTION_A,
                attacker_remaining=200,
                city_captured=True,
            ),
        ]
        report = generate_round_report(state, battles)
        assert "P4" in report
        assert "500" in report
        assert "300" in report
        assert "甲" in report

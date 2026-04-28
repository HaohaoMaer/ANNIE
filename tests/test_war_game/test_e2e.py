"""End-to-end integration test: 2-round game with stubbed agent.

Covers: declaration, diplomacy, deployment, combat, production, elimination.
"""

from __future__ import annotations

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


class _AggressiveAgent:
    """Agent that always attacks with most forces.

    Faction A attacks Player territory (P4 via A3, P2 via A5).
    Faction B defends everything.
    """

    def __init__(self) -> None:
        self.run_count = 0

    def run(self, ctx: AgentContext) -> AgentResponse:
        self.run_count += 1
        phase = ctx.extra.get("phase", "")
        faction_id = ctx.extra.get("faction_id", "")

        if phase == "declaration":
            decl = "本轮防守" if faction_id == FACTION_A else "保持和平"
            ctx.extra["_declaration"] = decl

        elif phase == "diplomacy":
            ctx.extra["_message"] = "我们联手吧"

        elif phase == "deployment":
            owned = ctx.extra.get("owned_city_ids", [])
            adj_enemies = ctx.extra.get("adjacent_enemy_ids", [])
            pool = ctx.extra.get("force_pool", 0)

            if faction_id == FACTION_A and adj_enemies:
                # Attack the first adjacent enemy with 60% forces
                attack_troops = int(pool * 0.6)
                defense_pool = pool - attack_troops
                per_city = defense_pool // len(owned) if owned else 0
                remainder = defense_pool - per_city * len(owned) if owned else 0

                deployments = []
                for i, cid in enumerate(owned):
                    t = per_city + (1 if i < remainder else 0)
                    deployments.append(Deployment(target=cid, troops=t, action="defend"))
                deployments.append(
                    Deployment(target=adj_enemies[0], troops=attack_troops, action="attack")
                )
                ctx.extra["_deployments"] = deployments
            else:
                # All defense
                per_city = pool // len(owned) if owned else 0
                remainder = pool - per_city * len(owned) if owned else 0
                deployments = []
                for i, cid in enumerate(owned):
                    t = per_city + (1 if i < remainder else 0)
                    deployments.append(Deployment(target=cid, troops=t, action="defend"))
                ctx.extra["_deployments"] = deployments

        elif phase == "final_decision":
            ctx.extra["_final_decision"] = "fight"

        return AgentResponse(dialogue=f"{faction_id} says something")


@pytest.fixture
def tmp_chroma(tmp_path):
    return chromadb.PersistentClient(path=str(tmp_path / "vs"))


def test_two_round_game(tmp_path, tmp_chroma):
    """Run 2 rounds with A attacking Player, verify state progression."""
    config = GameConfig(
        initial_forces=1000,
        production_per_city=50,
        max_diplomacy_rounds=1,
    )
    engine = WarGameEngine(
        config=config,
        chroma_client=tmp_chroma,
        history_dir=tmp_path / "hist",
    )
    agent = _AggressiveAgent()
    state = engine.state

    # Verify initial state
    assert len(state.owned_cities(PLAYER)) == 5
    assert len(state.owned_cities(FACTION_A)) == 5
    assert len(state.owned_cities(FACTION_B)) == 5

    for round_num in range(1, 3):
        state.round_number = round_num

        # Declaration
        declaration_phase(state, engine, agent, player_input_fn=lambda _: "防守")

        # Diplomacy
        msg_num = 0
        def player_diplo(_: str) -> str:
            nonlocal msg_num
            msg_num += 1
            return "end"

        diplomacy_phase(
            state, engine, agent,
            player_input_fn=player_diplo,
        )

        # Player deploys all to defense
        owned_p = state.owned_cities(PLAYER)
        pool_p = state.factions[PLAYER].force_pool
        per_city_p = pool_p // len(owned_p) if owned_p else 0
        remainder_p = pool_p - per_city_p * len(owned_p) if owned_p else 0
        state.deployments[PLAYER] = [
            Deployment(
                target=c.id,
                troops=per_city_p + (1 if i < remainder_p else 0),
                action="defend",
            )
            for i, c in enumerate(owned_p)
        ]

        # AI deployment
        deployment_phase(state, engine, agent, player_input_fn=None)
        # Restore player deployment (deployment_phase may have overwritten with default)
        # Actually deployment_phase with player_input_fn=None uses default defense, let's just
        # use the deployments as set by the phase for all factions.

        # Resolution
        results = resolution_phase(state, engine, agent)

        # Generate report
        report = generate_round_report(state, results)
        assert f"第{round_num}回合" in report

    # After 2 rounds:
    # - A has been attacking, some battles should have occurred
    # - Force pools should have changed
    # - No faction should be eliminated after only 2 rounds with these parameters
    assert not state.is_game_over(), "Game should not be over after only 2 rounds"
    # Verify agent was called many times (declaration + diplomacy + deployment per round)
    assert agent.run_count > 10


def test_elimination(tmp_path, tmp_chroma):
    """Test that a faction with 0 cities gets eliminated."""
    config = GameConfig(initial_forces=5000, production_per_city=0)
    engine = WarGameEngine(
        config=config,
        chroma_client=tmp_chroma,
        history_dir=tmp_path / "hist",
    )
    state = engine.state

    # Manually set up: give all of B's cities to A
    for cid in ["B1", "B2", "B3", "B4", "B5"]:
        state.cities[cid].owner = FACTION_A

    # Set up deployments (all defend, no battles)
    for fid in [PLAYER, FACTION_A, FACTION_B]:
        owned = state.owned_cities(fid)
        pool = state.factions[fid].force_pool
        if not owned:
            state.deployments[fid] = []
            continue
        per_city = pool // len(owned)
        remainder = pool - per_city * len(owned)
        state.deployments[fid] = [
            Deployment(
                target=c.id,
                troops=per_city + (1 if i < remainder else 0),
                action="defend",
            )
            for i, c in enumerate(owned)
        ]

    # Resolution should detect B has 0 cities and eliminate them
    resolution_phase(state, engine)
    assert state.factions[FACTION_B].is_eliminated
    assert state.factions[FACTION_B].force_pool == 0
    assert not state.factions[PLAYER].is_eliminated
    assert not state.factions[FACTION_A].is_eliminated

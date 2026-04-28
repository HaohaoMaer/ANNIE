"""Phase orchestration for the three-faction war game.

Each phase is a standalone function that takes (state, engine, agent, ...)
for easy testing and clear separation of concerns.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from annie.npc.agent import NPCAgent
from annie.war_game.combat import (
    resolve_2v1_attrition,
    resolve_2v1_standoff,
    resolve_all_battles,
)
from annie.war_game.game_state import BattleResult, Deployment, GameState
from annie.war_game.map_preset import FACTION_A, FACTION_B, FACTION_NAMES, PLAYER

if TYPE_CHECKING:
    from annie.war_game.engine import WarGameEngine

logger = logging.getLogger(__name__)


# ---- Declaration phase ---------------------------------------------------

def declaration_phase(
    state: GameState,
    engine: "WarGameEngine",
    agent: NPCAgent,
    player_input_fn: Callable[[str], str] | None = None,
) -> None:
    """Collect declarations from player and both AI factions.

    Args:
        player_input_fn: Callback for player declaration. If None, player is skipped.
    """
    state.declarations.clear()

    # Player declaration
    if player_input_fn is not None and not state.factions[PLAYER].is_eliminated:
        decl = player_input_fn("Your declaration: ")
        state.declarations[PLAYER] = decl

    # AI faction declarations
    for faction_id in [FACTION_A, FACTION_B]:
        if state.factions[faction_id].is_eliminated:
            continue
        ctx = engine.build_context(
            faction_id,
            event="宣言阶段：请发表你本轮的公开宣言。",
            phase="declaration",
        )
        response = agent.run(ctx)
        engine.handle_response(faction_id, response)
        # Extract declaration from extra (set by DeclareIntentTool)
        decl = ctx.extra.get("_declaration", response.dialogue or "（无宣言）")
        state.declarations[faction_id] = decl


# ---- Diplomacy phase -----------------------------------------------------

def diplomacy_phase(
    state: GameState,
    engine: "WarGameEngine",
    agent: NPCAgent,
    player_input_fn: Callable[[str], str] | None = None,
    on_ai_message: Callable[[str, str], None] | None = None,
) -> None:
    """Run pairwise diplomacy conversations.

    Args:
        player_input_fn: Callback for player messages. Returns "end" to stop early.
        on_ai_message: Callback(faction_name, message) to display AI messages to player.
    """
    max_rounds = engine.config.max_diplomacy_rounds
    active_ids = [f.id for f in state.active_factions()]

    # Player-AI conversations
    if PLAYER in active_ids and player_input_fn is not None:
        for ai_id in [FACTION_A, FACTION_B]:
            if ai_id not in active_ids:
                continue
            _run_player_ai_diplomacy(
                state, engine, agent, ai_id, max_rounds,
                player_input_fn, on_ai_message,
            )

    # AI-AI conversation
    if FACTION_A in active_ids and FACTION_B in active_ids:
        _run_ai_ai_diplomacy(state, engine, agent, FACTION_A, FACTION_B, max_rounds)


def _run_player_ai_diplomacy(
    state: GameState,
    engine: "WarGameEngine",
    agent: NPCAgent,
    ai_id: str,
    max_rounds: int,
    player_input_fn: Callable[[str], str],
    on_ai_message: Callable[[str, str], None] | None,
) -> None:
    ai_name = FACTION_NAMES.get(ai_id, ai_id)
    for round_num in range(1, max_rounds + 1):
        # Player message
        prompt = f"[Diplomacy with {ai_name}] Message {round_num}/{max_rounds} (type 'end' to finish): "
        player_msg = player_input_fn(prompt)
        if player_msg.lower().strip() == "end":
            break

        # Record player message in AI's history
        engine.history_for(ai_id).append(speaker=PLAYER, content=player_msg)

        # AI response
        ctx = engine.build_context(
            ai_id,
            event=f"外交阶段：丙方对你说：\"{player_msg}\"",
            phase="diplomacy",
        )
        response = agent.run(ctx)
        engine.handle_response(ai_id, response)
        ai_msg = ctx.extra.get("_message", response.dialogue or "...")

        if on_ai_message:
            on_ai_message(ai_name, ai_msg)


def _run_ai_ai_diplomacy(
    state: GameState,
    engine: "WarGameEngine",
    agent: NPCAgent,
    faction_a: str,
    faction_b: str,
    max_rounds: int,
) -> None:
    """Run AI-AI private diplomacy (invisible to player)."""
    for round_num in range(1, max_rounds + 1):
        # A speaks to B
        ctx_a = engine.build_context(
            faction_a,
            event=f"外交阶段：你正在与{FACTION_NAMES[faction_b]}进行第{round_num}轮私下对话。请发送消息。",
            phase="diplomacy",
        )
        resp_a = agent.run(ctx_a)
        engine.handle_response(faction_a, resp_a)
        msg_a = ctx_a.extra.get("_message", resp_a.dialogue or "...")

        # Deliver A's message to B
        engine.history_for(faction_b).append(speaker=faction_a, content=msg_a)

        # B responds to A
        ctx_b = engine.build_context(
            faction_b,
            event=f"外交阶段：{FACTION_NAMES[faction_a]}对你说：\"{msg_a}\"",
            phase="diplomacy",
        )
        resp_b = agent.run(ctx_b)
        engine.handle_response(faction_b, resp_b)
        msg_b = ctx_b.extra.get("_message", resp_b.dialogue or "...")

        # Deliver B's message to A
        engine.history_for(faction_a).append(speaker=faction_b, content=msg_b)


# ---- Deployment phase ----------------------------------------------------

def deployment_phase(
    state: GameState,
    engine: "WarGameEngine",
    agent: NPCAgent,
    player_input_fn: Callable[[str], list[dict]] | None = None,
) -> None:
    """Collect force allocations from player and AI factions.

    Args:
        player_input_fn: Callback that returns a list of deployment dicts.
            If None, player deploys all forces to defense equally.
    """
    state.deployments.clear()

    # Player deployment
    if not state.factions[PLAYER].is_eliminated:
        if player_input_fn is not None:
            player_allocs = player_input_fn("Enter deployments: ")
            state.deployments[PLAYER] = [
                Deployment(target=a["target"], troops=a["troops"], action=a["action"])
                for a in player_allocs
            ]
        else:
            # Default: equal defense
            state.deployments[PLAYER] = _default_defense(state, PLAYER)

    # AI deployment
    for faction_id in [FACTION_A, FACTION_B]:
        if state.factions[faction_id].is_eliminated:
            continue
        deployments = _ai_deploy(state, engine, agent, faction_id)
        state.deployments[faction_id] = deployments


def _ai_deploy(
    state: GameState,
    engine: "WarGameEngine",
    agent: NPCAgent,
    faction_id: str,
) -> list[Deployment]:
    """Get deployment from AI via agent.run. Falls back to equal defense on failure."""
    ctx = engine.build_context(
        faction_id,
        event="部署阶段：请分配你的全部兵力到防守和进攻。使用 deploy_forces 工具提交部署。",
        phase="deployment",
    )
    response = agent.run(ctx)
    engine.handle_response(faction_id, response)

    deployments = ctx.extra.get("_deployments")
    if deployments:
        return deployments

    # Fallback: equal defense
    logger.warning("AI %s failed to deploy, using default defense", faction_id)
    return _default_defense(state, faction_id)


def _default_defense(state: GameState, faction_id: str) -> list[Deployment]:
    """Equal defense across all owned cities."""
    owned = state.owned_cities(faction_id)
    pool = state.factions[faction_id].force_pool
    per_city = pool // len(owned) if owned else 0
    remainder = pool - per_city * len(owned) if owned else 0
    result: list[Deployment] = []
    for i, city in enumerate(owned):
        troops = per_city + (1 if i < remainder else 0)
        result.append(Deployment(target=city.id, troops=troops, action="defend"))
    return result


# ---- Resolution phase ----------------------------------------------------

def resolution_phase(
    state: GameState,
    engine: "WarGameEngine",
    agent: NPCAgent | None = None,
    player_negotiate_fn: Callable | None = None,
) -> list[BattleResult]:
    """Resolve all battles, handle 2v1 negotiations, apply production, check elimination.

    Returns the list of BattleResults for display.
    """
    raw_results = resolve_all_battles(state)
    final_results: list[BattleResult] = []

    for result in raw_results:
        if result.is_2v1 and result.winner == "":
            # Needs negotiation sub-game
            if agent is not None:
                resolved = negotiation_subgame(
                    state, engine, agent,
                    result.attacker_id,
                    result.second_attacker_id,
                    result.city_id,
                    result.attacker_troops,
                    result.second_attacker_troops,
                    result.defender_troops,
                    result.defender_id,
                    player_negotiate_fn=player_negotiate_fn,
                )
                final_results.append(resolved)
            else:
                # No agent → both withdraw (test fallback)
                final_results.append(BattleResult(
                    city_id=result.city_id,
                    attacker_id=result.attacker_id,
                    defender_id=result.defender_id,
                    attacker_troops=result.attacker_troops,
                    defender_troops=result.defender_troops,
                    winner=result.defender_id,
                    is_2v1=True,
                    second_attacker_id=result.second_attacker_id,
                    second_attacker_troops=result.second_attacker_troops,
                ))
        else:
            final_results.append(result)

    # Apply results to game state
    _apply_battle_results(state, final_results)

    # Production
    _apply_production(state, engine.config.production_per_city)

    # Elimination check
    _check_elimination(state)

    state.round_log = final_results
    return final_results


def _apply_battle_results(state: GameState, results: list[BattleResult]) -> None:
    """Mutate state based on battle outcomes."""
    for result in results:
        if result.city_captured:
            state.cities[result.city_id].owner = result.winner
            state.cities[result.city_id].captured_this_round = True
            # Return surviving troops to winner's pool
            state.factions[result.winner].force_pool += result.attacker_remaining
        else:
            # Defender keeps city, surviving defender troops return
            state.factions[result.defender_id].force_pool += result.defender_remaining

        # Deduct committed troops (they were already subtracted from pool at deployment)
        # Actually, deployment consumes the entire pool. Survivors return above.
        # Non-survivors are simply gone.


def _apply_production(state: GameState, production_per_city: int) -> None:
    """Add production for each owned city (captured this round excluded)."""
    for faction in state.active_factions():
        production = 0
        for city in state.owned_cities(faction.id):
            if not city.captured_this_round:
                production += production_per_city
        faction.force_pool += production

    # Reset captured_this_round flags
    for city in state.cities.values():
        city.captured_this_round = False


def _check_elimination(state: GameState) -> None:
    """Mark factions with no cities as eliminated."""
    for faction in state.factions.values():
        if faction.is_eliminated:
            continue
        if not state.owned_cities(faction.id):
            faction.is_eliminated = True
            faction.force_pool = 0
            logger.info("Faction %s has been eliminated!", faction.id)


# ---- Negotiation sub-game ------------------------------------------------

def negotiation_subgame(
    state: GameState,
    engine: "WarGameEngine",
    agent: NPCAgent,
    attacker_a_id: str,
    attacker_b_id: str,
    city_id: str,
    attacker_a_troops: int,
    attacker_b_troops: int,
    defender_troops: int,
    defender_id: str,
    player_negotiate_fn: Callable | None = None,
) -> BattleResult:
    """Run the 2v1 negotiation sub-game.

    1. Attrition phase (pure math)
    2. Negotiation rounds (agent.run or player input)
    3. Simultaneous withdraw/fight decision
    """
    # Phase 1: Attrition
    attrition = resolve_2v1_attrition(
        city_id, attacker_a_id, attacker_b_id, defender_id,
        attacker_a_troops, attacker_b_troops, defender_troops,
    )

    # Phase 2: Negotiation rounds
    max_rounds = engine.config.max_negotiation_rounds
    for round_num in range(1, max_rounds + 1):
        for faction_id in [attacker_a_id, attacker_b_id]:
            other_id = attacker_b_id if faction_id == attacker_a_id else attacker_a_id
            if faction_id == PLAYER:
                # Player negotiation handled by CLI
                pass
            else:
                ctx = engine.build_context(
                    faction_id,
                    event=(
                        f"2v1谈判：你和{FACTION_NAMES.get(other_id, other_id)}同时进攻了"
                        f"{city_id}。防守方已被消灭。你不知道自己剩余多少兵力。"
                        f"第{round_num}/{max_rounds}轮谈判。请发送消息。"
                    ),
                    phase="negotiation",
                )
                response = agent.run(ctx)
                engine.handle_response(faction_id, response)

    # Phase 3: Collect decisions
    decision_a = _get_decision(engine, agent, attacker_a_id, attacker_b_id, player_negotiate_fn)
    decision_b = _get_decision(engine, agent, attacker_b_id, attacker_a_id, player_negotiate_fn)

    return resolve_2v1_standoff(attrition, decision_a, decision_b)


def _get_decision(
    engine: "WarGameEngine",
    agent: NPCAgent,
    faction_id: str,
    opponent_id: str,
    player_fn: Callable | None = None,
) -> str:
    """Get withdraw/fight decision from a faction."""
    if faction_id == PLAYER and player_fn is not None:
        return player_fn()

    ctx = engine.build_context(
        faction_id,
        event=(
            "最终决定：谈判结束。请使用 final_decision 工具选择 'withdraw'（撤退）或 'fight'（战斗）。"
            "你不知道自己和对方各剩余多少兵力。"
        ),
        phase="final_decision",
    )
    response = agent.run(ctx)
    engine.handle_response(faction_id, response)
    return ctx.extra.get("_final_decision", "withdraw")  # default to withdraw on failure


# ---- Round report --------------------------------------------------------

def generate_round_report(state: GameState, battles: list[BattleResult]) -> str:
    """Generate a human-readable round report."""
    lines: list[str] = []
    lines.append(f"═══ 第{state.round_number}回合 结算报告 ═══")
    lines.append("")

    if not battles:
        lines.append("本回合无战斗发生。")
    else:
        for b in battles:
            att_name = FACTION_NAMES.get(b.attacker_id, b.attacker_id)
            def_name = FACTION_NAMES.get(b.defender_id, b.defender_id)
            if b.is_2v1:
                att2_name = FACTION_NAMES.get(b.second_attacker_id, b.second_attacker_id)
                lines.append(
                    f"[2v1战斗] {att_name}({b.attacker_troops}) 和 "
                    f"{att2_name}({b.second_attacker_troops}) "
                    f"进攻 {def_name} 的城市 {b.city_id}（防守 {b.defender_troops}）"
                )
                winner_name = FACTION_NAMES.get(b.winner, b.winner)
                if b.city_captured:
                    lines.append(f"  → {winner_name} 占领 {b.city_id}")
                else:
                    lines.append(f"  → {def_name} 保住 {b.city_id}（防守方兵力已耗尽）")
            else:
                if b.city_captured:
                    lines.append(
                        f"[战斗] {att_name} 进攻 {def_name} 的 {b.city_id}："
                        f" {att_name}出兵{b.attacker_troops}，防守{b.defender_troops}"
                        f" → {att_name}胜，占领{b.city_id}（剩余{b.attacker_remaining}）"
                    )
                else:
                    lines.append(
                        f"[战斗] {att_name} 进攻 {def_name} 的 {b.city_id}："
                        f" {att_name}出兵{b.attacker_troops}，防守{b.defender_troops}"
                        f" → {def_name}胜，守住{b.city_id}（剩余{b.defender_remaining}）"
                    )

    # Declaration vs reality
    lines.append("")
    lines.append("═══ 宣言 vs 实际 ═══")
    for faction_id, decl in state.declarations.items():
        name = FACTION_NAMES.get(faction_id, faction_id)
        actual_attacks = []
        for b in battles:
            if b.attacker_id == faction_id:
                actual_attacks.append(f"进攻{b.city_id}(出兵{b.attacker_troops})")
            if b.second_attacker_id == faction_id:
                actual_attacks.append(f"进攻{b.city_id}(出兵{b.second_attacker_troops})")
        if actual_attacks:
            actual_str = ", ".join(actual_attacks)
        else:
            actual_str = "全部防守"
        lines.append(f"{name} 宣言: \"{decl}\"  →  实际: {actual_str}")

    return "\n".join(lines)

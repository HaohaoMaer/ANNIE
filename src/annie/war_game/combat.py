"""Combat resolution — pure functions, no LLM involved.

1v1 attrition with defender-wins-ties.
2v1 attrition with equal damage split + negotiation standoff.
"""

from __future__ import annotations

from dataclasses import dataclass

from annie.war_game.game_state import BattleResult, GameState


@dataclass
class TwoVsOneAttritionResult:
    """Intermediate result after the attrition phase of a 2v1 battle."""

    city_id: str
    defender_id: str
    attacker_a_id: str
    attacker_b_id: str
    attacker_a_sent: int
    attacker_b_sent: int
    defender_sent: int
    remaining_a: int
    remaining_b: int


def resolve_battle(attacker_troops: int, defender_troops: int) -> tuple[int, int]:
    """Resolve a 1v1 battle. Returns (attacker_remaining, defender_remaining).

    Attrition: forces cancel. Ties go to the defender.
    """
    if defender_troops == 0:
        return (attacker_troops, 0)
    diff = attacker_troops - defender_troops
    if diff > 0:
        return (diff, 0)
    else:
        return (0, -diff)


def make_1v1_result(
    city_id: str,
    attacker_id: str,
    defender_id: str,
    attacker_troops: int,
    defender_troops: int,
) -> BattleResult:
    """Build a BattleResult for a 1v1 engagement."""
    att_rem, def_rem = resolve_battle(attacker_troops, defender_troops)
    city_captured = att_rem > 0 and def_rem == 0
    winner = attacker_id if city_captured else defender_id
    return BattleResult(
        city_id=city_id,
        attacker_id=attacker_id,
        defender_id=defender_id,
        attacker_troops=attacker_troops,
        defender_troops=defender_troops,
        winner=winner,
        attacker_remaining=att_rem,
        defender_remaining=def_rem,
        city_captured=city_captured,
    )


def resolve_2v1_attrition(
    city_id: str,
    attacker_a_id: str,
    attacker_b_id: str,
    defender_id: str,
    attacker_a_troops: int,
    attacker_b_troops: int,
    defender_troops: int,
) -> TwoVsOneAttritionResult:
    """Phase 1 of 2v1: defender damage split equally between two attackers.

    Returns remaining forces per attacker (hidden from both during negotiation).
    """
    half_damage = defender_troops / 2
    remaining_a = max(0, attacker_a_troops - int(half_damage + 0.5))  # round up for first
    remaining_b = max(0, attacker_b_troops - int(half_damage))        # round down for second
    # Ensure total damage dealt equals defender troops when possible
    # Simpler: split evenly, remainder goes to the one who sent more
    damage_a = defender_troops // 2
    damage_b = defender_troops - damage_a  # second absorbs the odd unit
    remaining_a = max(0, attacker_a_troops - damage_a)
    remaining_b = max(0, attacker_b_troops - damage_b)
    return TwoVsOneAttritionResult(
        city_id=city_id,
        defender_id=defender_id,
        attacker_a_id=attacker_a_id,
        attacker_b_id=attacker_b_id,
        attacker_a_sent=attacker_a_troops,
        attacker_b_sent=attacker_b_troops,
        defender_sent=defender_troops,
        remaining_a=remaining_a,
        remaining_b=remaining_b,
    )


def resolve_2v1_standoff(
    attrition: TwoVsOneAttritionResult,
    decision_a: str,
    decision_b: str,
) -> BattleResult:
    """Phase 2 of 2v1: withdraw/fight matrix after negotiation.

    Both withdraw → city stays with defender (0 garrison).
    One withdraws → the other takes the city.
    Both fight → final attrition between the two.
    """
    city_id = attrition.city_id
    remaining_a = attrition.remaining_a
    remaining_b = attrition.remaining_b

    base = BattleResult(
        city_id=city_id,
        attacker_id=attrition.attacker_a_id,
        defender_id=attrition.defender_id,
        attacker_troops=attrition.attacker_a_sent,
        defender_troops=attrition.defender_sent,
        is_2v1=True,
        second_attacker_id=attrition.attacker_b_id,
        second_attacker_troops=attrition.attacker_b_sent,
    )

    if decision_a == "withdraw" and decision_b == "withdraw":
        # City stays with defender (0 garrison), both attackers get troops back
        base.winner = attrition.defender_id
        base.city_captured = False
        base.attacker_remaining = remaining_a
        base.defender_remaining = 0
        return base

    if decision_a == "fight" and decision_b == "withdraw":
        # A takes the city
        base.winner = attrition.attacker_a_id
        base.city_captured = True
        base.attacker_remaining = remaining_a
        base.defender_remaining = 0
        return base

    if decision_a == "withdraw" and decision_b == "fight":
        # B takes the city
        base.winner = attrition.attacker_b_id
        base.city_captured = True
        base.attacker_remaining = remaining_b
        base.defender_remaining = 0
        return base

    # Both fight — final attrition between the two remaining forces
    a_rem, b_rem = resolve_battle(remaining_a, remaining_b)
    if a_rem > 0:
        base.winner = attrition.attacker_a_id
        base.city_captured = True
        base.attacker_remaining = a_rem
    elif b_rem > 0:
        base.winner = attrition.attacker_b_id
        base.city_captured = True
        base.attacker_remaining = b_rem
    else:
        # Both wiped out — city stays with original defender (0 garrison)
        base.winner = attrition.defender_id
        base.city_captured = False
        base.attacker_remaining = 0
    base.defender_remaining = 0
    return base


def resolve_all_battles(state: GameState) -> list[BattleResult]:
    """Resolve all deployments in a round simultaneously.

    Returns a list of BattleResults. 2v1 situations are detected but NOT
    fully resolved here — they return a sentinel with is_2v1=True for the
    engine to handle via the negotiation sub-game.

    For non-2v1 battles, results are fully resolved and the returned
    BattleResults include attacker/defender remaining.
    """
    # Collect all attacks targeting each city
    attacks_by_city: dict[str, list[tuple[str, int]]] = {}  # city_id → [(faction_id, troops)]
    defense_by_city: dict[str, int] = {}  # city_id → defending troops

    for faction_id, deployments in state.deployments.items():
        for dep in deployments:
            if dep.action == "attack":
                attacks_by_city.setdefault(dep.target, []).append((faction_id, dep.troops))
            elif dep.action == "defend":
                defense_by_city[dep.target] = defense_by_city.get(dep.target, 0) + dep.troops

    results: list[BattleResult] = []

    for city_id, attackers in attacks_by_city.items():
        city = state.cities[city_id]
        defender_id = city.owner
        defender_troops = defense_by_city.get(city_id, 0)

        if len(attackers) == 1:
            att_id, att_troops = attackers[0]
            results.append(make_1v1_result(
                city_id=city_id,
                attacker_id=att_id,
                defender_id=defender_id,
                attacker_troops=att_troops,
                defender_troops=defender_troops,
            ))
        elif len(attackers) == 2:
            # 2v1 — return a sentinel for the engine to handle via negotiation
            att_a_id, att_a_troops = attackers[0]
            att_b_id, att_b_troops = attackers[1]
            results.append(BattleResult(
                city_id=city_id,
                attacker_id=att_a_id,
                defender_id=defender_id,
                attacker_troops=att_a_troops,
                defender_troops=defender_troops,
                winner="",  # not yet resolved
                is_2v1=True,
                second_attacker_id=att_b_id,
                second_attacker_troops=att_b_troops,
            ))

    return results

"""Unit tests for combat resolution."""

from annie.war_game.combat import (
    TwoVsOneAttritionResult,
    make_1v1_result,
    resolve_2v1_attrition,
    resolve_2v1_standoff,
    resolve_all_battles,
    resolve_battle,
)
from annie.war_game.game_state import Deployment
from annie.war_game.map_preset import FACTION_A, FACTION_B, PLAYER, create_default_state


class TestResolve1v1:
    def test_attacker_wins(self) -> None:
        att_rem, def_rem = resolve_battle(500, 300)
        assert att_rem == 200
        assert def_rem == 0

    def test_defender_wins(self) -> None:
        att_rem, def_rem = resolve_battle(200, 500)
        assert att_rem == 0
        assert def_rem == 300

    def test_tie_goes_to_defender(self) -> None:
        att_rem, def_rem = resolve_battle(300, 300)
        assert att_rem == 0
        assert def_rem == 0  # defender keeps city but 0 remaining

    def test_undefended_city(self) -> None:
        att_rem, def_rem = resolve_battle(100, 0)
        assert att_rem == 100
        assert def_rem == 0


class TestMake1v1Result:
    def test_attacker_captures(self) -> None:
        r = make_1v1_result("P3", "faction_a", "player", 500, 300)
        assert r.city_captured is True
        assert r.winner == "faction_a"
        assert r.attacker_remaining == 200

    def test_defender_holds(self) -> None:
        r = make_1v1_result("P3", "faction_a", "player", 200, 500)
        assert r.city_captured is False
        assert r.winner == "player"
        assert r.defender_remaining == 300

    def test_tie_defender_holds(self) -> None:
        r = make_1v1_result("A4", "player", "faction_a", 300, 300)
        assert r.city_captured is False
        assert r.winner == "faction_a"


class TestResolve2v1:
    def test_attrition_equal_split(self) -> None:
        r = resolve_2v1_attrition(
            "P3", "faction_a", "faction_b", "player",
            400, 500, 300,
        )
        # 300 defender damage split: 150 each
        assert r.remaining_a == 400 - 150  # 250
        assert r.remaining_b == 500 - 150  # 350

    def test_attrition_odd_damage(self) -> None:
        r = resolve_2v1_attrition(
            "P3", "faction_a", "faction_b", "player",
            400, 500, 301,
        )
        # 301 // 2 = 150 for A, 301 - 150 = 151 for B
        assert r.remaining_a == 400 - 150  # 250
        assert r.remaining_b == 500 - 151  # 349

    def test_both_withdraw_city_stays(self) -> None:
        attrition = TwoVsOneAttritionResult(
            city_id="P3", defender_id="player",
            attacker_a_id="faction_a", attacker_b_id="faction_b",
            attacker_a_sent=400, attacker_b_sent=500, defender_sent=300,
            remaining_a=250, remaining_b=350,
        )
        r = resolve_2v1_standoff(attrition, "withdraw", "withdraw")
        assert r.winner == "player"
        assert r.city_captured is False
        assert r.attacker_remaining == 250  # A gets troops back

    def test_a_fights_b_withdraws(self) -> None:
        attrition = TwoVsOneAttritionResult(
            city_id="P3", defender_id="player",
            attacker_a_id="faction_a", attacker_b_id="faction_b",
            attacker_a_sent=400, attacker_b_sent=500, defender_sent=300,
            remaining_a=250, remaining_b=350,
        )
        r = resolve_2v1_standoff(attrition, "fight", "withdraw")
        assert r.winner == "faction_a"
        assert r.city_captured is True
        assert r.attacker_remaining == 250

    def test_a_withdraws_b_fights(self) -> None:
        attrition = TwoVsOneAttritionResult(
            city_id="P3", defender_id="player",
            attacker_a_id="faction_a", attacker_b_id="faction_b",
            attacker_a_sent=400, attacker_b_sent=500, defender_sent=300,
            remaining_a=250, remaining_b=350,
        )
        r = resolve_2v1_standoff(attrition, "withdraw", "fight")
        assert r.winner == "faction_b"
        assert r.city_captured is True
        assert r.attacker_remaining == 350

    def test_both_fight_stronger_wins(self) -> None:
        attrition = TwoVsOneAttritionResult(
            city_id="P3", defender_id="player",
            attacker_a_id="faction_a", attacker_b_id="faction_b",
            attacker_a_sent=400, attacker_b_sent=500, defender_sent=300,
            remaining_a=250, remaining_b=350,
        )
        r = resolve_2v1_standoff(attrition, "fight", "fight")
        # 250 vs 350: B wins with 100 remaining
        assert r.winner == "faction_b"
        assert r.city_captured is True
        assert r.attacker_remaining == 100

    def test_both_fight_equal_city_returns(self) -> None:
        attrition = TwoVsOneAttritionResult(
            city_id="P3", defender_id="player",
            attacker_a_id="faction_a", attacker_b_id="faction_b",
            attacker_a_sent=400, attacker_b_sent=400, defender_sent=300,
            remaining_a=250, remaining_b=250,
        )
        r = resolve_2v1_standoff(attrition, "fight", "fight")
        # Equal forces: defender of the attacker fight is A (first), tie → defender wins
        # But here both are attackers. resolve_battle(250, 250) → (0, 0)
        # Both wiped out → city stays with original defender
        assert r.winner == "player"
        assert r.city_captured is False


class TestResolveAllBattles:
    def test_single_1v1(self) -> None:
        state = create_default_state()
        state.deployments = {
            FACTION_A: [
                Deployment(target="P4", troops=400, action="attack"),
                Deployment(target="A1", troops=100, action="defend"),
                Deployment(target="A2", troops=100, action="defend"),
                Deployment(target="A3", troops=100, action="defend"),
                Deployment(target="A4", troops=200, action="defend"),
                Deployment(target="A5", troops=100, action="defend"),
            ],
            PLAYER: [
                Deployment(target="P1", troops=200, action="defend"),
                Deployment(target="P2", troops=200, action="defend"),
                Deployment(target="P3", troops=200, action="defend"),
                Deployment(target="P4", troops=300, action="defend"),
                Deployment(target="P5", troops=100, action="defend"),
            ],
            FACTION_B: [
                Deployment(target="B1", troops=200, action="defend"),
                Deployment(target="B2", troops=200, action="defend"),
                Deployment(target="B3", troops=200, action="defend"),
                Deployment(target="B4", troops=200, action="defend"),
                Deployment(target="B5", troops=200, action="defend"),
            ],
        }
        results = resolve_all_battles(state)
        assert len(results) == 1
        r = results[0]
        assert r.city_id == "P4"
        assert r.attacker_id == FACTION_A
        assert r.city_captured is True  # 400 vs 300

    def test_2v1_detected(self) -> None:
        state = create_default_state()
        # Both A and B attack P3 (which is adjacent to B4 and P1)
        # A attacks via... wait, A doesn't border P3. Let me pick a city both can attack.
        # A borders P4 (via A3, A4... no, A4 borders B3).
        # Actually: A3-P4 and A5-P2 are the A-P borders.
        # B2-P5 and B4-P3 are the B-P borders.
        # No city is attackable by both A and B, since A borders {P4, P2} and B borders {P5, P3}.
        # For a 2v1 to happen, one of them would need to have captured territory first.
        # Let's simulate that scenario.
        state.cities["P3"].owner = FACTION_A  # A captured P3
        # Now A owns P3 which is adjacent to B4. And B owns B4 adjacent to P3.
        # If both A (from P3 direction) and player (no, player lost P3)...
        # Actually for a 2v1, we need two factions attacking the same enemy city.
        # Let's say B captured P5, so now both A (bordering P2-A5) and B (owning P5, bordering P3)
        # Hmm, this is getting complicated. Let me just set up deployments directly.

        # Give A adjacency to B1 by having A own B3 (captured earlier)
        state.cities["B3"].owner = FACTION_A
        # Now both P (via B2-P5, B4-P3... but P borders B4 via P3) can attack B4,
        # and A (via B3 which A now owns, B3 borders B1) can attack B1.
        # Let's make both P and A attack B4.
        # P borders B4 via P3. A borders B4 via... A owns B3, B3 borders B1, not B4.
        # B3 adj: [B1, B5, A4]. Nope.
        # Let me try differently: A owns A4 which borders B3. If A also owns B3 (adj B1, B5, A4),
        # then A borders B5 (via B3) and B1 (via B3).
        # P borders B4 (via P3) and B2 (via P5).
        # For 2v1 on B1: only A (via B3) can reach it. Not enough.
        # For 2v1 on B2: P can reach via P5. Can A reach B2? B2 adj: [B1, B4, P5]. A doesn't own any of those.

        # Simplest approach: just manually set up attack deployments and let the function work.
        # The function only looks at deployments, not adjacency validation.
        state.deployments = {
            PLAYER: [
                Deployment(target="B4", troops=300, action="attack"),
                Deployment(target="P1", troops=200, action="defend"),
                Deployment(target="P2", troops=200, action="defend"),
                Deployment(target="P4", troops=100, action="defend"),
                Deployment(target="P5", troops=200, action="defend"),
            ],
            FACTION_A: [
                Deployment(target="B4", troops=400, action="attack"),
                Deployment(target="A1", troops=100, action="defend"),
                Deployment(target="A2", troops=100, action="defend"),
                Deployment(target="A3", troops=100, action="defend"),
                Deployment(target="A4", troops=100, action="defend"),
                Deployment(target="A5", troops=100, action="defend"),
                Deployment(target="P3", troops=50, action="defend"),
                Deployment(target="B3", troops=50, action="defend"),
            ],
            FACTION_B: [
                Deployment(target="B1", troops=200, action="defend"),
                Deployment(target="B2", troops=300, action="defend"),
                Deployment(target="B4", troops=200, action="defend"),
                Deployment(target="B5", troops=300, action="defend"),
            ],
        }
        results = resolve_all_battles(state)
        assert len(results) == 1
        r = results[0]
        assert r.is_2v1 is True
        assert r.city_id == "B4"
        assert r.winner == ""  # not yet resolved (needs negotiation)

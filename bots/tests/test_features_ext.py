"""Step 7: the 18 candidate features.

These are candidates, not commitments — each still has to win an ablation
gate. The tests pin what each one *means*, so a screen that says "no effect"
is a statement about the game rather than about a bug.
"""
from __future__ import annotations

import random

import pytest

from bots._engine import (
    Claim,
    Crystal,
    CrystalCard,
    Game,
    PointCard,
    Token,
    TradeCard,
    UpgradeCard,
)
from bots import sim
from bots.features import (
    CORE_FEATURES,
    EXTENDED_FEATURES,
    FEATURES,
    SCREEN_ORDER,
    Ctx,
    Scales,
)

Y, G, B, M = Crystal.YELLOW, Crystal.GREEN, Crystal.TURQUOISE, Crystal.MAGENTA
CREATE_2 = CrystalCard(((Y, 2),), "Create 2")
UPGRADE_2 = UpgradeCard(2, "Upgrade 2")
UPGRADE_3 = UpgradeCard(3, "Triple")
TRADE_2Y_1B = TradeCard(((Y, 2),), ((B, 1),), "2Y->1B")
TRADE_DOWN = TradeCard(((M, 1),), ((Y, 3),), "1M->3Y")


@pytest.fixture(autouse=True)
def _clear():
    sim.clear_cache()
    yield


def build(caravan=(0, 0, 0, 0), hand=(), played=(), point_cards=(), row=None,
          n=2, pid=0, current=0):
    g = Game([f"P{i}" for i in range(n)], seed=1)
    p = g.players[pid]
    p.caravan = list(caravan)
    p.hand = list(hand)
    p.played = list(played)
    p.point_cards = list(point_cards)
    if row is not None:
        g.point_row = list(row) + [None] * (Game.POINT_ROW - len(row))
    g.current = current
    return g


def val(key, game, pid=0, before=None, depth=2, **ctx_kw):
    return FEATURES[key].fn(before or game, game, pid, Ctx(game, depth, **ctx_kw))


# --------------------------------------------------------------------------
# Registry hygiene
# --------------------------------------------------------------------------

def test_eighteen_candidates_registered():
    assert len(EXTENDED_FEATURES) == 18
    assert len(FEATURES) == 30
    assert not set(EXTENDED_FEATURES) & set(CORE_FEATURES)


def test_screen_order_covers_every_candidate():
    assert set(SCREEN_ORDER) == set(EXTENDED_FEATURES)


def test_opponent_features_are_screened_last():
    """Step 6 measured that ignoring opponents costs nothing, so this family
    is both least likely to pay and most expensive to compute."""
    opponent = [k for k in SCREEN_ORDER if FEATURES[k].group == "opponent"]
    tail = SCREEN_ORDER[-len(opponent):]
    assert set(opponent) == set(tail)


def test_every_candidate_has_a_scale():
    s = Scales.load()
    for k in EXTENDED_FEATURES:
        assert k in s.values, f"{k} needs `calibrate --features new --merge`"


def test_no_candidate_disturbed_the_core_scales():
    """Adding features must not move the twelve already tuned against.

    Re-measuring an existing scale shifts it by sampling noise alone, and
    every weight fitted against the old divisor then means something slightly
    different. calibrate --merge keeps them verbatim.
    """
    s = Scales.load()
    known = {"golem_points": 19.76, "throughput": 0.28, "cry_y": 2.08}
    for k, expected in known.items():
        assert s.get(k) == pytest.approx(expected, abs=0.02), k


# --------------------------------------------------------------------------
# Engine shape
# --------------------------------------------------------------------------

def test_card_count():
    assert val("card_count", build(hand=[CREATE_2], played=[UPGRADE_2])) == 2.0
    assert val("card_count", build()) == 0.0


def test_upgrade_steps_sums_owned_upgrade_cards():
    g = build(hand=[UPGRADE_2, CREATE_2], played=[UPGRADE_3])
    assert val("upgrade_steps", g) == 5.0


def test_feedable_trades_needs_affordability_and_profit():
    # 4 yellow affords 2Y->1B twice, net +1 each
    assert val("feedable_trades", build(caravan=(4, 0, 0, 0), hand=[TRADE_2Y_1B])) == 2.0
    # unaffordable
    assert val("feedable_trades", build(caravan=(1, 0, 0, 0), hand=[TRADE_2Y_1B])) == 0.0
    # trading down the chain is not profit
    assert val("feedable_trades", build(caravan=(0, 0, 0, 3), hand=[TRADE_DOWN])) == 0.0


def test_feedable_trades_counts_the_played_pile_too():
    """Unlike playable_now, this is about the engine you own, not this turn."""
    g = build(caravan=(4, 0, 0, 0), played=[TRADE_2Y_1B])
    assert val("feedable_trades", g) == 2.0


def test_color_coverage_counts_producible_colours():
    # a card that gains blue covers blue only
    assert val("color_coverage", build(hand=[CrystalCard(((B, 1),), "+1B")])) == 1.0
    # a 3-step upgrade can climb to magenta, so it covers G, B and M
    assert val("color_coverage", build(hand=[UPGRADE_3])) == 3.0
    # a 2-step upgrade reaches blue but not magenta
    assert val("color_coverage", build(hand=[UPGRADE_2])) == 2.0
    assert val("color_coverage", build(hand=[CREATE_2])) == 0.0


def test_free_space_is_room_under_the_cap():
    assert val("free_space", build(caravan=(0, 0, 0, 0))) == 10.0
    assert val("free_space", build(caravan=(3, 3, 2, 2))) == 0.0


def test_overflow_waste_reads_the_engines_discard():
    g = build(caravan=(9, 0, 0, 0), hand=[CREATE_2])
    before = g.clone()
    g.apply_action(__import__("bots._engine", fromlist=["PlayCrystal"]).PlayCrystal(0))
    assert g.last_discard == [1, 0, 0, 0]
    assert val("overflow_waste", g, before=before) == 1.0     # one yellow, YE 1


def test_overflow_waste_is_zero_for_seats_that_did_not_act():
    g = build(caravan=(9, 0, 0, 0), hand=[CREATE_2])
    before = g.clone()
    g.apply_action(__import__("bots._engine", fromlist=["PlayCrystal"]).PlayCrystal(0))
    assert val("overflow_waste", g, pid=1, before=before) == 0.0


def test_golem_count_is_separate_from_points():
    g = build(point_cards=[PointCard(((Y, 2),), 20, "a"), PointCard(((Y, 2),), 4, "b")])
    assert val("golem_count", g) == 2.0
    assert val("golem_points", g) == 24.0


def test_race_lead_compares_golem_counts():
    g = build(point_cards=[PointCard(((Y, 1),), 5, "a")] * 3)
    g.players[1].point_cards = [PointCard(((Y, 1),), 5, "b")]
    assert val("race_lead", g) == 2.0
    assert val("race_lead", g, pid=1) == -2.0


def test_row_bounty_prefers_a_cheap_slot_with_crystals_on_it():
    g = build()
    g.merchant_row = [None] * 6
    g.merchant_row[0] = CrystalCard(((Y, 2),), "+2Y")        # output 2, index 0
    g.merchant_row[3] = CrystalCard(((Y, 2),), "+2Y")        # output 2, index 3
    g.row_crystals[3][M] = 1                                  # +4 YE sitting on it
    # slot 0: 2 + 0 - 0 = 2 ; slot 3: 2 + 4 - 3 = 3
    assert val("row_bounty", g) == 3.0


# --------------------------------------------------------------------------
# Target shaping
# --------------------------------------------------------------------------

def test_option_breadth_rewards_several_reachable_golems():
    payable = PointCard(((G, 2),), 10, "2G")
    one = build(caravan=(0, 2, 0, 0), row=[payable])
    two = build(caravan=(0, 2, 0, 0), row=[payable, payable])
    assert val("option_breadth", two) > val("option_breadth", one)


def test_option_breadth_discounts_harder_than_best_target():
    """The square makes distance hurt more, which is the point of the feature."""
    golem = PointCard(((B, 2),), 12, "2B")
    g = build(caravan=(0, 2, 0, 0), hand=[UPGRADE_2], row=[golem])   # TTC 1
    assert val("option_breadth", g) == pytest.approx(12 / 4)          # /(1+1)^2
    assert val("best_target", g) == pytest.approx(12 / 2)


def test_shaped_target_reproduces_best_target_at_unit_exponents():
    golem = PointCard(((B, 2),), 12, "2B")
    g = build(caravan=(0, 2, 0, 0), hand=[UPGRADE_2], row=[golem])
    assert val("shaped_target", g, alpha=1.0, beta=1.0) == pytest.approx(
        val("best_target", g))


def test_shaped_target_exponents_change_the_trade_off():
    cheap_near = PointCard(((G, 2),), 8, "2G=8")        # payable now
    rich_far = PointCard(((M, 4),), 20, "4M=20")        # far away
    g = build(caravan=(0, 2, 0, 0), row=[cheap_near, rich_far])
    # beta high punishes distance, so the near one wins by more
    low_beta = val("shaped_target", g, alpha=1.0, beta=0.5)
    high_beta = val("shaped_target", g, alpha=1.0, beta=3.0)
    assert high_beta <= low_beta


def test_clock_lead_is_zero_when_scores_are_level():
    g = build()
    assert val("clock_lead", g) == 0.0


def test_clock_lead_tracks_the_score_lead():
    g = build(point_cards=[PointCard(((Y, 2),), 30, "a")])
    assert val("clock_lead", g) > 0
    assert val("clock_lead", g, pid=1) < 0


# --------------------------------------------------------------------------
# Opponent modelling
# --------------------------------------------------------------------------

def test_snipe_risk_fires_when_an_opponent_is_at_least_as_fast():
    golem = PointCard(((G, 2),), 12, "2G")
    g = build(caravan=(0, 2, 0, 0), row=[golem])
    g.players[1].caravan = [0, 2, 0, 0]          # equally ready
    assert val("snipe_risk", g) == 1.0


def test_snipe_risk_is_zero_when_you_are_clearly_ahead():
    golem = PointCard(((M, 4),), 20, "4M")
    g = build(caravan=(0, 0, 0, 4), row=[golem])     # payable now
    g.players[1].caravan = [1, 0, 0, 0]              # nowhere near
    assert val("snipe_risk", g) == 0.0


def test_contested_target_discounts_a_golem_an_opponent_reaches_first():
    golem = PointCard(((G, 2),), 20, "2G=20")
    mine = build(caravan=(0, 1, 0, 0), hand=[CREATE_2], row=[golem])
    mine.players[1].caravan = [0, 2, 0, 0]       # they can take it now, I cannot
    contested = val("contested_target", mine)
    plain = val("best_target", mine)
    assert contested < plain


def test_contested_target_equals_best_target_when_uncontested():
    golem = PointCard(((G, 2),), 20, "2G=20")
    g = build(caravan=(0, 2, 0, 0), row=[golem])
    g.players[1].caravan = [0, 0, 0, 0]
    g.players[1].hand = []
    assert val("contested_target", g) == pytest.approx(val("best_target", g))


def test_contested_tokens_ignores_slots_an_opponent_wins():
    payable = PointCard(((G, 2),), 10, "2G")
    g = build(caravan=(0, 1, 0, 0), row=[payable])
    g.players[1].caravan = [0, 2, 0, 0]          # strictly faster to slot 0
    assert val("contested_tokens", g) == 0.0


def test_denial_counts_only_what_i_took_from_under_an_opponent():
    golem = PointCard(((G, 2),), 15, "2G=15")
    g = build(caravan=(0, 2, 0, 0), row=[golem])
    g.players[1].caravan = [0, 2, 0, 0]          # they were ready too
    before = g.clone()
    g.apply_action(Claim(0))
    assert val("denial", g, before=before) == 15.0


def test_denial_is_zero_when_nobody_wanted_it():
    golem = PointCard(((G, 2),), 15, "2G=15")
    g = build(caravan=(0, 2, 0, 0), row=[golem])
    g.players[1].caravan = [0, 0, 0, 0]
    g.players[1].hand = []
    before = g.clone()
    g.apply_action(Claim(0))
    assert val("denial", g, before=before) == 0.0


def test_response_threat_is_zero_before_the_end_is_triggered():
    g = build(row=[PointCard(((G, 2),), 15, "a")])
    assert val("response_threat", g) == 0.0


def test_response_threat_counts_opponents_who_can_still_claim():
    golem = PointCard(((G, 2),), 15, "2G=15")
    g = build(row=[golem], n=2, current=1)
    g._end_triggered = True
    g.players[1].caravan = [0, 2, 0, 0]          # can claim immediately
    assert val("response_threat", g) == 15.0


def test_opp_fit_bounty_is_zero_when_it_is_my_own_turn():
    g = build(current=0)
    assert val("opp_fit_bounty", g, pid=0) == 0.0


# --------------------------------------------------------------------------
# Whole-set safety
# --------------------------------------------------------------------------

@pytest.mark.parametrize("n_players", [2, 3])
def test_no_feature_raises_or_mutates_over_real_play(n_players):
    rng = random.Random(4)
    g = Game([f"P{i}" for i in range(n_players)], seed=4)
    for _ in range(60):
        acts = g.legal_actions(pruned=True)
        if not acts or g.game_over:
            break
        before = g.clone()
        g.apply_action(rng.choice(acts))
        snap = ([list(p.caravan) for p in g.players],
                [len(p.hand) for p in g.players],
                [c.name if c else None for c in g.point_row])
        ctx = Ctx(g, 2)
        for key, spec in FEATURES.items():
            v = spec.fn(before, g, 0, ctx)
            assert isinstance(v, float) and v == v, key      # no NaN
            assert abs(v) < 1e6, (key, v)
        after = ([list(p.caravan) for p in g.players],
                 [len(p.hand) for p in g.players],
                 [c.name if c else None for c in g.point_row])
        assert snap == after, "a feature mutated the game"

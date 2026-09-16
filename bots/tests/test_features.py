"""Step 3: features, the value function, and explain().

One test per feature on a hand-built position, so a regression names the
feature it broke.
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
    Rest,
    Token,
    TradeCard,
    UpgradeCard,
)
from bots import features as F
from bots import sim
from bots.features import (
    CORE_FEATURES,
    Ctx,
    FEATURES,
    Scales,
    Weights,
    evaluate,
    explain,
    phase_of,
    score_actions,
    terminal_value,
)

Y, G, B, M = Crystal.YELLOW, Crystal.GREEN, Crystal.TURQUOISE, Crystal.MAGENTA

CREATE_2 = CrystalCard(((Y, 2),), "Create 2")
UPGRADE_2 = UpgradeCard(2, "Upgrade 2")
TRADE_2Y_1B = TradeCard(((Y, 2),), ((B, 1),), "2Y->1B")
TRADE_DOWN = TradeCard(((M, 1),), ((Y, 3),), "1M->3Y")


@pytest.fixture(autouse=True)
def _clear():
    sim.clear_cache()
    yield


def build(caravan=(0, 0, 0, 0), hand=(), played=(), point_cards=(), tokens=(),
          row=None, n=2, pid=0, tokens_row=True):
    """A game with one seat's state set by hand."""
    g = Game([f"P{i}" for i in range(n)], seed=1)
    p = g.players[pid]
    p.caravan = list(caravan)
    p.hand = list(hand)
    p.played = list(played)
    p.point_cards = list(point_cards)
    p.tokens = list(tokens)
    if row is not None:
        g.point_row = list(row) + [None] * (Game.POINT_ROW - len(row))
    if not tokens_row:
        g.point_tokens = [[] for _ in range(Game.POINT_ROW)]
    return g


def val(key, game, pid=0, depth=3):
    return FEATURES[key].fn(game, game, pid, Ctx(game, depth))


UNIT = Scales.unit()


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

def test_core_set_is_the_briefs_twelve():
    assert len(CORE_FEATURES) == 12
    assert set(CORE_FEATURES) == {
        "golem_points", "token_points", "cry_y", "cry_g", "cry_b", "cry_m",
        "best_target", "token_race", "throughput", "playable_now",
        "exhausted", "dead_hand",
    }


def test_symmetric_flags():
    """Only features meaningful for an opponent join the -lambda term."""
    sym = {k for k, s in FEATURES.items() if s.symmetric}
    assert sym == {"golem_points", "token_points", "best_target", "throughput"}


def test_every_feature_has_a_description():
    for spec in FEATURES.values():
        assert spec.description and spec.group


# --------------------------------------------------------------------------
# 1-2: score features
# --------------------------------------------------------------------------

def test_golem_points():
    g = build(point_cards=[PointCard(((Y, 2),), 6, "a"), PointCard(((G, 2),), 8, "b")])
    assert val("golem_points", g) == 14.0
    assert val("golem_points", g, pid=1) == 0.0


def test_token_points_weights_copper_three_and_silver_one():
    g = build(tokens=[Token.COPPER, Token.COPPER, Token.SILVER])
    assert val("token_points", g) == 7.0


# --------------------------------------------------------------------------
# 3-6: caravan
# --------------------------------------------------------------------------

def test_crystal_counts():
    g = build(caravan=(3, 2, 1, 4))
    assert (val("cry_y", g), val("cry_g", g), val("cry_b", g), val("cry_m", g)) \
        == (3.0, 2.0, 1.0, 4.0)


# --------------------------------------------------------------------------
# 7: best_target
# --------------------------------------------------------------------------

def test_best_target_prefers_points_over_distance():
    """A payable 10-pointer scores 10; a 20-pointer three turns out scores 5."""
    payable = PointCard(((G, 2),), 10, "2G=10")
    far = PointCard(((M, 5),), 20, "5M=20")
    g = build(caravan=(0, 2, 0, 0), row=[payable, far])
    assert sim.ttc(g.players[0], payable) == 0.0
    assert val("best_target", g) == pytest.approx(10.0)


def test_best_target_uses_the_best_slot_not_the_first():
    cheap = PointCard(((Y, 2),), 4, "2Y=4")
    rich = PointCard(((G, 2),), 12, "2G=12")
    g = build(caravan=(2, 2, 0, 0), row=[cheap, rich])
    assert val("best_target", g) == pytest.approx(12.0)


def test_best_target_discounts_by_ttc():
    golem = PointCard(((B, 2),), 12, "2B=12")
    near = build(caravan=(0, 2, 0, 0), hand=[UPGRADE_2], row=[golem])   # TTC 1
    assert sim.ttc(near.players[0], golem) == 1.0
    assert val("best_target", near) == pytest.approx(6.0)               # 12/(1+1)


def test_best_target_is_zero_on_an_empty_row():
    g = build(row=[])
    assert val("best_target", g) == 0.0


# --------------------------------------------------------------------------
# 9: token_race
# --------------------------------------------------------------------------

def test_token_race_values_the_copper_slot_at_three():
    payable = PointCard(((G, 2),), 10, "2G")
    far = PointCard(((M, 5),), 20, "5M")
    g = build(caravan=(0, 2, 0, 0), row=[payable, far])
    # slot 0 copper: 3/(1+0) = 3. slot 1 silver: 1/(1+ttc(5M)), small.
    got = val("token_race", g)
    assert got > 3.0
    assert got < 3.0 + 1.0


def test_token_race_ignores_empty_piles():
    payable = PointCard(((G, 2),), 10, "2G")
    g = build(caravan=(0, 2, 0, 0), row=[payable], tokens_row=False)
    assert val("token_race", g) == 0.0


def test_token_race_follows_the_silver_reflow():
    """When copper runs out the engine slides silver into slot 0, so the slot
    is then worth 1, not 3."""
    payable = PointCard(((G, 2),), 10, "2G")
    g = build(caravan=(0, 2, 0, 0), row=[payable])
    g.point_tokens[0] = []
    g.point_tokens[1] = [Token.SILVER] * 4
    g._reflow_tokens()
    assert g.point_tokens[0] and int(g.point_tokens[0][-1]) == 1
    assert val("token_race", g) == pytest.approx(1.0)


# --------------------------------------------------------------------------
# 11: throughput
# --------------------------------------------------------------------------

def test_throughput_matches_the_simulator():
    g = build(hand=[CREATE_2], played=[UPGRADE_2])
    assert val("throughput", g) == pytest.approx(sim.throughput(g.players[0]))
    assert val("throughput", g) == pytest.approx(4 / 3)


# --------------------------------------------------------------------------
# 16: playable_now
# --------------------------------------------------------------------------

def test_playable_now_counts_crystal_gains():
    g = build(hand=[CREATE_2])
    assert val("playable_now", g) == 2.0


def test_playable_now_caps_upgrades_by_what_the_caravan_can_absorb():
    # one blue can take exactly one step; a 2-step card only gets 1 of use
    assert val("playable_now", build(caravan=(0, 0, 1, 0), hand=[UPGRADE_2])) == 1.0
    # one yellow can climb three levels, so a 2-step card is fully usable
    assert val("playable_now", build(caravan=(1, 0, 0, 0), hand=[UPGRADE_2])) == 2.0
    # nothing upgradable at all
    assert val("playable_now", build(caravan=(0, 0, 0, 5), hand=[UPGRADE_2])) == 0.0


def test_playable_now_counts_affordable_trades_and_caps_repeats():
    # 2Y->1B nets +1 YE; 4 yellow affords it twice
    assert val("playable_now", build(caravan=(4, 0, 0, 0), hand=[TRADE_2Y_1B])) == 2.0
    # 10 yellow affords it 5 times, but the cap is 3
    assert val("playable_now", build(caravan=(10, 0, 0, 0), hand=[TRADE_2Y_1B])) == 3.0


def test_playable_now_ignores_unaffordable_and_unprofitable_trades():
    assert val("playable_now", build(caravan=(1, 0, 0, 0), hand=[TRADE_2Y_1B])) == 0.0
    assert val("playable_now", build(caravan=(0, 0, 0, 3), hand=[TRADE_DOWN])) == 0.0


def test_playable_now_sums_the_hand():
    g = build(caravan=(4, 0, 0, 0), hand=[CREATE_2, TRADE_2Y_1B, UPGRADE_2])
    assert val("playable_now", g) == 2.0 + 2.0 + 2.0


# --------------------------------------------------------------------------
# 17: exhausted
# --------------------------------------------------------------------------

def test_exhausted_sums_the_played_pile():
    g = build(played=[CREATE_2, UPGRADE_2])
    assert val("exhausted", g) == 4.0


def test_exhausted_is_zero_with_an_empty_played_pile():
    assert val("exhausted", build(hand=[CREATE_2])) == 0.0


# --------------------------------------------------------------------------
# 18: dead_hand
# --------------------------------------------------------------------------

def test_dead_hand_fires_on_an_empty_hand():
    assert val("dead_hand", build(played=[CREATE_2])) == 1.0


def test_dead_hand_fires_when_nothing_in_hand_is_usable():
    g = build(caravan=(0, 0, 0, 2), hand=[UPGRADE_2, TRADE_2Y_1B])
    assert val("playable_now", g) == 0.0
    assert val("dead_hand", g) == 1.0


def test_dead_hand_is_zero_with_a_usable_hand():
    assert val("dead_hand", build(hand=[CREATE_2])) == 0.0


# --------------------------------------------------------------------------
# Ctx caching — the reason Step 2's cost is affordable
# --------------------------------------------------------------------------

def test_ctx_computes_ttc_once_per_player(monkeypatch):
    calls = []
    real = sim.ttc_row

    def counted(player, row, depth=3):
        calls.append(id(player))
        return real(player, row, depth)

    monkeypatch.setattr(sim, "ttc_row", counted)
    g = build(caravan=(0, 2, 0, 0), row=[PointCard(((G, 2),), 10, "2G")])
    ctx = Ctx(g, 3)
    for _ in range(5):
        ctx.ttc_row(0)
        ctx.best_target(0)
        FEATURES["token_race"].fn(g, g, 0, ctx)
    assert len(calls) == 1, f"ttc_row called {len(calls)} times, expected 1"


def test_ctx_is_per_state_not_shared_across_states():
    g = build(caravan=(0, 2, 0, 0), row=[PointCard(((G, 2),), 10, "2G")])
    a = Ctx(g, 3)
    first = a.best_target(0)
    g.players[0].caravan = [0, 0, 0, 0]
    b = Ctx(g, 3)
    assert b.best_target(0) != first


# --------------------------------------------------------------------------
# Phase and weight blending
# --------------------------------------------------------------------------

def test_phase_runs_zero_to_one():
    g = build()
    assert phase_of(g) == 0.0
    g.players[0].point_cards = [PointCard(((Y, 1),), 1, "x")] * g.win_target
    assert phase_of(g) == 1.0


def test_weights_blend_by_phase():
    w = Weights(name="t", features=["golem_points"],
                w_early={"golem_points": 0.0}, w_late={"golem_points": 10.0})
    assert w.effective(0.0)["golem_points"] == pytest.approx(0.0)
    assert w.effective(1.0)["golem_points"] == pytest.approx(10.0)
    assert w.effective(0.5)["golem_points"] == pytest.approx(5.0)


def test_identical_early_and_late_weights_skip_blending():
    same = {"golem_points": 2.0}
    w = Weights(name="t", features=["golem_points"], w_early=same, w_late=dict(same))
    assert w.effective(0.3) == same


# --------------------------------------------------------------------------
# Value function
# --------------------------------------------------------------------------

def simple_weights(**kw):
    feats = list(kw) or ["golem_points"]
    w = {k: kw.get(k, 1.0) for k in feats}
    return Weights(name="t", features=feats, w_early=w, w_late=dict(w), lam=0.0)


def test_evaluate_sums_weighted_features():
    g = build(point_cards=[PointCard(((Y, 2),), 10, "a")], caravan=(3, 0, 0, 0))
    w = simple_weights(golem_points=2.0, cry_y=0.5)
    v, parts = evaluate(g, g, 0, w, UNIT)
    assert parts["golem_points"] == pytest.approx(20.0)
    assert parts["cry_y"] == pytest.approx(1.5)
    assert v == pytest.approx(21.5)


def test_evaluate_applies_scales():
    g = build(point_cards=[PointCard(((Y, 2),), 10, "a")])
    w = simple_weights(golem_points=1.0)
    scaled = Scales(values={"golem_points": 5.0})
    v, _ = evaluate(g, g, 0, w, scaled)
    assert v == pytest.approx(2.0)


def test_lambda_subtracts_the_leading_opponent():
    g = build(point_cards=[PointCard(((Y, 2),), 10, "a")])
    g.players[1].point_cards = [PointCard(((Y, 2),), 6, "b")]
    w = simple_weights(golem_points=1.0)
    w.lam = 0.5
    v, parts = evaluate(g, g, 0, w, UNIT)
    assert parts["golem_points"] == pytest.approx(10.0)
    assert parts["-opp:golem_points"] == pytest.approx(-3.0)
    assert v == pytest.approx(7.0)


def test_lambda_ignores_me_only_features():
    g = build(caravan=(5, 0, 0, 0))
    g.players[1].caravan = [9, 0, 0, 0]
    w = simple_weights(cry_y=1.0)
    w.lam = 1.0
    v, parts = evaluate(g, g, 0, w, UNIT)
    assert "-opp:cry_y" not in parts
    assert v == pytest.approx(5.0)


def test_leading_opponent_is_the_highest_scorer():
    g = build(n=3)
    g.players[1].point_cards = [PointCard(((Y, 2),), 5, "b")]
    g.players[2].point_cards = [PointCard(((Y, 2),), 30, "c")]
    ctx = Ctx(g, 3)
    assert F._leading_opponent(g, 0, ctx) == 2


# --------------------------------------------------------------------------
# Terminal handling
# --------------------------------------------------------------------------

def test_terminal_is_none_while_the_game_is_open():
    assert terminal_value(build(), 0) is None


def test_terminal_win_and_loss():
    g = build(point_cards=[PointCard(((Y, 2),), 40, "a")])
    g.game_over = True
    assert terminal_value(g, 0) == pytest.approx(F.WIN_VALUE + 40)
    assert terminal_value(g, 1) == pytest.approx(-F.WIN_VALUE - 40)


def test_terminal_uses_seat_not_name():
    """Two seats can share a name; the winner must still be identified."""
    g = Game(["bot", "bot"], seed=1)
    g.players[1].point_cards = [PointCard(((Y, 2),), 12, "a")]
    g.game_over = True
    assert g._winner_index() == 1
    assert terminal_value(g, 1) > 0
    assert terminal_value(g, 0) < 0


def test_terminal_when_the_end_is_triggered_and_i_cannot_act_again():
    g = build(point_cards=[PointCard(((Y, 2),), 20, "a")], n=3)
    g._end_triggered = True
    g.current = 2                      # seats 0 and 1 have already acted
    assert terminal_value(g, 0) == pytest.approx(10 * 20)
    assert terminal_value(g, 2) is None, "seat 2 still has a turn"


def test_evaluate_short_circuits_on_terminal():
    g = build(point_cards=[PointCard(((Y, 2),), 40, "a")])
    g.game_over = True
    v, parts = evaluate(g, g, 0, simple_weights(golem_points=1.0), UNIT)
    assert list(parts) == ["terminal"] and v > F.WIN_VALUE


# --------------------------------------------------------------------------
# score_actions / explain
# --------------------------------------------------------------------------

def test_score_actions_ranks_best_first():
    g = Game(["A", "B"], seed=3)
    ranked = score_actions(g, 0, simple_weights(golem_points=1.0, best_target=1.0),
                           UNIT, rng=random.Random(0))
    assert ranked
    assert all(ranked[i][0] >= ranked[i + 1][0] for i in range(len(ranked) - 1))


def test_score_actions_prefers_claiming_when_golem_points_dominate():
    golem = PointCard(((G, 2),), 20, "2G=20")
    g = build(caravan=(0, 2, 0, 0), hand=[CREATE_2], row=[golem])
    w = simple_weights(golem_points=1.0)
    best = score_actions(g, 0, w, UNIT, rng=random.Random(0))[0][1]
    assert isinstance(best, Claim) and best.row_index == 0


def test_score_actions_does_not_mutate_the_game():
    g = Game(["A", "B"], seed=3)
    before = (list(g.players[0].caravan), len(g.merchant_deck),
              [c.name if c else None for c in g.merchant_row])
    score_actions(g, 0, simple_weights(golem_points=1.0), UNIT, rng=random.Random(0))
    after = (list(g.players[0].caravan), len(g.merchant_deck),
             [c.name if c else None for c in g.merchant_row])
    assert before == after


def test_explain_names_moves_and_contributions():
    golem = PointCard(((G, 2),), 20, "2G=20")
    g = build(caravan=(0, 2, 0, 0), hand=[CREATE_2], row=[golem])
    out = explain(g, 0, simple_weights(golem_points=1.0, best_target=1.0),
                  UNIT, top_k=3, rng=random.Random(0))
    assert "#1" in out and "V=" in out
    assert "Claim(row 0)" in out
    assert "golem_points" in out


def test_explain_survives_an_empty_action_list():
    g = build()
    g.game_over = True
    out = explain(g, 0, simple_weights(golem_points=1.0), UNIT)
    assert "0 legal moves" in out


# --------------------------------------------------------------------------
# Scales file
# --------------------------------------------------------------------------

def test_scales_file_is_present_and_covers_every_core_feature():
    s = Scales.load()
    assert s.values, "run `python -m bots.calibrate` to generate feature_scales.json"
    for key in CORE_FEATURES:
        assert key in s.values and s.values[key] > 0


# `throughput` is genuinely outside the comparable band and it is not a
# mistake to be fixed by widening the band. Every player builds a similar
# engine, so it sits in a narrow range (~1.9-2.6) all game; dividing by that
# small spread amplifies it about 9x. It is *not* redundant — its strongest
# correlation with another feature is only r=0.42 against `exhausted` — so it
# is kept, with its weight set through bots.make_handset's points-based intent
# rather than typed directly. Pinned here so it cannot drift further unnoticed.
KNOWN_WIDE = {"throughput": 10.0}


def test_scales_are_in_the_comparable_band():
    """Normalisation is only useful if a weight of 1.0 means about the same
    thing for each feature — see calibrate.py's norm-p95 note."""
    s = Scales.load()
    for key in CORE_FEATURES:
        d = s.diagnostics.get(key)
        assert d, key
        ceiling = KNOWN_WIDE.get(key, 8.0)
        assert 1.0 <= d["norm_p95"] <= ceiling, (key, d["norm_p95"], ceiling)


def test_only_the_known_features_are_outside_the_band():
    """A new feature outside the band must be noticed, not absorbed."""
    s = Scales.load()
    outside = {k for k in CORE_FEATURES
               if not (1.0 <= s.diagnostics[k]["norm_p95"] <= 8.0)}
    assert outside == set(KNOWN_WIDE), (
        f"band membership changed: {outside} vs known {set(KNOWN_WIDE)}. "
        "Recalibrate and decide deliberately — see API_NOTES §10.")


def test_unit_scales_are_all_one():
    for key in CORE_FEATURES:
        assert Scales.unit().get(key) == 1.0

"""Step 4: the admissible lower bound.

The roadmap's check is "h matches hand calculations on made-up states", which
`test_handover_worked_example` is. Everything else here defends the one
property the search depends on:

    h must NEVER exceed the turns actually remaining.

Too-small h only costs search time. Too-big h prunes a winning line and DFBB
still calls the result optimal, so the tests lean on that side.
"""

from __future__ import annotations

import random

import pytest

from bots._engine import (CARAVAN_LIMIT, MERCHANT_CARDS, Crystal, CrystalCard,
                          Discard, TradeCard, UpgradeCard)
from bots.bots import GreedyBot
from bots.sim import YE, cost_of, ye_of
from solver import bound
from solver.bound import (cap_for, card_gain, crystal_values, g_max,
                          golem_value, h, value)
from solver.solo import new_solo_game


def named(name):
    return next(c for c in MERCHANT_CARDS if c.name == name)


# ---------------------------------------------------------------------------
# The value scale
# ---------------------------------------------------------------------------

def test_capped_scales_match_the_base_scale():
    """The scales are hardcoded for readability; this is what stops them
    drifting from YE if YE is ever retuned (bots/sim.py says it may be)."""
    for cap in range(4):
        assert crystal_values(cap) == tuple(min(v, YE[cap]) for v in YE)


def test_scales_are_indexed_by_crystal():
    assert crystal_values(Crystal.YELLOW) == (1, 1, 1, 1)
    assert crystal_values(Crystal.GREEN) == (1, 2, 2, 2)
    assert crystal_values(Crystal.TURQUOISE) == (1, 2, 3, 3)
    assert crystal_values(Crystal.MAGENTA) == (1, 2, 3, 4)


def test_value_matches_the_engine_side_scale_uncapped():
    for counts in ([3, 0, 0, 0], [2, 2, 2, 1], [0, 0, 0, 10], [0, 0, 0, 0]):
        assert value(counts) == ye_of(counts)


def test_capping_only_ever_lowers_value():
    counts = [1, 1, 1, 1]           # one of each colour
    # yellow cap 1+1+1+1, green 1+2+2+2, blue 1+2+3+3, uncapped 1+2+3+4
    assert [value(counts, cap) for cap in range(4)] == [4, 7, 9, 10]


# ---------------------------------------------------------------------------
# Golems
# ---------------------------------------------------------------------------

def test_golem_value_prices_the_cost_not_the_points():
    """Two golems costing the same are worth the same to a turn-minimising
    search even when one pays far more victory points."""
    g = new_solo_game(seed=0)
    for card in g.point_deck:
        assert golem_value(card) == value(cost_of(card))


def test_cap_for_is_magenta_while_magenta_golems_remain():
    """22 of the 36 golems need magenta, so this is the normal case and the
    capping machinery almost never fires in a real game."""
    assert cap_for(new_solo_game(seed=0)) == Crystal.MAGENTA


def test_cap_for_reads_the_deck_not_just_the_row():
    """Pricing only the visible five could overstate what is owed."""
    g = new_solo_game(seed=0)
    g.point_row = [c for c in g.point_row if max(
        i for i in range(4) if cost_of(c)[i] > 0) <= Crystal.GREEN] or [None] * 5
    assert cap_for(g) == Crystal.MAGENTA, "deck still holds magenta golems"


def test_cap_for_falls_back_to_yellow_when_nothing_remains():
    g = new_solo_game(seed=0)
    g.point_row, g.point_deck = [None] * 5, []
    assert cap_for(g) == Crystal.YELLOW


# ---------------------------------------------------------------------------
# Card gains
# ---------------------------------------------------------------------------

def test_crystal_card_gain_is_what_it_makes():
    assert card_gain(CrystalCard(((Crystal.YELLOW, 2),), "Create 2")) == 2
    assert card_gain(CrystalCard(((Crystal.YELLOW, 3),), "+3Y")) == 3
    assert card_gain(CrystalCard(((Crystal.MAGENTA, 1),), "+1M")) == 4


@pytest.mark.parametrize("cap,expected", [
    (Crystal.MAGENTA, 2), (Crystal.TURQUOISE, 2),
    (Crystal.GREEN, 2), (Crystal.YELLOW, 0),
])
def test_upgrade_gain_collapses_under_a_yellow_cap(cap, expected):
    """If only yellow is wanted, an upgrade card genuinely cannot help."""
    assert card_gain(UpgradeCard(2, "Upgrade 2"), cap) == expected


def test_trade_gain_uses_crystals_per_trade_for_the_repeat_count():
    """2G->1M2Y: net +2, costs 2 crystals, so 10//2 = 5 repeats.

    Counting repeats by the cost's *value* (4) instead of its crystal count
    would give 2 repeats and a gain of 4 — too small, which makes h too big.
    """
    assert card_gain(named("2G->1M2Y")) == 10


def test_value_losing_trades_count_zero():
    losing = TradeCard(((Crystal.MAGENTA, 1),), ((Crystal.YELLOW, 1),), "1M->1Y")
    assert card_gain(losing) == 0


def test_unknown_card_type_raises_rather_than_guessing():
    with pytest.raises(TypeError):
        card_gain(object())


# ---------------------------------------------------------------------------
# G_max
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cap,expected", [
    (Crystal.YELLOW, 10), (Crystal.GREEN, 20),
    (Crystal.TURQUOISE, 30), (Crystal.MAGENTA, 40),
])
def test_g_max_is_the_caravan_ceiling(cap, expected):
    """A turn cannot leave you holding more than CARAVAN_LIMIT crystals, so it
    cannot add more value than a full caravan of the best colour is worth.

    This is the bound that survives Acquire. The cards alone would give a
    smaller number, and a too-small G_max makes h too big.
    """
    assert g_max(cap) == expected == CARAVAN_LIMIT * max(crystal_values(cap))


def test_g_max_is_cached_but_still_correct():
    assert g_max(Crystal.MAGENTA) == g_max(Crystal.MAGENTA) == 40


# ---------------------------------------------------------------------------
# h
# ---------------------------------------------------------------------------

def test_handover_worked_example(monkeypatch):
    """Two golems claimed, cheapest four remaining worth 40, caravan worth 10,
    G_max 10.  V = 30, building = 3, claims left = 4, h = 7."""
    monkeypatch.setattr(bound, "g_max", lambda cap, cards=None: 10)
    # Every golem costs 10 on every scale, and needs magenta (so no capping).
    # h reads golem prices through _facts since step 8 cached them.
    monkeypatch.setattr(bound, "_facts",
                        lambda c: (c, Crystal.MAGENTA, (10, 10, 10, 10)))
    monkeypatch.setattr(bound, "value", lambda counts, cap=None: 10)

    game = new_solo_game(seed=0)
    game.players[0].point_cards = [game.point_row[0], game.point_row[1]]
    assert bound.h(game) == 7


def test_h_is_zero_once_the_goal_is_reached():
    game = new_solo_game(seed=0)
    game.players[0].point_cards = list(game.point_deck[:6])
    assert h(game) == 0


def test_h_is_never_below_the_claims_still_owed():
    """Each golem needs its own Claim turn, so h can never undercut that."""
    game = new_solo_game(seed=0)
    for claimed in range(6):
        game.players[0].point_cards = list(game.point_deck[:claimed])
        assert h(game) >= game.win_target - claimed


@pytest.mark.parametrize("seed", range(6))
def test_h_never_exceeds_the_turns_actually_remaining(seed):
    """The property the whole file exists for, checked against real play.

    A playthrough's remaining turns is an upper bound on the optimal
    remaining turns, so h <= remaining is necessary (not sufficient) for
    admissibility. If it ever fails, the bound is definitely broken.
    """
    game = new_solo_game(seed=seed)
    rng = random.Random(seed)
    greedy = GreedyBot(seed=seed)

    trace = []
    while not game.game_over and len(trace) < 4000:
        action = greedy.choose(game) or rng.choice(game.legal_actions())
        trace.append((h(game), action))
        game.apply_action(action)

    total = sum(1 for _, a in trace if not isinstance(a, Discard))
    spent = 0
    for estimate, action in trace:
        assert estimate <= total - spent, (
            f"h={estimate} but only {total - spent} turns remained")
        if not isinstance(action, Discard):
            spent += 1


def test_h_is_currently_weak_and_we_know_it():
    """Documents where the bound stands, so a future tightening has a
    baseline to beat. G_max is 40 while magenta golems remain, and golems
    cost 8-17, so the building term is almost always 1."""
    game = new_solo_game(seed=0)
    rng = random.Random(0)
    greedy = GreedyBot(seed=0)
    seen = set()
    while not game.game_over:
        claims_left = game.win_target - len(game.players[0].point_cards)
        seen.add(h(game) - claims_left)
        game.apply_action(greedy.choose(game) or rng.choice(game.legal_actions()))
    assert seen <= {0, 1, 2}, f"building term moved off 0-2: {sorted(seen)}"


# ---------------------------------------------------------------------------
# Step 8: the cached h must equal the original, not merely be close
# ---------------------------------------------------------------------------

def _reference_h(game):
    """h exactly as first written (step 4), before its golem facts were
    cached. The fast version must agree with it on every position."""
    player = game.players[0]
    claims_left = game.win_target - len(player.point_cards)
    if claims_left <= 0:
        return 0
    remaining = [c for c in game.point_row if c is not None] + game.point_deck
    cap = Crystal.YELLOW
    for card in remaining:
        cost = cost_of(card)
        for c in range(4):
            if cost[c] > 0 and c > cap:
                cap = Crystal(c)
    cheapest = sorted(value(cost_of(c), cap) for c in remaining)[:claims_left]
    deficit = max(0, sum(cheapest) - value(player.caravan, cap))
    per_turn = CARAVAN_LIMIT * max(crystal_values(cap))
    return claims_left + (deficit + per_turn - 1) // per_turn


@pytest.mark.parametrize("seed", range(8))
def test_cached_h_equals_the_original(seed):
    from solver.tiny import fast_board
    games = [new_solo_game(seed=seed), fast_board(seed).game()]
    rng = random.Random(seed)
    for game in games:
        while not game.game_over:
            assert h(game) == _reference_h(game)
            game.apply_action(rng.choice(game.legal_actions()))
        assert h(game) == _reference_h(game)


def test_cap_for_unaffected_when_the_deck_empties():
    game = new_solo_game(seed=0)
    game.point_row, game.point_deck = [None] * 5, []
    assert cap_for(game) == Crystal.YELLOW
    assert h(game) == _reference_h(game)

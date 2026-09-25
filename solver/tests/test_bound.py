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
    # The handover's single G_max of 10 applies to both bounds. Patching
    # g_play also stops it computing — and caching, for every later test —
    # its per-card table while `value` is faked.
    monkeypatch.setattr(bound, "g_play", lambda cap=None: 10)
    # The handover's arithmetic has no notion of buying cards or resting, so
    # the engine bound is switched off here — which also stops it building
    # and caching its per-card table from the fake `value`.
    monkeypatch.setattr(bound, "engine_turns", lambda *args, **kw: 0)

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


def test_h_building_term_baseline():
    """Documents where the bound stands, so a future tightening has a
    baseline to beat. With only the caravan bound (G_max 40) the building
    term was 0-2; the potential bound (g_play 10) lifted it to 0-5, and the
    engine bound (buying cards and resting cost turns) to 0-8 over a greedy
    game. This fails if a change quietly loses that."""
    game = new_solo_game(seed=0)
    rng = random.Random(0)
    greedy = GreedyBot(seed=0)
    seen = set()
    while not game.game_over:
        claims_left = game.win_target - len(game.players[0].point_cards)
        seen.add(h(game) - claims_left)
        game.apply_action(greedy.choose(game) or rng.choice(game.legal_actions()))
    # caravan bound alone: 0-2; + potential: 0-5; + engine: 0-8;
    # + board-aware golem pricing: 0-10
    assert max(seen) >= 9, f"building term only reached {max(seen)}"
    assert seen <= set(range(14)), f"building term jumped: {sorted(seen)}"


# ---------------------------------------------------------------------------
# Step 8: the cached h must equal the original, not merely be close
# ---------------------------------------------------------------------------

def _brute_schedule(items, k):
    """Least total price over every set of k distinct golems that can fill
    claims 1..k (claim i takes one with earliest <= i). Exhaustive and
    obvious on purpose; independent of the matroid greedy it checks."""
    import itertools
    best = None
    for combo in itertools.combinations(items, min(k, len(items))):
        # a set can fill claims 1..k iff, earliest first, the i-th fits claim i
        if all(w <= i + 1 for i, (_, w) in enumerate(sorted(combo, key=lambda t: t[1]))):
            total = sum(price for price, _ in combo)
            best = total if best is None or total < best else best
    return best or 0


def _reference_h(game):
    """h exactly as first written (step 4), before its golem facts were
    cached. The fast version must agree with it on every position."""
    player = game.players[0]
    claims_left = game.win_target - len(player.point_cards)
    if claims_left <= 0:
        return 0
    # Golems that can surface before the last claim, with the earliest claim
    # each could fill: the row from claim 1, the m-th card drawn (from the END
    # of the deck) from claim m + 1.
    windows = [(c, 1) for c in game.point_row if c is not None]
    for m in range(1, claims_left):
        if m <= len(game.point_deck):
            windows.append((game.point_deck[-m], m + 1))
    cap = Crystal.YELLOW
    for card, _ in windows:
        cost = cost_of(card)
        for c in range(4):
            if cost[c] > 0 and c > cap:
                cap = Crystal(c)
    cheapest = [_brute_schedule(
        [(value(cost_of(c), cap), w) for c, w in windows], claims_left)]
    deficit = max(0, sum(cheapest) - value(player.caravan, cap))
    per_turn = CARAVAN_LIMIT * max(crystal_values(cap))
    by_caravan = (deficit + per_turn - 1) // per_turn

    # The step-8 potential bound, written out longhand.
    vals = crystal_values(cap)
    pot = value(player.caravan, cap) + sum(
        n * vals[c] for rc in game.row_crystals for c, n in rc.items())
    gp = bound.g_play(cap)
    deficit = max(0, sum(cheapest) - pot)
    by_potential = (deficit + gp - 1) // gp
    by_engine = bound.engine_turns(player.hand, player.played, deficit, cap)
    return claims_left + max(by_caravan, by_potential, by_engine)


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


# ---------------------------------------------------------------------------
# Step 8: the potential bound
# ---------------------------------------------------------------------------

from bots._engine import Acquire, Claim, Rest  # noqa: E402
from bots.bots import RandomBot  # noqa: E402
from solver.bound import g_play, play_gain, potential  # noqa: E402


def test_play_gain_honours_the_limit_on_the_way_out():
    """1B->1G4Y 'nets +30' by the old formula (net 3 x 10 repeats), but ten
    repeats make 50 crystals and only 10 can be kept."""
    card = named("1B->1G4Y")
    assert card_gain(card) == 30
    assert play_gain(card) < 30
    assert play_gain(card) <= g_play()


def test_the_best_card_play_adds_ten():
    """Measured tight: trades like 4Y->3B reach exactly this in real play."""
    assert g_play(Crystal.MAGENTA) == 10
    assert play_gain(named("4Y->3B")) == 10


def test_crystal_and_upgrade_cards_are_unchanged():
    create = CrystalCard(((Crystal.YELLOW, 2),), "Create 2")
    upgrade = UpgradeCard(2, "Upgrade 2")
    for cap in range(4):
        assert play_gain(create, cap) == card_gain(create, cap)
        assert play_gain(upgrade, cap) == card_gain(upgrade, cap)


def test_potential_counts_row_crystals_as_yours():
    game = new_solo_game(seed=0)
    base = potential(game)
    game.row_crystals[2][Crystal.MAGENTA] += 1
    assert potential(game) == base + 4


@pytest.mark.parametrize("seed", range(6))
def test_only_card_plays_raise_the_potential(seed):
    """The lemma the bound rests on, checked on every turn of real games under
    every cap: Acquire, Rest and Claim (after its cost) never raise the
    potential, and a play never raises it by more than g_play. A discard
    that follows a move is part of that move's turn."""
    for bot in (GreedyBot(seed=seed), RandomBot(seed=seed)):
        game = new_solo_game(seed=seed)
        rng = random.Random(seed)
        while not game.game_over:
            action = bot.choose(game) or rng.choice(game.legal_actions())
            before = [potential(game, cap) for cap in range(4)]
            golem = game.point_row[action.row_index] if isinstance(action, Claim) else None
            game.apply_action(action)
            while game.pending_discard is not None:
                game.apply_action(rng.choice(game.legal_actions()))
            for cap in range(4):
                change = potential(game, cap) - before[cap]
                if golem is not None:
                    change += value(cost_of(golem), cap)
                limit = 0 if isinstance(action, (Acquire, Rest, Claim)) else g_play(cap)
                assert change <= limit, (type(action).__name__, cap, change)


def test_h_takes_the_larger_of_the_two_bounds():
    """Crystals piled on the row raise the potential and can shrink the
    potential bound below the caravan bound; h must not drop with it."""
    game = new_solo_game(seed=0)
    for rc in game.row_crystals:
        rc[Crystal.MAGENTA] = 10
    assert h(game) >= game.win_target
    assert h(game) == _reference_h(game)


# ---------------------------------------------------------------------------
# Step 8: the engine bound
# ---------------------------------------------------------------------------

import functools  # noqa: E402
from solver.bound import _engine_turns, engine_turns  # noqa: E402


def _brute_engine_turns(hand, played, deficit, pool, horizon=14):
    """The same relaxed model, solved the slow obvious way: breadth-first
    over (turns, cards in hand, cards in the played pile, bought so far,
    gained so far). Independent of the DP it checks."""
    start = (tuple(sorted(hand)), tuple(sorted(played)), 0, 0)
    layer = {start}
    for turns in range(horizon + 1):
        if any(gained >= deficit for _, _, _, gained in layer):
            return turns
        nxt = set()
        for hnd, pld, bought, gained in layer:
            if bought < len(pool):                       # acquire the next best
                nxt.add((tuple(sorted(hnd + (pool[bought],))), pld, bought + 1, gained))
            if pld:                                      # rest
                nxt.add((tuple(sorted(hnd + pld)), (), bought, gained))
            for i, g in enumerate(hnd):                  # play one card
                rest_hand = hnd[:i] + hnd[i + 1:]
                nxt.add((rest_hand, tuple(sorted(pld + (g,))), bought,
                         min(deficit, gained + g)))
        layer = nxt
    return None


@pytest.mark.parametrize("seed", range(40))
def test_engine_dp_matches_a_brute_force_of_the_same_model(seed):
    rng = random.Random(seed)
    pool = tuple(sorted((rng.randint(0, 10) for _ in range(5)), reverse=True))
    hand = tuple(rng.randint(0, 4) for _ in range(rng.randint(0, 3)))
    played = tuple(rng.randint(0, 6) for _ in range(rng.randint(0, 2)))
    deficit = rng.randint(1, 30)
    want = _brute_engine_turns(hand, played, deficit, pool)
    got = _engine_turns(tuple(sorted(hand, reverse=True)),
                        tuple(sorted(played, reverse=True)), deficit, pool)
    if want is None:
        assert got > 14
    else:
        assert got == want


def test_engine_opening_example():
    """Hand Create 2 + Upgrade 2 (2 each), deficit 42, best cards worth 10:
    buy two 10s, play both, Rest, play both again and one 2 — 2 + 2 + 1 +
    3 = 8 turns. The potential bound said ceil(42 / 10) = 5."""
    assert _engine_turns((2, 2), (), 42, (10, 10, 10, 10, 10, 9)) == 8


def test_played_cards_need_a_rest_first():
    # the only card is in the played pile: rest then play, or buy and play
    assert _engine_turns((), (10,), 10, (10,)) == 2
    assert _engine_turns((), (10,), 10, ()) == 2      # rest, play


def test_engine_bound_never_below_the_potential_bound():
    game = new_solo_game(seed=3)
    p = game.players[0]
    for deficit in range(0, 80, 7):
        assert engine_turns(p.hand, p.played, deficit) >= -(-deficit // bound.g_play())


def test_opening_h_reads_the_board():
    """Engine bound alone: 14 on every seed. Pricing only golems that can
    surface makes the opening bound depend on the deal."""
    opening = [h(new_solo_game(seed=s)) for s in range(10)]
    assert opening == [16, 18, 16, 16, 16, 16, 15, 18, 18, 15]


# ---------------------------------------------------------------------------
# Step 8: board-aware golem pricing
# ---------------------------------------------------------------------------

from solver.bound import _cheapest_schedule, reachable_golems  # noqa: E402


def test_reachable_golems_are_the_row_then_the_next_draws():
    game = new_solo_game(seed=0)
    got = reachable_golems(game, 6)
    assert [w for _, w in got] == [1] * 5 + [2, 3, 4, 5, 6]
    assert [c for c, _ in got[5:]] == [game.point_deck[-m] for m in range(1, 6)]
    assert len(reachable_golems(game, 1)) == 5       # last claim: row only


@pytest.mark.parametrize("seed", range(60))
def test_cheapest_schedule_matches_brute_force(seed):
    rng = random.Random(seed)
    k = rng.randint(1, 4)
    items = [(rng.randint(4, 20), 1) for _ in range(rng.randint(1, 4))]
    items += [(rng.randint(4, 20), w) for w in range(2, k + 1)]
    assert _cheapest_schedule(items, k) == _brute_schedule(items, k)


def test_a_cheap_golem_deep_in_the_deck_is_not_counted():
    """It cannot surface before the claims run out, so pricing it would
    understate what is owed."""
    game = new_solo_game(seed=0)
    cheapest_card = min(game.point_deck, key=golem_value)
    game.point_deck.remove(cheapest_card)
    game.point_deck.insert(0, cheapest_card)            # drawn last
    assert cheapest_card not in [c for c, _ in reachable_golems(game, 6)]

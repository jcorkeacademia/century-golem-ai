"""Step 2: the solitaire simulator and TTC."""
from __future__ import annotations

import math
import random
import time

import pytest

from bots._engine import (
    Crystal,
    CrystalCard,
    Game,
    PointCard,
    TradeCard,
    UpgradeCard,
)
from bots import sim
from bots.sim import (
    YE,
    can_pay,
    card_id,
    card_ids,
    cost_of,
    enforce_limit,
    nominal_output,
    shortfall,
    throughput,
    ttc,
    ttc_state,
    ye_of,
)

Y, G, B, M = Crystal.YELLOW, Crystal.GREEN, Crystal.TURQUOISE, Crystal.MAGENTA

CREATE_2 = CrystalCard(((Y, 2),), "Create 2")
UPGRADE_2 = UpgradeCard(2, "Upgrade 2")
UPGRADE_3 = UpgradeCard(3, "Triple upgrade")


def make_player(caravan, hand=(), played=()):
    g = Game(["A", "B"], seed=1)
    p = g.players[0]
    p.caravan = list(caravan)
    p.hand = list(hand)
    p.played = list(played)
    return p


@pytest.fixture(autouse=True)
def _clear_cache():
    sim.clear_cache()
    yield


# --------------------------------------------------------------------------
# YE and nominal output (§2.1, §2.2)
# --------------------------------------------------------------------------

def test_ye_scale():
    assert YE == (1, 2, 3, 4)
    assert ye_of((1, 1, 1, 1)) == 10
    assert ye_of((0, 0, 0, 0)) == 0
    assert ye_of((3, 0, 0, 2)) == 11


def test_nominal_output_crystal_card():
    assert nominal_output(CREATE_2) == 2.0                       # 2 yellow
    assert nominal_output(CrystalCard(((M, 1),), "+1M")) == 4.0
    assert nominal_output(CrystalCard(((B, 1), (Y, 1)), "+1B1Y")) == 4.0


def test_nominal_output_upgrade_card():
    assert nominal_output(UPGRADE_2) == 2.0
    assert nominal_output(UPGRADE_3) == 3.0


def test_nominal_output_trade_card():
    # 2Y (2 YE) -> 1B (3 YE): net +1
    assert nominal_output(TradeCard(((Y, 2),), ((B, 1),), "2Y->1B")) == 1.0
    # 3G (6 YE) -> 2M (8 YE): net +2
    assert nominal_output(TradeCard(((G, 3),), ((M, 2),), "3G->2M")) == 2.0


def test_nominal_output_can_be_negative():
    """Trading down the chain is a real card type and must not be clamped."""
    # 1M (4 YE) -> 3Y (3 YE): net -1
    assert nominal_output(TradeCard(((M, 1),), ((Y, 3),), "1M->3Y")) == -1.0


def test_throughput_counts_the_rest_turn():
    p = make_player((0, 0, 0, 0), hand=[CREATE_2], played=[UPGRADE_2])
    # (2 + 2) / (2 cards + 1 rest)
    assert throughput(p) == pytest.approx(4 / 3)


def test_throughput_of_empty_hand_is_zero():
    assert throughput(make_player((5, 0, 0, 0))) == 0.0


# --------------------------------------------------------------------------
# Card identity
# --------------------------------------------------------------------------

def test_card_id_ignores_name():
    """The engine's starting cards differ in name from century_cards'."""
    assert card_id(UpgradeCard(2, "Upgrade 2")) == card_id(UpgradeCard(2, "Double upgrade"))
    assert card_id(CrystalCard(((Y, 2),), "Create 2")) == \
           card_id(CrystalCard(((Y, 2),), "Create 2 (+2Y)"))


def test_card_id_distinguishes_mechanics():
    ids = {card_id(c) for c in (CREATE_2, UPGRADE_2, UPGRADE_3,
                                TradeCard(((Y, 2),), ((B, 1),), "a"),
                                TradeCard(((Y, 2),), ((G, 2),), "b"))}
    assert len(ids) == 5


def test_card_ids_are_order_independent():
    assert card_ids([CREATE_2, UPGRADE_2]) == card_ids([UPGRADE_2, CREATE_2])


# --------------------------------------------------------------------------
# Shortfall (§2.3)
# --------------------------------------------------------------------------

def test_shortfall_zero_when_payable():
    assert shortfall((2, 2, 0, 0), (2, 2, 0, 0)) == 0
    assert shortfall((5, 5, 5, 5), (1, 1, 1, 1)) == 0


def test_shortfall_counts_upgrade_steps():
    # two green, need two blue: one step each
    assert shortfall((0, 2, 0, 0), (0, 0, 2, 0)) == 2
    # one yellow, need one magenta: three steps
    assert shortfall((1, 0, 0, 0), (0, 0, 0, 1)) == 3


def test_shortfall_magenta_cannot_pay_a_green_cost():
    """The case the brief calls out: crystals only move up the chain."""
    # one magenta, need one green -> magenta is useless, charge the green's YE
    assert shortfall((0, 0, 0, 1), (0, 1, 0, 0)) == YE[1] == 2
    # and having more magenta does not help
    assert shortfall((0, 0, 0, 5), (0, 1, 0, 0)) == 2


def test_shortfall_charges_full_value_for_missing_crystals():
    assert shortfall((0, 0, 0, 0), (0, 0, 0, 1)) == 4     # a magenta from nothing
    assert shortfall((0, 0, 0, 0), (1, 0, 0, 0)) == 1
    assert shortfall((0, 0, 0, 0), (2, 2, 0, 0)) == 2 * 1 + 2 * 2


def test_shortfall_matches_expensive_costs_first():
    """One green, needing a green and a blue.

    Spending the green on the blue (1 step) and buying the green outright (2)
    costs 3; the other way round costs 0 + 3 = 3 as well. Either way 3 — but
    the expensive-first rule is what keeps that true in general.
    """
    assert shortfall((0, 1, 0, 0), (0, 1, 1, 0)) == 3


def test_shortfall_partial_coverage():
    # have 2Y 1G, need 2Y 2G: one green short, and no spare yellow to upgrade
    assert shortfall((2, 1, 0, 0), (2, 2, 0, 0)) == 2
    # have 3Y 1G, need 2Y 2G: the spare yellow upgrades into the green
    assert shortfall((3, 1, 0, 0), (2, 2, 0, 0)) == 1


def test_can_pay_agrees_with_shortfall():
    rng = random.Random(0)
    for _ in range(500):
        car = tuple(rng.randrange(0, 5) for _ in range(4))
        cost = tuple(rng.randrange(0, 4) for _ in range(4))
        assert can_pay(car, cost) == (shortfall(car, cost) == 0)


# --------------------------------------------------------------------------
# Caravan limit
# --------------------------------------------------------------------------

def test_enforce_limit_leaves_small_caravans_alone():
    assert enforce_limit((1, 2, 3, 4)) == (1, 2, 3, 4)


def test_enforce_limit_drops_cheapest_first():
    assert enforce_limit((5, 5, 5, 0)) == (0, 5, 5, 0)
    assert enforce_limit((2, 9, 0, 0)) == (1, 9, 0, 0)
    assert enforce_limit((0, 0, 6, 6)) == (0, 0, 4, 6)


def test_enforce_limit_matches_the_engine():
    """The sim's cap must track Game._enforce_caravan_limit exactly."""
    rng = random.Random(1)
    for _ in range(200):
        car = [rng.randrange(0, 8) for _ in range(4)]
        g = Game(["A", "B"], seed=1)
        p = g.players[0]
        p.caravan = car[:]
        g._enforce_caravan_limit(p)
        assert tuple(p.caravan) == enforce_limit(tuple(car))


# --------------------------------------------------------------------------
# TTC — the four cases the brief requires (§2.5)
# --------------------------------------------------------------------------

def test_ttc_zero_when_already_payable():
    p = make_player((0, 0, 2, 0), hand=[UPGRADE_2])
    golem = PointCard(((B, 2),), 9, "2B")
    assert ttc(p, golem) == 0.0


def test_ttc_one_turn_with_the_upgrade_in_hand():
    """Golem 2B, caravan 2G, Upgrade 2 in hand -> 1."""
    p = make_player((0, 2, 0, 0), hand=[UPGRADE_2])
    golem = PointCard(((B, 2),), 9, "2B")
    assert ttc(p, golem) == 1.0


def test_ttc_two_turns_with_the_upgrade_in_the_played_pile():
    """Same position, but the card must be rested back first -> 2."""
    p = make_player((0, 2, 0, 0), hand=[], played=[UPGRADE_2])
    golem = PointCard(((B, 2),), 9, "2B")
    assert ttc(p, golem) == 2.0


def test_ttc_falls_back_beyond_the_horizon():
    """Nothing reachable in `depth` turns -> an extrapolation above depth."""
    p = make_player((0, 0, 0, 0), hand=[CREATE_2])
    golem = PointCard(((M, 5),), 20, "5M")
    got = ttc(p, golem, depth=3)
    assert got > 3, got
    assert math.isfinite(got)


def test_ttc_fallback_uses_throughput():
    """depth + ceil(shortfall AT THE BEST LEAF / throughput).

    Empty caravan, only Create 2 in hand, chasing 5M. Over three turns the
    best line is play / rest / play, ending on 4Y. That is not 5M, but it is
    much closer than nothing: four yellows cover four magenta at three
    upgrade steps each (12), plus one magenta missing outright (4) = 16.
    Throughput is 2 YE over (1 card + 1 rest) = 1.0, so 3 + 16 = 19.

    The starting shortfall is 20; using that instead of the best leaf would
    give 23. The distinction is the whole point of the fallback.
    """
    p = make_player((0, 0, 0, 0), hand=[CREATE_2])
    golem = PointCard(((M, 5),), 20, "5M")
    assert throughput(p) == pytest.approx(1.0)
    assert shortfall((0, 0, 0, 0), (0, 0, 0, 5)) == 20      # at the start
    assert shortfall((4, 0, 0, 0), (0, 0, 0, 5)) == 16      # at the best leaf
    assert ttc(p, golem, depth=3) == pytest.approx(3 + math.ceil(16 / 1.0))


def test_ttc_never_negative_and_zero_only_when_payable():
    rng = random.Random(3)
    for _ in range(200):
        car = tuple(rng.randrange(0, 4) for _ in range(4))
        cost = tuple(rng.randrange(0, 3) for _ in range(4))
        if not any(cost):
            continue
        p = make_player(car, hand=[CREATE_2, UPGRADE_2])
        golem = PointCard(tuple((Crystal(i), cost[i]) for i in range(4) if cost[i]),
                          10, "x")
        got = ttc(p, golem)
        assert got >= 0
        assert (got == 0) == can_pay(car, cost)


# --------------------------------------------------------------------------
# TTC — behaviour
# --------------------------------------------------------------------------

def test_more_cards_never_makes_ttc_worse():
    golem = PointCard(((B, 2),), 9, "2B")
    lean = make_player((0, 2, 0, 0), hand=[CREATE_2])
    rich = make_player((0, 2, 0, 0), hand=[CREATE_2, UPGRADE_2])
    assert ttc(rich, golem) <= ttc(lean, golem)


def test_a_crystal_card_can_bridge_the_gap():
    """Need 4Y, have 2Y, holding Create 2 -> one turn."""
    p = make_player((2, 0, 0, 0), hand=[CREATE_2])
    assert ttc(p, PointCard(((Y, 4),), 6, "4Y")) == 1.0


def test_a_trade_card_can_bridge_the_gap():
    p = make_player((4, 0, 0, 0), hand=[TradeCard(((Y, 4),), ((B, 2),), "4Y->2B")])
    assert ttc(p, PointCard(((B, 2),), 9, "2B")) == 1.0


def test_trade_repetitions_are_searched():
    """2Y->1B played once is not enough; the search must try times=2."""
    p = make_player((4, 0, 0, 0), hand=[TradeCard(((Y, 2),), ((B, 1),), "2Y->1B")])
    assert ttc(p, PointCard(((B, 2),), 9, "2B")) == 1.0


def test_two_step_plan_is_found():
    """Create 2 then upgrade both: 2 turns to reach 2G."""
    p = make_player((0, 0, 0, 0), hand=[CREATE_2, UPGRADE_2])
    assert ttc(p, PointCard(((G, 2),), 6, "2G")) == 2.0


def test_rest_is_used_when_the_hand_is_empty():
    p = make_player((2, 0, 0, 0), hand=[], played=[CREATE_2])
    # turn 1 rest, turn 2 play Create 2 -> 4Y
    assert ttc(p, PointCard(((Y, 4),), 6, "4Y")) == 2.0


def test_deeper_search_never_returns_a_worse_answer():
    rng = random.Random(7)
    g = Game(["A", "B"], seed=2)
    r = random.Random(2)
    for _ in range(40):
        acts = g.legal_actions()
        if not acts or g.game_over:
            break
        g.apply_action(r.choice(acts))
    for p in g.players:
        for pc in g.point_row:
            if pc is None:
                continue
            sim.clear_cache()
            shallow = ttc(p, pc, depth=2)
            sim.clear_cache()
            deep = ttc(p, pc, depth=4)
            assert deep <= shallow + 1e-9, (shallow, deep, pc.name)


def test_ttc_row_matches_ttc_per_card():
    g = Game(["A", "B"], seed=5)
    r = random.Random(5)
    for _ in range(30):
        acts = g.legal_actions()
        if not acts:
            break
        g.apply_action(r.choice(acts))
    p = g.players[0]
    row = sim.ttc_row(p, g.point_row)
    for slot, pc in enumerate(g.point_row):
        assert row[slot] == (None if pc is None else ttc(p, pc))


def test_cache_returns_identical_answers():
    g = Game(["A", "B"], seed=9)
    p = g.players[0]
    pc = g.point_row[0]
    sim.clear_cache()
    cold = ttc(p, pc)
    warm = ttc(p, pc)
    assert cold == warm and sim.cache_size() >= 1


def test_simulator_does_not_touch_the_real_game():
    g = Game(["A", "B"], seed=6)
    r = random.Random(6)
    for _ in range(25):
        acts = g.legal_actions()
        if not acts:
            break
        g.apply_action(r.choice(acts))
    p = g.players[0]
    before = (list(p.caravan), list(p.hand), list(p.played))
    for pc in g.point_row:
        if pc is not None:
            ttc(p, pc, depth=4)
    assert (list(p.caravan), list(p.hand), list(p.played)) == before


# --------------------------------------------------------------------------
# Performance (§2.5: <= 1 ms average per call after caching)
# --------------------------------------------------------------------------

def test_ttc_is_fast_on_real_positions():
    positions = []
    rng = random.Random(11)
    for seed in range(12):
        g = Game(["A", "B"], seed=seed)
        while not g.game_over and len(positions) < 400:
            acts = g.legal_actions()
            if not acts:
                break
            positions.append((g.players[g.current], [c for c in g.point_row if c]))
            g.apply_action(rng.choice(acts))
        if len(positions) >= 400:
            break

    sim.clear_cache()
    calls = 0
    t0 = time.perf_counter()
    for p, row in positions:
        for pc in row:
            ttc(p, pc, depth=3)
            calls += 1
    per_ms = (time.perf_counter() - t0) / calls * 1000
    assert per_ms < 1.0, f"{per_ms:.4f} ms per TTC call, target < 1 ms"


# --------------------------------------------------------------------------
# Cache bound
# --------------------------------------------------------------------------

def test_cache_is_bounded():
    """The memo table is module-level and outlives any one game.

    A tuning worker lives for a whole run — ~2,500 games by generation 19 —
    and without a cap each of 20 processes had committed 2.2 GB, 39.8 GB on a
    15.7 GB machine. The box thrashed and generation time tripled before it
    was noticed. An unbounded cache here is a slow-motion OOM, not a leak that
    shows up in a test run.
    """
    assert sim.CACHE_LIMIT > 0
    real_limit = sim.CACHE_LIMIT
    sim.CACHE_LIMIT = 50
    try:
        sim.clear_cache()
        rng = random.Random(0)
        g = Game(["A", "B"], seed=1)
        p = g.players[0]
        for i in range(400):
            p.caravan = [rng.randrange(0, 4) for _ in range(4)]
            p.hand = [CREATE_2, UPGRADE_2][: 1 + i % 2]
            cost = tuple((Crystal(j), rng.randrange(0, 3)) for j in range(4))
            cost = tuple((c, n) for c, n in cost if n)
            if not cost:
                continue
            ttc(p, PointCard(cost, 10, "x"), depth=2)
            assert sim.cache_size() <= sim.CACHE_LIMIT, sim.cache_size()
    finally:
        sim.CACHE_LIMIT = real_limit
        sim.clear_cache()


def test_cache_still_returns_correct_answers_when_it_wraps():
    """Clearing a full cache must never change an answer, only recompute it."""
    real_limit = sim.CACHE_LIMIT
    try:
        p = make_player((0, 2, 0, 0), hand=[UPGRADE_2])
        golem = PointCard(((B, 2),), 9, "2B")
        sim.CACHE_LIMIT = 10_000
        sim.clear_cache()
        warm = ttc(p, golem)
        sim.CACHE_LIMIT = 1          # every insert wipes the table
        sim.clear_cache()
        cold = ttc(p, golem)
        assert warm == cold == 1.0
    finally:
        sim.CACHE_LIMIT = real_limit
        sim.clear_cache()

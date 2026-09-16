"""Step 4: the three bots and the paired match harness."""
from __future__ import annotations

import random

import pytest

from bots._engine import (
    Acquire,
    Claim,
    Crystal,
    CrystalCard,
    Game,
    PlayCrystal,
    PointCard,
    Rest,
    UpgradeCard,
)
from bots.bots import GreedyBot, RandomBot, WeightedBot, play_game
from bots.features import Scales, Weights
from bots.match import run_match, wilson
from bots import sim

Y, G, B, M = Crystal.YELLOW, Crystal.GREEN, Crystal.TURQUOISE, Crystal.MAGENTA
CREATE_2 = CrystalCard(((Y, 2),), "Create 2")
UPGRADE_2 = UpgradeCard(2, "Upgrade 2")


@pytest.fixture(autouse=True)
def _clear():
    sim.clear_cache()
    yield


@pytest.fixture(scope="module")
def handset():
    return Weights.load("handset_v1"), Scales.load()


# --------------------------------------------------------------------------
# RandomBot
# --------------------------------------------------------------------------

def test_random_bot_returns_a_legal_action():
    g = Game(["A", "B"], seed=1)
    bot = RandomBot(seed=0)
    assert bot.choose(g) in g.legal_actions()


def test_random_bot_is_reproducible():
    def run():
        g = Game(["A", "B"], seed=4)
        bot = RandomBot(seed=7)
        out = []
        for _ in range(30):
            a = bot.choose(g)
            if a is None or g.game_over:
                break
            out.append(repr(a))
            g.apply_action(a)
        return out
    assert run() == run()


def test_random_bot_returns_none_when_the_game_is_over():
    g = Game(["A", "B"], seed=1)
    g.game_over = True
    assert RandomBot(seed=0).choose(g) is None


# --------------------------------------------------------------------------
# GreedyBot
# --------------------------------------------------------------------------

def test_greedy_claims_when_it_can():
    g = Game(["A", "B"], seed=1)
    g.point_row = [PointCard(((G, 2),), 15, "2G=15")] + [None] * 4
    g.players[0].caravan = [0, 2, 0, 0]
    a = GreedyBot(seed=0).choose(g)
    assert isinstance(a, Claim) and a.row_index == 0


def test_greedy_prefers_the_higher_value_claim_including_the_token():
    g = Game(["A", "B"], seed=1)
    # slot 0 carries a copper (3 pts), so 10+3 beats a bare 12
    g.point_row = [PointCard(((G, 2),), 10, "a"), PointCard(((G, 2),), 12, "b")] + [None] * 3
    g.players[0].caravan = [0, 4, 0, 0]
    a = GreedyBot(seed=0).choose(g)
    assert isinstance(a, Claim) and a.row_index == 0


def test_greedy_builds_an_engine_early():
    """The brief's rule order never acquires; rule 2 exists to fix that."""
    g = Game(["A", "B"], seed=1)
    assert len(g.players[0].hand) == 2          # only the starting cards
    a = GreedyBot(seed=0).choose(g)
    assert isinstance(a, Acquire)


def test_greedy_stops_building_once_the_engine_is_big_enough():
    g = Game(["A", "B"], seed=1)
    g.players[0].hand = [CREATE_2] * 6
    a = GreedyBot(seed=0, build_until=5).choose(g)
    assert not isinstance(a, Acquire)


def test_greedy_with_build_until_zero_reproduces_the_briefs_degenerate_bot():
    """Documents the bug rather than just the fix: with the brief's ordering
    the bot never buys a card, so throughput is constant all game."""
    g = Game(["A", "B"], seed=3)
    bot = GreedyBot(seed=3, build_until=0)
    n = 0
    while not g.game_over and n < 400:
        a = bot.choose(g)
        if a is None:
            break
        assert not isinstance(a, Acquire)
        g.apply_action(a)
        n += 1
    owned = len(g.players[0].hand) + len(g.players[0].played)
    assert owned == 2


def test_greedy_actually_acquires_over_a_game():
    g = Game(["A", "B"], seed=3)
    bot = GreedyBot(seed=3)
    acquires = n = 0
    while not g.game_over and n < 400:
        a = bot.choose(g)
        if a is None:
            break
        acquires += isinstance(a, Acquire)
        g.apply_action(a)
        n += 1
    assert acquires > 0
    assert len(g.players[0].hand) + len(g.players[0].played) > 2


def test_greedy_rests_a_dead_hand():
    g = Game(["A", "B"], seed=1)
    p = g.players[0]
    p.caravan = [0, 0, 0, 2]        # magenta cannot be upgraded
    p.hand = [UPGRADE_2]
    p.played = [CREATE_2]
    g.point_row = [None] * 5        # no target, no claim
    g.merchant_row = [None] * 6     # nothing to acquire
    assert isinstance(GreedyBot(seed=0).choose(g), Rest)


def test_greedy_beats_random_decisively():
    res = run_match(lambda s: GreedyBot(seed=s), lambda s: RandomBot(seed=s),
                    range(12), a_name="greedy", b_name="random")
    assert res.a_rate > 0.9, res.summary()


# --------------------------------------------------------------------------
# WeightedBot
# --------------------------------------------------------------------------

def test_weighted_bot_picks_the_highest_scoring_move(handset):
    w, sc = handset
    g = Game(["A", "B"], seed=4)
    bot = WeightedBot(w, sc, seed=1)
    scored = bot.score_all(g)
    assert scored == sorted(scored, key=lambda t: -t[0])
    chosen = bot.choose(g)
    assert any(a == chosen and v >= scored[0][0] - 1e-9 for v, a in scored)


def test_weighted_bot_does_not_mutate_the_game(handset):
    w, sc = handset
    g = Game(["A", "B"], seed=4)
    before = (list(g.players[0].caravan), len(g.merchant_deck), len(g.point_deck),
              [c.name if c else None for c in g.merchant_row])
    WeightedBot(w, sc, seed=1).choose(g)
    after = (list(g.players[0].caravan), len(g.merchant_deck), len(g.point_deck),
             [c.name if c else None for c in g.merchant_row])
    assert before == after


def test_weighted_bot_claims_an_obviously_good_golem(handset):
    """Regression for the hoarding bug.

    The first two handset attempts valued holding resources (best_target,
    crystals, playable_now) so highly that claiming — which spends them —
    lowered V. The bot skipped 48 legal claims in one game and lost 120 of
    120. Any weighting where a free 20-point golem is not taken is broken.
    """
    w, sc = handset
    g = Game(["A", "B"], seed=1)
    g.point_row = [PointCard(((G, 2),), 20, "2G=20")] + [None] * 4
    g.players[0].caravan = [0, 2, 0, 0]
    a = WeightedBot(w, sc, seed=1).choose(g)
    assert isinstance(a, Claim), f"did not claim a free 20-pointer, chose {a}"


def test_weighted_bot_is_reproducible(handset):
    w, sc = handset

    def run():
        g = Game(["A", "B"], seed=6)
        bot = WeightedBot(w, sc, seed=3)
        out = []
        for _ in range(12):
            a = bot.choose(g)
            if a is None or g.game_over:
                break
            out.append(repr(a))
            g.apply_action(a)
        return out
    assert run() == run()


def test_weighted_bot_samples_average_over_reshuffles(handset):
    """Acquire and Claim reveal a refill card, so they are sampled."""
    w, sc = handset
    g = Game(["A", "B"], seed=4)
    one = WeightedBot(w, sc, seed=1, samples=1).score_all(g)
    three = WeightedBot(w, sc, seed=1, samples=3).score_all(g)
    assert len(one) == len(three)
    # non-revealing moves must be identical; revealing ones may differ
    for (v1, a1) in one:
        v3 = next(v for v, a in three if a == a1)
        if not isinstance(a1, (Acquire, Claim)):
            assert v1 == pytest.approx(v3)


def test_weighted_bot_returns_none_when_the_game_is_over(handset):
    w, sc = handset
    g = Game(["A", "B"], seed=1)
    g.game_over = True
    assert WeightedBot(w, sc, seed=1).choose(g) is None


# --------------------------------------------------------------------------
# play_game
# --------------------------------------------------------------------------

def test_play_game_tags_names_by_seat():
    """Game.scores() is keyed by name, so identical bots must not collide."""
    out = play_game([GreedyBot(seed=1), GreedyBot(seed=2)], seed=5)
    assert len(out["scores"]) == 2
    assert out["winner"] in (0, 1)


def test_play_game_handles_two_identical_bots():
    a, b = GreedyBot(seed=1, name="same"), GreedyBot(seed=2, name="same")
    out = play_game([a, b], seed=9)
    assert len(out["scores"]) == 2


def test_play_game_respects_the_action_cap():
    out = play_game([RandomBot(seed=1), RandomBot(seed=2)], seed=3, cap=20)
    assert out["actions"] <= 20
    assert out["capped"] is True and out["finished"] is False


def test_play_game_reports_a_finished_game():
    out = play_game([GreedyBot(seed=1), GreedyBot(seed=2)], seed=5)
    assert out["finished"] and not out["capped"]
    assert max(out["golems"]) >= 5


def test_play_game_winner_matches_the_engine_tie_break():
    """Highest seat wins a tie."""
    out = play_game([GreedyBot(seed=1), GreedyBot(seed=2)], seed=11)
    best = max(out["scores"])
    tied = [i for i, s in enumerate(out["scores"]) if s == best]
    assert out["winner"] == max(tied)


# --------------------------------------------------------------------------
# match harness
# --------------------------------------------------------------------------

def test_wilson_interval_brackets_the_rate():
    lo, hi = wilson(50, 100)
    assert lo < 0.5 < hi
    assert 0.0 <= wilson(0, 10)[0] and wilson(10, 10)[1] <= 1.0
    # wider at small n
    assert (wilson(5, 10)[1] - wilson(5, 10)[0]) > (wilson(500, 1000)[1] - wilson(500, 1000)[0])


def test_run_match_plays_every_seed_in_both_seatings():
    res = run_match(lambda s: GreedyBot(seed=s), lambda s: RandomBot(seed=s),
                    range(5), a_name="greedy", b_name="random")
    assert res.games == 10
    assert res.seat_games == {0: 5, 1: 5}


def test_run_match_wins_sum_to_games():
    res = run_match(lambda s: GreedyBot(seed=s), lambda s: RandomBot(seed=s),
                    range(6), a_name="a", b_name="b")
    assert res.a_wins + res.b_wins == res.games


def test_run_match_is_reproducible():
    def run():
        r = run_match(lambda s: GreedyBot(seed=s), lambda s: RandomBot(seed=s),
                      range(6), a_name="a", b_name="b")
        return r.a_wins, r.margins
    assert run() == run()


def test_a_mirror_match_is_near_even():
    """Same bot both sides: seat swapping should cancel any seat advantage.

    Not exactly 50% — the two sides get different RNG streams — but a large
    imbalance would mean the pairing is broken.
    """
    res = run_match(lambda s: GreedyBot(seed=s), lambda s: GreedyBot(seed=s + 500),
                    range(40), a_name="g1", b_name="g2")
    lo, hi = res.ci
    assert lo < 0.5 < hi, res.summary()


def test_handset_beats_greedy(handset):
    """Step 4's acceptance bar: >60% of paired games, seats swapped.

    Small sample here to keep the suite fast; the reported figure comes from
    a 120-game run on held-out seeds (see API_NOTES §11).
    """
    w, sc = handset
    res = run_match(lambda s: WeightedBot(w, sc, seed=s, name="handset"),
                    lambda s: GreedyBot(seed=s),
                    range(8), a_name="handset", b_name="greedy")
    assert res.a_rate > 0.6, res.summary()

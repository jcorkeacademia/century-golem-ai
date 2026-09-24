"""Step 5: the starting upper bound.

The roadmap's check is "always finishes; gives starting b". Beyond that, two
things matter: b must be a turn count the plan really achieves (or the
search would chase a number it can never reproduce), and the solo patch must
never leak into `bots/`, which practice mode uses.
"""

from __future__ import annotations

import pytest

import bots.features as features
from solver.greedy import Plan, _solo_scoring, upper_bound, verify
from solver.solo import new_solo_game

SEEDS = range(3)


@pytest.mark.parametrize("seed", SEEDS)
def test_upper_bound_finishes_and_replays(seed):
    plan = upper_bound(seed)
    assert plan.turns > 0
    verify(seed, plan)          # upper_bound already did; this is the check


@pytest.mark.parametrize("seed", SEEDS)
def test_the_tuned_bot_beats_plain_greedy(seed):
    """Why this module uses WeightedBot at all: over seeds 0-19 it averaged
    39.5 turns against GreedyBot's 60.6. On a tiny sample the best-of must at
    least never be worse than greedy alone."""
    greedy_only = upper_bound(seed, weights=(), include_greedy=True)
    best = upper_bound(seed)
    assert best.turns <= greedy_only.turns


def test_same_seed_same_b():
    assert upper_bound(0).turns == upper_bound(0).turns


def test_a_wrong_turn_count_fails_verification():
    plan = upper_bound(0)
    with pytest.raises(AssertionError):
        verify(0, Plan(plan.turns - 1, plan.actions, plan.bot))


def test_a_plan_that_does_not_finish_fails_verification():
    plan = upper_bound(0)
    short = plan.actions[:-1]
    with pytest.raises(AssertionError):
        verify(0, Plan(plan.turns - 1, short, plan.bot))


def test_a_plan_for_another_seed_fails_verification():
    plan = upper_bound(0)
    with pytest.raises(Exception):
        verify(1, plan)


# ---------------------------------------------------------------------------
# The patch must not leak into bots/, which the multiplayer game imports
# ---------------------------------------------------------------------------

def test_solo_scoring_is_restored_afterwards():
    original = features.terminal_value
    upper_bound(0)
    assert features.terminal_value is original


def test_solo_scoring_is_restored_even_on_error():
    original = features.terminal_value
    with pytest.raises(RuntimeError):
        with _solo_scoring():
            assert features.terminal_value is not original
            raise RuntimeError("boom")
    assert features.terminal_value is original


def test_multiplayer_scoring_still_needs_an_opponent():
    """Outside the patch, terminal_value is the multiplayer original: it
    still compares against opponents, so it still fails on a solo game."""
    upper_bound(0)
    with pytest.raises(ValueError):
        features.terminal_value(new_solo_game(seed=0), 0)

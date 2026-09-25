"""Step 7: dfbb and brute force agree on tiny boards.

The fast tier runs here. The thorough tier (two golems, slower) is marked
slow; run it with `pytest -m slow` or `python -m solver.tiny`, and rerun it
after every step-8 speed-up.
"""

from __future__ import annotations

import random

import pytest

import solver.search as search
from bots._engine import MERCHANT_CARDS
from solver.search import all_moves, cheap_payments
from solver.tiny import (CHEAPEST_GOLEMS, Board, brute_force, check,
                         fast_board, rule_check, thorough_board)


@pytest.mark.parametrize("seed", range(20))
def test_dfbb_agrees_with_brute_force_on_fast_boards(seed):
    outcome = check(fast_board(seed))
    assert outcome.status == "agree", (
        f"brute={outcome.brute} dfbb={outcome.dfbb}")


@pytest.mark.slow
@pytest.mark.parametrize("seed", range(15))
def test_dfbb_agrees_with_brute_force_on_thorough_boards(seed):
    outcome = check(thorough_board(seed))
    if outcome.status == "skipped":
        pytest.skip("board too big for the brute force")
    assert outcome.status == "agree", (
        f"brute={outcome.brute} dfbb={outcome.dfbb}")


def test_the_check_catches_an_inadmissible_bound(monkeypatch):
    """Step 7 is only worth having if it fails when h is wrong. Inflate h by
    two turns — an overestimate — and at least one board must disagree."""
    real_h = search.h
    monkeypatch.setattr(search, "h", lambda game: real_h(game) + 2)
    statuses = {check(fast_board(seed)).status for seed in range(10)}
    assert "DISAGREE" in statuses


def test_brute_force_on_a_one_move_win():
    """A board where the golem is affordable at once: the optimum is 1."""
    rng = random.Random(0)
    board = Board(0, tuple(rng.sample(MERCHANT_CARDS, 6)),
                  tuple(rng.sample(CHEAPEST_GOLEMS[:10], 5)),
                  target=1, start=(4, 3, 3, 0))   # pays any of the cheapest ten
    assert brute_force(board.game()) == 1


@pytest.mark.parametrize("seed", range(20))
def test_yellow_green_payments_never_cost_turns(seed):
    """The user's rule: acquires are only worth paying in yellow and green.
    Not provable in general, so measured: the optimum with the rule equals
    the optimum with every move, on boards that START holding blue and
    magenta, which is where the rule could bite."""
    rng = random.Random(1000 + seed)
    start = (rng.randint(0, 2), rng.randint(0, 2), rng.randint(1, 3), rng.randint(0, 2))
    board = Board(1000 + seed, tuple(rng.sample(MERCHANT_CARDS, 6)),
                  tuple(rng.sample(CHEAPEST_GOLEMS[:14], 5)), 1, start)
    result = rule_check(board, max_states=150_000)
    if result is None:
        pytest.skip("too big")
    full, cut = result
    assert full == cut


def test_cheap_payments_only_removes_blue_and_magenta_acquires():
    game = fast_board(0).game()
    game.players[0].caravan = [2, 2, 2, 2]
    kept, every = cheap_payments(game), all_moves(game)
    removed = [a for a in every if a not in kept]
    assert removed, "with blue and magenta held, some payments use them"
    for a in removed:
        assert type(a).__name__ == "Acquire"
        assert any(c >= 2 for c in a.payment)

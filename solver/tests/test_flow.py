"""The crystal-flow lower bound. Slow (~1s a call), so these stay few."""

from __future__ import annotations

import random

import pytest

from bots._engine import Discard
from bots.bots import GreedyBot
from solver.bound import h
from solver.flow import flow_bound
from solver.search import cheap_payments
from solver.solo import new_solo_game
from solver.tiny import brute_force, fast_board


def test_zero_once_the_goal_is_reached():
    game = new_solo_game(seed=0)
    game.players[0].point_cards = list(game.point_deck[:6])
    assert flow_bound(game) == 0


def test_opening_bound_beats_h():
    """Measured on seeds 0-9: flow 16-19 against h 15-18."""
    for seed in (0, 9):
        game = new_solo_game(seed=seed)
        assert flow_bound(game) > h(game)


@pytest.mark.parametrize("seed", [0, 3, 6])
def test_never_above_the_brute_force_on_tiny_boards(seed):
    """Tiny boards use a small merchant deck; the bound prices every card in
    the compendium, a superset, which can only make it lower — still safe.
    The brute force here uses ALL moves, so it is the true optimum."""
    board = fast_board(seed)
    truth = brute_force(board.game())
    assert flow_bound(board.game()) <= truth


def test_never_above_what_a_real_game_took():
    game = new_solo_game(seed=5)
    bot, rng = GreedyBot(seed=5), random.Random(5)
    trace = []
    while not game.game_over:
        action = bot.choose(game) or rng.choice(game.legal_actions())
        trace.append((game.clone(), action))
        game.apply_action(action)
    # turns still to play from position i: discards ride along, not counted
    left = [sum(1 for _, a in trace[i:] if not isinstance(a, Discard))
            for i in range(len(trace))]
    for i in (0, len(trace) // 2, len(trace) - 3):
        assert flow_bound(trace[i][0]) <= left[i]

"""Step 6: depth-first branch and bound.

The roadmap's check is that the returned plan replays on a fresh same-seed
game and wins in exactly the turns claimed. From the opening position the
search does not finish (the tree is far too big for the current h), so the
tests that need a *finished* search start from late-game positions, where it
does, and compare against a plain exhaustive search.
"""

from __future__ import annotations

import random

import pytest

from bots._engine import Discard, PlayCrystal
from bots.bots import GreedyBot
from solver.search import OutOfBudget, Stats, dfbb, solve, turn_cost
from solver.solo import new_solo_game, turns_in


def test_turn_cost():
    assert turn_cost(Discard((1, 0, 0, 0))) == 0
    assert turn_cost(PlayCrystal(0)) == 1


def test_solve_on_a_budget_returns_a_verified_but_unproven_plan():
    """The full board does not finish; the greedy plan comes back, replayed
    and correctly flagged as not proven optimal."""
    result = solve(0, node_budget=200)
    assert not result.optimal
    assert result.plan.turns > 0          # solve() already ran verify()
    assert result.stats.nodes > 200


def _late_positions(seed, claimed=5):
    """Positions from a greedy game with `claimed` golems, plus greedy's own
    remaining line from each, which serves as the starting b."""
    game = new_solo_game(seed=seed)
    bot, rng = GreedyBot(seed=seed), random.Random(seed)
    line = []
    while not game.game_over:
        action = bot.choose(game) or rng.choice(game.legal_actions())
        line.append((game.clone(), action))
        game.apply_action(action)
    for i, (snap, _) in enumerate(line):
        if len(snap.players[0].point_cards) == claimed:
            yield snap, [a for _, a in line[i:]]


def _fewest_turns(game, limit):
    """Plain exhaustive search, no bound: fewest turns to win, or None if it
    takes more than `limit`. The thing dfbb must agree with."""
    if game.game_over:
        return 0
    if limit == 0 and game.pending_discard is None:
        return None
    best = None
    for action in game.legal_actions():
        child = game.clone()
        child.apply_action(action)
        cost = turn_cost(action)
        sub = _fewest_turns(child, limit - cost)
        if sub is not None and (best is None or sub + cost < best):
            best = sub + cost
    return best


@pytest.mark.parametrize("seed", [0, 3, 6, 8])
def test_dfbb_agrees_with_exhaustive_search_near_the_end(seed):
    checked = 0
    for snap, rest in _late_positions(seed):
        best = {"turns": turns_in(rest), "actions": tuple(rest)}
        try:
            dfbb(snap.clone(), 0, [], best, Stats(), 3_000, None)
        except OutOfBudget:
            continue
        truth = _fewest_turns(snap, 2)
        if truth is None:
            continue
        assert best["turns"] == truth

        replay = snap.clone()
        for action in best["actions"]:
            replay.apply_action(action)
        assert replay.game_over and turns_in(best["actions"]) == best["turns"]
        checked += 1
    assert checked, "no position was checkable; pick another seed"


def test_budget_stops_the_search():
    snap, rest = next(_late_positions(1, claimed=4))
    best = {"turns": turns_in(rest), "actions": tuple(rest)}
    stats = Stats()
    with pytest.raises(OutOfBudget):
        dfbb(snap, 0, [], best, stats, 5, None)
    assert stats.nodes == 6


def test_a_finished_search_from_a_winnable_position_says_one_turn():
    """If a golem is affordable right now, the optimum is exactly 1."""
    for snap, rest in _late_positions(8):
        if turns_in(rest) == 1:
            best = {"turns": 99, "actions": ()}
            dfbb(snap, 0, [], best, Stats(), None, None)
            assert best["turns"] == 1
            return
    pytest.skip("no one-turn finish on this seed")

"""Chained sub-goals: each segment is proven fastest to its golem, and the
chained plan is a real, verified win."""

from __future__ import annotations

from bots._engine import Claim
from solver.chain import _sub_goal, chain, next_golem
from solver.search import Stats, cheap_payments, dfbb
from solver.solo import new_solo_game


def test_the_sub_goal_is_one_more_golem_on_a_copy():
    game = new_solo_game(seed=0)
    sub = _sub_goal(game)
    assert sub.win_target == 1 and game.win_target == 6
    assert _sub_goal(game, step=9).win_target == 6       # never past the real goal


def test_a_segment_ends_on_its_claim_and_is_proven_fastest():
    game = new_solo_game(seed=0)
    seg = next_golem(game, seed=0)
    assert seg.proven and isinstance(seg.actions[-1], Claim)
    # no route to the first golem is shorter: rerun the proof from one turn less
    best = {"turns": seg.turns, "actions": ()}
    dfbb(_sub_goal(game), 0, [], best, Stats(), None, None,
         moves=cheap_payments, seen={})
    assert best["turns"] == seg.turns


def test_the_chain_is_a_verified_win_of_proven_segments():
    result = chain(0)                                   # verify() runs inside
    assert result.all_proven
    assert result.plan.turns == sum(s.turns for s in result.segments)
    assert len(result.segments) == 6

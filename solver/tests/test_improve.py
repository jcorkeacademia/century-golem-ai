"""Upper-bound improvement: every plan is a real win, never longer than its
input, and the bot-scoring patch never leaks out."""

from __future__ import annotations

import random

import bots.features as features
from bots.bots import GreedyBot
from solver.greedy import Plan, upper_bound, verify
from solver.improve import beam, repair
from solver.solo import new_solo_game, turns_in


def _greedy_plan(seed):
    """GreedyBot's line: deliberately weak, so repair has something to fix."""
    game = new_solo_game(seed=seed)
    bot, rng = GreedyBot(seed=seed), random.Random(seed)
    actions = []
    while not game.game_over:
        action = bot.choose(game) or rng.choice(game.legal_actions())
        game.apply_action(action)
        actions.append(action)
    return Plan(turns_in(actions), tuple(actions), "greedy")


def test_repair_shortens_a_weak_plan_and_it_still_replays():
    plan = _greedy_plan(1)
    fixed = repair(1, plan, node_budget=300)
    verify(1, fixed)
    assert fixed.turns < plan.turns


def test_repair_never_lengthens_a_plan():
    plan = upper_bound(0)
    fixed = repair(0, plan, node_budget=200)
    verify(0, fixed)
    assert fixed.turns <= plan.turns


def test_beam_finds_a_verified_win():
    plan = beam(0, width=10)
    assert plan is not None
    verify(0, plan)


def test_a_wider_beam_is_no_worse_on_this_seed():
    """Not a law — beams are not monotone in width in general — but measured
    on seed 0 (20/100/300/1000 -> 38/35/34/31), and a regression here means
    the ranking broke."""
    assert beam(0, width=40).turns <= beam(0, width=10).turns


def test_beam_restores_the_multiplayer_scoring():
    original = features.terminal_value
    beam(0, width=5)
    assert features.terminal_value is original

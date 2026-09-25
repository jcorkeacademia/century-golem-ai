"""fast_clone must be Game.clone() in everything but speed.

It is a second copy routine the engine does not know about, so these tests
exist to catch it drifting: a missing field, a shared container, or an rng
that turns out to be used after all.
"""

from __future__ import annotations

import random
from collections import Counter

import pytest

from bots._engine import Game
from solver.fastclone import KNOWN_FIELDS, LOG_FIELDS, fast_clone
from solver.solo import new_solo_game
from solver.tiny import fast_board


def _positions(seed):
    """Every position of a random game — solo real, and a tiny board — which
    between them include pending discards and a finished game."""
    for game in (new_solo_game(seed=seed), fast_board(seed).game()):
        rng = random.Random(seed)
        while True:
            yield game
            if game.game_over:
                break
            game.apply_action(rng.choice(game.legal_actions()))


def _state(game):
    """Every field except rng, which fast_clone shares on purpose."""
    return {k: v for k, v in vars(game).items() if k != "rng"}


@pytest.mark.parametrize("game", [
    new_solo_game(seed=0),
    Game(["a", "b", "c"], seed=0),
    Game(["a", "b"], seed=0, log=True),
], ids=["solo", "three-player", "logged"])
def test_every_game_field_is_one_fast_clone_knows(game):
    """If the engine grows a field, this fails until fastclone copies it."""
    unknown = set(vars(game)) - KNOWN_FIELDS - LOG_FIELDS
    assert not unknown, f"fast_clone does not copy {sorted(unknown)}"
    assert set(vars(fast_clone(game))) == set(vars(game.clone()))


@pytest.mark.parametrize("seed", range(4))
def test_fast_clone_equals_clone_on_every_position(seed):
    for game in _positions(seed):
        assert _state(fast_clone(game)) == _state(game.clone())


@pytest.mark.parametrize("seed", range(4))
def test_playing_on_a_fast_clone_leaves_the_parent_alone(seed):
    """Every container must be a copy, not shared — the whole point."""
    rng = random.Random(seed)
    for game in _positions(seed):
        if game.game_over:
            continue
        before = _state(game.clone())
        child = fast_clone(game)
        child.apply_action(rng.choice(child.legal_actions()))
        assert _state(game) == before


@pytest.mark.parametrize("seed", range(4))
def test_a_move_on_a_fast_clone_matches_the_same_move_on_a_clone(seed):
    rng = random.Random(seed)
    for game in _positions(seed):
        if game.game_over:
            continue
        action = rng.choice(game.legal_actions())
        a, b = fast_clone(game), game.clone()
        a.apply_action(action)
        b.apply_action(action)
        assert _state(a) == _state(b)


def test_row_crystals_are_real_independent_counters():
    game = new_solo_game(seed=0)
    game.row_crystals[0][0] = 2
    copy = fast_clone(game)
    assert all(type(rc) is Counter for rc in copy.row_crystals)
    copy.row_crystals[0][0] += 1
    copy.row_crystals[1][3] += 1          # missing keys still default to 0
    assert game.row_crystals[0][0] == 2 and game.row_crystals[1][3] == 0


@pytest.mark.parametrize("seed", range(4))
def test_nothing_draws_from_rng_after_setup(seed):
    """Sharing the parent's rng is only safe because play never uses it."""
    for game in (new_solo_game(seed=seed), Game(["a", "b"], seed=seed)):
        state = game.rng.getstate()
        rng = random.Random(seed)
        while not game.game_over:
            game.apply_action(rng.choice(game.legal_actions()))
        assert game.rng.getstate() == state

"""Step 1: solo mode, real cards, fixed seed.

The roadmap's check for this step is one line — "a random solo game runs to 6
golems without errors" — and `test_random_solo_game_reaches_the_goal` is it.
The rest of this file pins the surrounding assumptions the search will lean
on, and guards the 2-5 player game against the widened player-count check.
"""

from __future__ import annotations

import random

import pytest

from bots._engine import Claim, Game
from solver.solo import claimed, goal, new_solo_game

# Random solo play is wasteful: measured over seeds 0-7 it takes 174-553
# turns to stumble into six golems. The cap is well clear of that, and a
# capped run fails the test rather than passing quietly.
RANDOM_TURN_CAP = 2000

SEEDS = range(5)


def play_randomly(game: Game, rng: random.Random, cap: int = RANDOM_TURN_CAP) -> list:
    """Uniformly random legal play until the game ends. Returns the actions.

    Deliberately not `bots.bots.RandomBot`: this check should fail if the
    *engine* cannot finish a solo game, not be entangled with how the bot
    package happens to choose or cap moves today.
    """
    actions = []
    while not game.game_over and len(actions) < cap:
        legal = game.legal_actions()
        assert legal, f"no legal action at turn {len(actions)} of a live game"
        action = rng.choice(legal)
        game.apply_action(action)
        actions.append(action)
    return actions


# ---------------------------------------------------------------------------
# The board
# ---------------------------------------------------------------------------

def test_solo_game_constructs():
    g = new_solo_game(seed=0)
    assert g.n == 1
    assert g.current == 0
    assert not g.game_over
    assert goal(g) == 6, "solo plays to the 2-3p target of six golems"
    assert claimed(g) == 0


def test_solo_seat_gets_the_seat_zero_opening():
    g = new_solo_game(seed=0)
    p = g.players[0]
    assert p.caravan == [3, 0, 0, 0], "seat 0 opens on three yellow"
    assert [c.name for c in p.hand] == ["Create 2", "Upgrade 2"]
    # Token piles are sized n*2, so solo has two of each. Irrelevant to a
    # turn-minimising search, but it should not be empty or crash the claim.
    assert [len(t) for t in g.point_tokens] == [2, 2, 0, 0, 0]


def test_player_count_bounds():
    with pytest.raises(ValueError):
        Game([])
    with pytest.raises(ValueError):
        Game([f"p{i}" for i in range(6)])


def test_real_compendium_loaded_by_default():
    g = new_solo_game(seed=1)
    assert len(g.merchant_row) == 6 and len(g.merchant_deck) == 37  # 43 total
    assert len(g.point_row) == 5 and len(g.point_deck) == 31        # 36 total
    assert all(c is not None for c in g.merchant_row + g.point_row)


# ---------------------------------------------------------------------------
# The seed fixes the instance
# ---------------------------------------------------------------------------

def test_same_seed_gives_the_same_board():
    a, b = new_solo_game(seed=42), new_solo_game(seed=42)
    assert [c.name for c in a.merchant_row] == [c.name for c in b.merchant_row]
    assert [c.name for c in a.point_row] == [c.name for c in b.point_row]
    # Deck *order* too, not just the visible row: the deterministic search
    # searches through refills, so the whole instance has to be reproducible.
    assert [c.name for c in a.merchant_deck] == [c.name for c in b.merchant_deck]
    assert [c.name for c in a.point_deck] == [c.name for c in b.point_deck]


def test_different_seeds_give_different_boards():
    a, b = new_solo_game(seed=1), new_solo_game(seed=2)
    assert [c.name for c in a.merchant_deck] != [c.name for c in b.merchant_deck]


def test_replaying_a_plan_on_a_fresh_game_reproduces_it():
    """The property step 6 checks its DFBB plans with, proved here on random
    play: same seed + same actions => same result."""
    plan = play_randomly(new_solo_game(seed=3), random.Random(3))
    replay = new_solo_game(seed=3)
    for action in plan:
        replay.apply_action(action)
    assert replay.game_over
    assert claimed(replay) == 6


# ---------------------------------------------------------------------------
# The step-1 check
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", SEEDS)
def test_random_solo_game_reaches_the_goal(seed):
    game = new_solo_game(seed=seed)
    actions = play_randomly(game, random.Random(seed))

    assert len(actions) < RANDOM_TURN_CAP, "random play hit the turn cap"
    assert game.game_over
    assert claimed(game) == goal(game) == 6
    assert game.winner() == "solo"
    assert game.legal_actions() == [], "a finished game offers no moves"


@pytest.mark.parametrize("seed", SEEDS)
def test_the_game_ends_on_the_claiming_turn(seed):
    """No trailing final round when there is nobody else to give a turn to.

    This is what lets the search treat `len(plan)` as the turn count with no
    correction: the last action of a solo game is always the winning Claim.
    """
    game = new_solo_game(seed=seed)
    actions = play_randomly(game, random.Random(seed))

    assert isinstance(actions[-1], Claim)
    assert game.end_triggered
    # The claim that triggered the end is the same turn that ended the game:
    # six golems were not held before it.
    replay = new_solo_game(seed=seed)
    for action in actions[:-1]:
        replay.apply_action(action)
    assert not replay.game_over
    assert claimed(replay) == 5


# ---------------------------------------------------------------------------
# The multiplayer game is untouched
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n,target", [(2, 6), (3, 6), (4, 5), (5, 5)])
def test_multiplayer_win_targets_unchanged(n, target):
    g = Game([f"p{i}" for i in range(n)], seed=0)
    assert g.win_target == target
    assert [len(t) for t in g.point_tokens][:2] == [n * 2, n * 2]


def test_multiplayer_still_plays_a_full_round_after_the_trigger():
    """The n=1 shortcut must not have cost the multiplayer final round."""
    game = Game(["a", "b", "c"], seed=11)
    rng = random.Random(11)
    triggered_at = None
    turns = 0
    while not game.game_over and turns < RANDOM_TURN_CAP:
        game.apply_action(rng.choice(game.legal_actions()))
        turns += 1
        if triggered_at is None and game.end_triggered:
            triggered_at = turns
    assert game.game_over
    # Everyone gets the same number of turns: play stops on the wrap to seat 0.
    assert turns % 3 == 0
    assert triggered_at is not None and turns >= triggered_at

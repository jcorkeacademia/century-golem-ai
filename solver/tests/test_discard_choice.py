"""Step 3: the over-limit discard as a choice.

By the real rules, a player who goes over the ten-crystal caravan limit picks
what to throw away. The engine has always picked for them — cheapest first,
which means yellow first, which means it throws away the crystals that pay
for acquisitions. For a solver that is not a cosmetic difference: it can make
an optimal line look slower than it is, and the search would report the wrong
answer as proven.

`discard_choice=True` surfaces the choice instead. It is opt-in, and the
multiplayer default is unchanged — the last two tests here are what hold that
line.
"""

from __future__ import annotations

import random

import pytest

from bots._engine import (CARAVAN_LIMIT, Crystal, CrystalCard, Discard, Game,
                          IllegalAction, PlayCrystal)
from solver.solo import new_solo_game

# The overflow position used throughout: holding 4Y 3G 2B, playing a card that
# makes three green takes the caravan to twelve, so two crystals must go.
OVERFLOW_CARAVAN = [4, 3, 2, 0]


def _overflowing(g: Game) -> Game:
    p = g.players[0]
    p.caravan = OVERFLOW_CARAVAN[:]
    p.hand = [CrystalCard(((Crystal.GREEN, 3),), "Create 3G")]
    return g


def overflowing_game(**kwargs) -> Game:
    """Via `new_solo_game`, so it inherits the solver's opt-in default."""
    return _overflowing(new_solo_game(seed=0, **kwargs))


def overflowing_engine_default() -> Game:
    """Via `Game` directly, so it gets the ENGINE's default — which is what
    the multiplayer server and UI construct."""
    return _overflowing(Game(["solo"], seed=0))


# ---------------------------------------------------------------------------
# The default is exactly what it always was
# ---------------------------------------------------------------------------

def test_default_still_drops_the_cheapest():
    g = overflowing_engine_default()
    g.apply_action(PlayCrystal(0))
    assert g.players[0].caravan == [2, 6, 2, 0], "cheapest-first, i.e. yellow"
    assert g.last_discard == [2, 0, 0, 0]
    assert g.pending_discard is None, "no sub-decision unless asked for"
    assert not g.discard_choice


def test_default_never_offers_a_discard_action():
    """Across real play, an engine built the old way must never produce a
    pending discard or a Discard among its legal moves."""
    for seed in range(3):
        g = Game([f"p{i}" for i in range(3)], seed=seed)
        rng = random.Random(seed)
        while not g.game_over:
            legal = g.legal_actions()
            assert not any(isinstance(a, Discard) for a in legal)
            g.apply_action(rng.choice(legal))
            assert g.pending_discard is None


# ---------------------------------------------------------------------------
# With the flag on
# ---------------------------------------------------------------------------

def test_overflow_becomes_a_pending_choice():
    g = overflowing_game(discard_choice=True)
    g.apply_action(PlayCrystal(0))
    assert g.pending_discard == 2
    assert g.players[0].caravan == [4, 6, 2, 0], "nothing dropped yet"
    assert g.players[0].total_crystals() == 12, "over the limit, mid-move"


def test_every_choice_is_offered_and_only_choices_are():
    g = overflowing_game(discard_choice=True)
    g.apply_action(PlayCrystal(0))
    legal = g.legal_actions()
    assert all(isinstance(a, Discard) for a in legal), "nothing else may happen"
    assert {a.counts for a in legal} == {
        (2, 0, 0, 0), (1, 1, 0, 0), (1, 0, 1, 0),
        (0, 2, 0, 0), (0, 1, 1, 0), (0, 0, 2, 0),
    }
    assert all(sum(a.counts) == 2 for a in legal)


def test_the_player_can_keep_the_yellow():
    """The whole point: the choice the auto-discard could not make."""
    g = overflowing_game(discard_choice=True)
    g.apply_action(PlayCrystal(0))
    g.apply_action(Discard((0, 2, 0, 0)))
    assert g.players[0].caravan == [4, 4, 2, 0], "all four yellow kept"
    assert g.players[0].total_crystals() == CARAVAN_LIMIT
    assert g.pending_discard is None
    assert g.last_discard == [0, 2, 0, 0]


def test_the_turn_does_not_pass_until_it_is_resolved():
    g = Game(["a", "b"], seed=0, discard_choice=True)
    p = g.players[0]
    p.caravan = OVERFLOW_CARAVAN[:]
    p.hand = [CrystalCard(((Crystal.GREEN, 3),), "Create 3G")]
    g.apply_action(PlayCrystal(0))
    assert g.current == 0, "still the same player's move, mid-resolution"
    g.apply_action(Discard((2, 0, 0, 0)))
    assert g.current == 1, "and now the turn passes"


@pytest.mark.parametrize("bad,why", [
    ((1, 0, 0, 0), "too few"),
    ((3, 0, 0, 0), "too many"),
    ((0, 0, 0, 2), "crystals not held"),
    ((5, 0, 0, 0), "more of a color than held"),
])
def test_illegal_discards_are_rejected(bad, why):
    g = overflowing_game(discard_choice=True)
    g.apply_action(PlayCrystal(0))
    with pytest.raises(IllegalAction):
        g.apply_action(Discard(bad))
    assert g.pending_discard == 2, f"{why}: still owed after a rejected try"


def test_nothing_else_may_happen_while_one_is_pending():
    g = overflowing_game(discard_choice=True)
    g.apply_action(PlayCrystal(0))
    with pytest.raises(IllegalAction, match="discard"):
        g.apply_action(PlayCrystal(0))


def test_discard_is_not_pending_when_the_move_fits():
    g = new_solo_game(seed=0, discard_choice=True)
    g.apply_action(PlayCrystal(0))          # 3Y -> 5Y, nowhere near the limit
    assert g.pending_discard is None
    assert not any(isinstance(a, Discard) for a in g.legal_actions())


def test_a_clone_carries_the_pending_decision():
    g = overflowing_game(discard_choice=True)
    g.apply_action(PlayCrystal(0))
    c = g.clone()
    assert c.discard_choice and c.pending_discard == 2
    c.apply_action(Discard((2, 0, 0, 0)))
    assert c.players[0].caravan == [2, 6, 2, 0]
    assert g.players[0].caravan == [4, 6, 2, 0], "the original is untouched"
    assert g.pending_discard == 2


def test_a_whole_solo_game_plays_through_with_the_flag_on():
    """Random play with the choice enabled still finishes, and every discard
    it is asked for is resolved before the next move."""
    for seed in range(3):
        g = new_solo_game(seed=seed, discard_choice=True)
        rng = random.Random(seed)
        turns = discards = 0
        while not g.game_over and turns + discards < 3000:
            action = rng.choice(g.legal_actions())
            g.apply_action(action)
            if isinstance(action, Discard):
                discards += 1
            else:
                turns += 1
            assert g.players[0].total_crystals() <= CARAVAN_LIMIT or g.pending_discard
        assert g.game_over
        assert len(g.players[0].point_cards) == 6
        assert discards > 0, "seed never overflowed; pick a livelier one"

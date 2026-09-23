"""Step 2: `key()`.

The roadmap's check for step 2 is that applying an action to a clone leaves
the original untouched — already covered by seven tests in
bots/tests/test_engine_step1.py, since `clone()` predates the solver. What is
new here is the fingerprint, so these tests are about the two ways a key can
be wrong:

  too coarse — two positions that differ in something that matters collide,
               and the search skips a line that was actually better;
  too fine   — two interchangeable positions look different, and the
               seen-state table never fires.

Both failure modes are silent at runtime, which is why they are pinned here.
"""

from __future__ import annotations

import random

import pytest

from bots._engine import Crystal, CrystalCard, Game, PlayCrystal, PlayUpgrade
from bots.sim import card_id
from solver.solo import new_solo_game
from solver.state import assert_goal_is_turns, key


def test_key_is_hashable_and_stable():
    g = new_solo_game(seed=0)
    k = key(g)
    assert isinstance(hash(k), int)
    assert k == key(g), "key must be a pure function of the position"
    assert key(new_solo_game(seed=0)) == k, "same seed, same opening position"


def test_a_clone_keys_the_same_and_diverges_on_a_move():
    g = new_solo_game(seed=0)
    c = g.clone()
    assert key(c) == key(g)
    c.apply_action(c.legal_actions()[0])
    assert key(c) != key(g), "the clone moved; the original did not"
    assert key(g) == key(new_solo_game(seed=0))


# ---------------------------------------------------------------------------
# Too fine: things that must NOT split the key
# ---------------------------------------------------------------------------

def test_hand_order_does_not_matter():
    a, b = new_solo_game(seed=0), new_solo_game(seed=0)
    b.players[0].hand.reverse()
    assert key(a) == key(b), "legal_actions offers every card whatever the order"


def test_played_pile_order_does_not_matter():
    a, b = new_solo_game(seed=0), new_solo_game(seed=0)
    for g in (a, b):
        g.apply_action(PlayCrystal(0))
        g.apply_action(g.legal_actions()[0])
    assert len(a.players[0].played) >= 2
    b.players[0].played.reverse()
    assert key(a) == key(b), "Rest returns the whole pile; order is irrelevant"


def test_tokens_and_score_do_not_split_the_key():
    """The goal is turns. A token changes your score and nothing else."""
    a, b = new_solo_game(seed=0), new_solo_game(seed=0)
    b.players[0].tokens.append(b.point_tokens[0][0])
    assert b.players[0].score() != a.players[0].score()
    assert key(a) == key(b)


def test_two_mechanically_identical_cards_collapse():
    a, b = new_solo_game(seed=0), new_solo_game(seed=0)
    same_thing = CrystalCard(((Crystal.YELLOW, 2),), "a different name")
    a.players[0].hand = [same_thing]
    b.players[0].hand = [CrystalCard(((Crystal.YELLOW, 2),), "Create 2")]
    assert key(a) == key(b), "cards are keyed by what they do, not by name"


# ---------------------------------------------------------------------------
# Too coarse: things that MUST split the key
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mutate,why", [
    (lambda g: g.players[0].caravan.__setitem__(0, 9), "caravan"),
    (lambda g: g.players[0].hand.pop(), "hand"),
    (lambda g: g.players[0].played.append(g.players[0].hand.pop()), "played pile"),
    (lambda g: g.merchant_row.reverse(), "merchant row order is its price"),
    (lambda g: g.point_row.__setitem__(0, g.point_deck[-1]), "point row"),
    (lambda g: g.row_crystals[2].update({Crystal.YELLOW: 1}), "crystals on a row card"),
    (lambda g: g.merchant_deck.pop(), "merchant deck position"),
    (lambda g: g.point_deck.pop(), "point deck position"),
    (lambda g: g.players[0].point_cards.append(g.point_row[0]), "claimed count"),
])
def test_these_must_split_the_key(mutate, why):
    a, b = new_solo_game(seed=0), new_solo_game(seed=0)
    mutate(b)
    assert key(a) != key(b), f"{why} affects a future move but did not split the key"


def test_golem_identity_collapses_but_count_does_not():
    """The one collapse worth stating out loud: *which* golems you claimed is
    inert, but *how many* decides when the game ends."""
    a, b = new_solo_game(seed=0), new_solo_game(seed=0)
    # Same number of claims, different cards, matching costs.
    a.players[0].point_cards.append(a.point_row[0])
    b.players[0].point_cards.append(a.point_row[0])
    assert key(a) == key(b)
    b.players[0].point_cards.append(b.point_row[1])
    assert key(a) != key(b), "one claim closer to the end is a different position"


# ---------------------------------------------------------------------------
# The property the seen-state table actually relies on
# ---------------------------------------------------------------------------

def move_signature(game) -> list[str]:
    """Legal moves, with hand *indices* resolved to the card they name.

    Actions address a card by its position in hand, but the key deliberately
    ignores hand order. So two equal-keyed positions really can offer
    `PlayCrystal(11)` and `PlayCrystal(12)` for the same card, and comparing
    raw actions would report a difference that is only a label.

    Worth knowing beyond this test: it means a plan recorded in one position
    is not replayable move-for-move in an equal-keyed one. That is fine for a
    seen-state table, which only ever *prunes* — but any future code that
    reuses a stored plan across a key match has to re-resolve the indices.
    """
    hand = game.players[0].hand
    out = []
    for a in game.legal_actions():
        idx = getattr(a, "hand_index", None)
        if idx is None:
            out.append(repr(a))
            continue
        extra = tuple(getattr(a, f) for f in ("upgrades", "times") if hasattr(a, f))
        out.append(f"{type(a).__name__}(card={card_id(hand[idx])}, {extra})")
    return sorted(out)


def test_equal_keys_offer_the_same_moves():
    """Over real play: any two positions sharing a key must offer the same set
    of legal moves. If that ever fails, the table is unsound."""
    seen: dict = {}
    for seed in range(3):
        g = new_solo_game(seed=seed)
        rng = random.Random(seed)
        while not g.game_over:
            k = key(g)
            sig = move_signature(g)
            if k in seen:
                assert seen[k] == sig, "two positions share a key but differ in moves"
            else:
                seen[k] = sig
            g.apply_action(rng.choice(g.legal_actions()))
    assert len(seen) > 500, "not enough positions visited to mean anything"


def test_transpositions_actually_collide():
    """The point of the whole exercise: two different move orders reaching the
    same place must produce the same key."""
    a, b = new_solo_game(seed=0), new_solo_game(seed=0)
    two_yellow = (Crystal.YELLOW, Crystal.YELLOW)
    # Opening hand is [Create 2, Upgrade 2] on a caravan of 3 yellow. Both
    # orders end on 3Y 2G with an empty hand and both cards played, so they
    # are the same position reached two ways.
    a.apply_action(PlayCrystal(0))                  # 3Y -> 5Y
    a.apply_action(PlayUpgrade(0, two_yellow))      # -> 3Y 2G
    b.apply_action(PlayUpgrade(1, two_yellow))      # 3Y -> 1Y 2G
    b.apply_action(PlayCrystal(0))                  # -> 3Y 2G
    assert a.players[0].caravan == [3, 2, 0, 0] == b.players[0].caravan
    assert key(a) == key(b), "order of two independent moves must not matter"


def test_assert_goal_is_turns_rejects_multiplayer():
    with pytest.raises(ValueError, match="solo"):
        assert_goal_is_turns(Game(["a", "b"], seed=0))
    assert_goal_is_turns(new_solo_game(seed=0))  # does not raise

"""Step 2: a hashable fingerprint of a solo position.

The search reaches the same position by many different move orders — upgrade
then buy, or buy then upgrade, often land in exactly the same place. Without a
way to recognise that, the search re-explores each of them. `key()` is the
fingerprint that makes the seen-state table possible.

What is in the key, and why each part earns its place:

    caravan            what you can pay with
    hand               what you can play
    played             what a Rest would return
    merchant row       what you can buy, and at what price (slot = cost)
    row crystals       crystals sitting on row cards, gained on acquire
    point row          what you can claim
    deck positions     which card refills the row next
    claimed count      how close the game is to ending
    pending discard    whether a sub-decision is owed mid-move

What is deliberately left out, and why it is safe *for this goal only*:

    which golems were claimed   inert once claimed; they affect no future
                                move. Only the count matters, because the
                                game ends at win_target.
    tokens, points, score       the objective is turns, not points. Nothing
                                in the rules lets a token or a point change
                                what you may do next.
    whose turn it is            solo: always seat 0.

That third group is the load-bearing assumption. Every one of them WOULD be
needed for a score-maximising search, and collapsing them is only sound while
the question is "fewest turns to win_target golems". `assert_goal_is_turns`
exists to make that dependency impossible to forget.

Cards are keyed by their `bots.sim` mechanical id rather than by name or
identity, so two cards that do the same thing collapse — they are genuinely
interchangeable, which makes the table hit more often, not less correctly.
"""

from __future__ import annotations

from typing import Optional, Sequence

from bots._engine import Game, MerchantCard, PointCard
from bots.sim import card_id

# A key is a tuple of plain ints and tuples of ints: hashable, comparable,
# and cheap to build. Typed loosely on purpose — the shape is documented by
# `key()` itself and pinned by tests, not by a dataclass nobody constructs.
Key = tuple


def _merchant_ids(row: Sequence[Optional[MerchantCard]]) -> tuple[int, ...]:
    """Row slots by mechanical id; -1 for an empty slot (a drained deck).

    Order matters here and must NOT be sorted: a merchant card's position in
    the row is its price, so slot 0 and slot 4 are different offers.
    """
    return tuple(-1 if c is None else card_id(c) for c in row)


def _point_key(card: Optional[PointCard]) -> tuple[int, ...]:
    """A golem by what it costs, not by what it is worth.

    Two golems with the same cost are interchangeable for a turn-minimising
    search even when their point values differ — which is exactly the
    collapse this module's docstring warns is goal-specific.
    """
    if card is None:
        return (-1,)
    cost = card.cost_counter()
    return tuple(cost.get(c, 0) for c in range(4))


def _hand_key(cards: Sequence[MerchantCard]) -> tuple[int, ...]:
    """Cards you hold, as a sorted multiset.

    Sorted because order never affects legality: `legal_actions` offers every
    card in hand regardless of where it sits. Two hands holding the same
    cards in different orders are the same position, and if the key did not
    sort, the table would miss every one of those matches.
    """
    return tuple(sorted(card_id(c) for c in cards))


def key(game: Game) -> Key:
    """The fingerprint. Two solo positions with equal keys are interchangeable
    for a search that is minimising turns to `win_target` golems.
    """
    p = game.players[0]
    return (
        tuple(p.caravan),
        _hand_key(p.hand),
        _hand_key(p.played),
        _merchant_ids(game.merchant_row),
        tuple(tuple(sorted(rc.items())) for rc in game.row_crystals),
        tuple(_point_key(c) for c in game.point_row),
        # Deck *position*, not contents. Cards are popped from the end and
        # the order is fixed by the seed, so "37 left" identifies the
        # remaining stack exactly — but only on a game nobody has called
        # `shuffle_hidden` on. That is fine for the deterministic search
        # (handover approach 1); a determinized search (approach 3) reshuffles
        # and must key the contents, or keep one table per sampled order.
        len(game.merchant_deck),
        len(game.point_deck),
        len(p.point_cards),
        -1 if game.pending_discard is None else game.pending_discard,
    )


def assert_goal_is_turns(game: Game) -> None:
    """Guard the assumptions in this module's docstring.

    The key throws away tokens, points and golem identity. That is sound only
    for a one-player, fewest-turns search. Call this wherever a Game enters
    the solver, so the day someone points this machinery at a scoring problem
    it fails loudly instead of quietly returning a wrong answer.
    """
    if game.n != 1:
        raise ValueError(
            f"solver keys assume a solo game; got {game.n} players. With "
            "opponents the key would have to include every other seat.")

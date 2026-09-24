"""Step 4: the admissible lower bound `h`.

Skeleton only — the bodies are yours. What this docstring is for is the one
rule the whole file lives or dies by:

    h must NEVER overestimate the turns remaining.

Overestimating by one turn, once, in a position the search would otherwise
have explored, and the answer is silently wrong: the branch gets pruned, the
plan that would have won two turns sooner is never found, and DFBB still
reports the result as proven optimal. Underestimating only makes the search
slower. When in doubt, be generous — a loose bound costs time, a tight-but-
wrong one costs correctness.

The shape, from the handover:

    h = claims left + ceil(value deficit / G_max)

where value is counted in "yellow-equivalents": how many upgrade steps a
crystal embodies, yellow counting as 1. A golem costing 2G + 2M is worth
2*2 + 2*4 = 12. `bots.sim.YE` already holds (1, 2, 3, 4) on this scale, and
`bots.sim.cost_of` gives a golem's cost as four counts.

Capped values
-------------
If every golem still needed asks only for yellow and green, then blue and
magenta are worth no more than green — nothing can spend the difference. So
values are capped at the highest color still wanted, which shrinks G_max and
tightens the bound. Any non-negative valuation stays admissible *as long as
golem costs and G_max use the same one*, so there are four G_max values, one
per cap, and the state picks which applies. The max of several valid bounds
is itself valid.

Two things to be careful about
------------------------------
1. The handover's trade-card gain is (gain - cost) * max repeats, with
   max repeats = 10 / crystals per trade, justified by "the caravan starts a
   turn with at most 10". That was written before the over-limit discard
   became a real choice (step 3). A turn may now legally pass *through* more
   than ten crystals and discard back down afterwards, so check whether that
   repeat count is still a true ceiling. If a single turn can add more value
   than G_max allows, the bound is inadmissible and step 7 will find it.

2. `bots.sim.ttc()` looks like it answers this question and does not. It is
   tuned to be accurate, not to be a lower bound, so it can overestimate.
   Different job — do not borrow it for h.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

from bots._engine import (CARAVAN_LIMIT, MERCHANT_CARDS, STARTING_CARDS,
                          Crystal, CrystalCard, Game, MerchantCard, PointCard,
                          TradeCard, UpgradeCard)
from bots.sim import YE, card_id, cost_of

# A cap is a Crystal: the highest color worth anything in this state.
CAP_NONE = Crystal.MAGENTA

_SCALES: tuple[tuple[int, int, int, int], ...] = (
    (1, 1, 1, 1),   # cap YELLOW     
    (1, 2, 2, 2),   # cap GREEN
    (1, 2, 3, 3),   # cap blue
    (1, 2, 3, 4),   # no cap
)

def crystal_values(cap: Crystal = CAP_NONE) -> tuple[int, int, int, int]:
    """The per-color value scale, capped at `cap`.

    Uncapped: (1, 2, 3, 4). Capped at green: (1, 2, 2, 2) — blue and magenta
    are worth no more than the best thing anyone still wants.
    """
    return _SCALES[cap]


def value(counts: Sequence[int], cap: Crystal = CAP_NONE) -> int:
    """Yellow-equivalent value of a caravan (or any four counts)."""
    values = crystal_values(cap)
    yellow_sum = 0
    for i in range(4):
        yellow_sum = yellow_sum + counts[i] * values[i]
    return yellow_sum


def golem_value(card: PointCard, cap: Crystal = CAP_NONE) -> int:
    """What a golem costs, in yellow-equivalents."""
    values = crystal_values(cap)
    sum_golem = 0
    #go through point card, count 
    for i in range(4):
        sum_golem = sum_golem + cost_of(card)[i] * values[i]
    return sum_golem


#helper function for card.gain, card.lost --> would create a tuple of form (string, #) i.e. 2G -> 4M would be (Green, 2) --> (MAGENTA, 4)
#converting it to just a numeric tuple
def _as_counts(pairs):
    out = [0, 0, 0, 0]
    for color, n in pairs:
        out[color] += n
    return out

def card_gain(card: MerchantCard, cap: Crystal = CAP_NONE) -> int:
    """The most value one turn spent playing `card` can add.

    Crystal card: the value of what it gives.
    Upgrade card: one per step.
    Trade card:   (gain - cost) * max repeats; value-losing trades count 0.
                  See caveat 1 in the module docstring about max repeats.
    """
    if isinstance(card, CrystalCard):
        return value(_as_counts(card.gain), cap)

    if isinstance(card, UpgradeCard):
        values = crystal_values(cap)
        best_step = max(values[c + 1] - values[c] for c in range(3))
        return card.steps * best_step

    if isinstance(card, TradeCard):
        cost_card, gain_card = _as_counts(card.cost), _as_counts(card.gain)
        net = value(gain_card, cap) - value(cost_card, cap)
        if net <= 0:            # a value-losing trade adds nothing
            return 0
        return net * (CARAVAN_LIMIT // sum(cost_card))

    raise TypeError(f"unknown merchant card {card!r}")
    




def g_max(cap: Crystal = CAP_NONE, cards: Optional[Iterable[MerchantCard]] = None) -> int:
    """The most value ANY single turn can add, at this cap.

    `cards=None` means the whole compendium: simple, safe, loose. Passing
    owned + row + known deck is tighter and still admissible on a fixed seed,
    since no other card can ever be played.

    Acquire contributes the value of the crystals sitting on the card taken;
    Rest and Claim contribute nothing.
    """
    # h() calls this on every node and the compendium never changes, so the
    # four default values are computed once. An explicit `cards` is not
    # cached: it may be any iterable, including a one-shot generator.
    if cards is None:
        if cap in _G_MAX_CACHE:
            return _G_MAX_CACHE[cap]
        cards = list(MERCHANT_CARDS) + list(STARTING_CARDS)
        _G_MAX_CACHE[cap] = result = _g_max_over(cards, cap)
        return result

    return _g_max_over(list(cards), cap)


_G_MAX_CACHE: dict[Crystal, int] = {}


def _g_max_over(cards: list[MerchantCard], cap: Crystal) -> int:
    # Acquire is the problem. Its gain is the crystals sitting on the card
    # taken, and nothing caps how many pile up — one lands on a slot every
    # time you buy from further right, and random solo play was measured at 22
    # crystals (value 38) on a single slot. So there is no useful static bound
    # on the acquire term, and a G_max built from the cards alone would be too
    # small: too-small G_max makes h too big, which loses optimal lines.
    #
    # The bound that does hold comes from the caravan, not the cards. Every
    # action ends with the caravan at CARAVAN_LIMIT crystals or fewer, so no
    # position is worth more than CARAVAN_LIMIT * (best crystal). A turn's
    # gain is the difference between two positions and value is never
    # negative, so no turn can add more than that — whatever it does, and
    # whatever piled up on the row. This is also what kills the fictional
    # trade gains: a card that "nets +30" by making 50 crystals cannot keep
    # them.
    ceiling = CARAVAN_LIMIT * max(crystal_values(cap))

    # Kept because it is the honest per-card figure and a future per-state
    # g_max will want it, but it cannot lower the answer on its own: the
    # acquire term is only bounded by the ceiling, so the max is the ceiling.
    best_card = max(card_gain(c, cap) for c in cards)
    assert best_card >= 0
    return ceiling



def cap_for(game: Game) -> Crystal: #highest crystal in remaining deck
    remaining = [c for c in game.point_row if c is not None] + game.point_deck #gives remaining deck
    highest = Crystal.YELLOW
    for card in remaining:
        cost = cost_of(card)
        for c in range(4):
            if cost[c] > 0 and c > highest:
                highest = Crystal(c)
    return highest

                    


def h(game: Game) -> int:
    """A lower bound on the turns remaining. Never an overestimate.

        1. V = value of the cheapest golems still needed - caravan value
        2. building turns >= ceil(V / G_max)
        3. h = building turns + claims left

    Worked example from the handover, to check an implementation against:
    with 2 golems claimed, the cheapest 4 remaining worth 40, a caravan worth
    10 and G_max 10 -- V = 30, building turns = 3, claims left = 4, h = 7.

    Later tightening, once the basic version is right: a Rest gains no value,
    so if every card is in the played pile the next turn *must* be a Rest,
    and that turn can be added to h for free.
    """
    # No guard on the row crystals any more: g_max no longer assumes anything
    # about them. It bounds a turn by what a caravan can hold, which holds
    # however much has piled up on the board.
    player = game.players[0]
    claims_left = game.win_target - len(player.point_cards)
    if claims_left <= 0:
        return 0

    cap = cap_for(game)

    # The cheapest golems still gettable, priced on the capped scale. Read off
    # the whole remaining pool, not just the row: pricing only the five
    # visible ones could overstate what is owed, and an overstated h prunes
    # winning lines. Taking the cheapest is the same relaxation — you may be
    # forced into dearer golems, never cheaper ones.
    remaining = [c for c in game.point_row if c is not None] + game.point_deck
    cheapest = sorted(golem_value(c, cap) for c in remaining)[:claims_left]

    # Overvaluing the caravan (some crystals are the wrong color to spend)
    # only shrinks the deficit, which shrinks h. Safe direction.
    deficit = max(0, sum(cheapest) - value(player.caravan, cap))

    per_turn = g_max(cap)
    building_turns = (deficit + per_turn - 1) // per_turn   # ceil, in ints
    return claims_left + building_turns

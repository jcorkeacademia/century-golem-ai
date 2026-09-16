"""Solitaire simulator: how far is a player from affording a given golem?

Everything here answers one question — *if this player kept playing alone,
ignoring opponents and the row, how many turns until they could pay this
cost?* That number (TTC, turns-to-claim) is what nearly every feature in
`features.py` is built on: a 20-point golem you can buy next turn is worth
far more than a 20-point golem eight turns away.

Nothing here mutates a real `Game`. The simulator works on plain tuples of
ints, which is what makes it cheap enough to call millions of times.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Iterable, Optional, Sequence

from bots._engine import (
    CARAVAN_LIMIT,
    Crystal,
    CrystalCard,
    MerchantCard,
    Player,
    PointCard,
    TradeCard,
    UpgradeCard,
)

# --------------------------------------------------------------------------
# Yellow-equivalent value
# --------------------------------------------------------------------------
# What one crystal of each colour is nominally worth, in "yellows". A green is
# a yellow plus one upgrade step, a blue is two steps, and so on. Tuning may
# later replace these with learned values (BOT_IMPLEMENTATION_PROMPT §2.1) —
# that is why it is one constant and not a scatter of literals.
YE: tuple[int, int, int, int] = (1, 2, 3, 4)

Caravan = tuple[int, int, int, int]


def ye_of(caravan: Sequence[int]) -> int:
    """Total yellow-equivalent value held."""
    return (caravan[0] * YE[0] + caravan[1] * YE[1]
            + caravan[2] * YE[2] + caravan[3] * YE[3])


# --------------------------------------------------------------------------
# Card descriptors
# --------------------------------------------------------------------------
# The simulator never touches engine card objects in its inner loop. Each card
# is reduced once to a compact descriptor of plain ints, and identified by a
# small integer id.
#
# Ids are assigned by *mechanics*, deliberately ignoring the card's name. Two
# reasons. First, the engine deals starting cards it builds itself
# (`CrystalCard(((Y,2),), "Create 2")`) which are not the same objects — nor
# even equal to — `century_cards.STARTING_CARDS` ("Create 2 (+2Y)"), because
# frozen-dataclass equality includes the name. Keying on identity or equality
# would treat those as unknown cards. Second, two mechanically identical cards
# are genuinely interchangeable for this simulation, so they *should* share an
# id — that makes the cache hit more often, not less correctly.

# kind codes
CRYSTAL, UPGRADE, TRADE = 0, 1, 2

# id -> descriptor
#   crystal: (CRYSTAL, gain: Caravan)
#   upgrade: (UPGRADE, steps: int)
#   trade:   (TRADE, cost: Caravan, gain: Caravan)
_DESCRIPTORS: list[tuple] = []
_ID_BY_SIG: dict[tuple, int] = {}


def _counts(pairs: Iterable[tuple[Crystal, int]]) -> Caravan:
    c = [0, 0, 0, 0]
    for color, n in pairs:
        c[color] += n
    return (c[0], c[1], c[2], c[3])


def card_id(card: MerchantCard) -> int:
    """Stable small-int id for a card, by mechanics."""
    if isinstance(card, CrystalCard):
        sig: tuple = (CRYSTAL, _counts(card.gain))
    elif isinstance(card, UpgradeCard):
        sig = (UPGRADE, card.steps)
    elif isinstance(card, TradeCard):
        sig = (TRADE, _counts(card.cost), _counts(card.gain))
    else:
        raise TypeError(f"not a merchant card: {card!r}")
    got = _ID_BY_SIG.get(sig)
    if got is None:
        got = len(_DESCRIPTORS)
        _ID_BY_SIG[sig] = got
        _DESCRIPTORS.append(sig)
    return got


def card_ids(cards: Iterable[MerchantCard]) -> tuple[int, ...]:
    """Sorted id tuple — sorted so hand order never splits the cache."""
    return tuple(sorted(card_id(c) for c in cards))


def cost_of(card: PointCard) -> Caravan:
    return _counts(card.cost)


# --------------------------------------------------------------------------
# Nominal output (§2.2)
# --------------------------------------------------------------------------

def nominal_output(card: MerchantCard) -> float:
    """Yellow-equivalent a card produces in one play.

    Crystal: the YE of its gain. Upgrade: one YE per step. Trade: the YE it
    gains minus the YE it spends, for a single repetition — which can be
    negative, and legitimately is for cards that trade down the chain.
    """
    kind = _DESCRIPTORS[card_id(card)]
    return _nominal_from_descriptor(kind)


def _nominal_from_descriptor(desc: tuple) -> float:
    if desc[0] == CRYSTAL:
        return float(ye_of(desc[1]))
    if desc[0] == UPGRADE:
        return float(desc[1])
    return float(ye_of(desc[2]) - ye_of(desc[1]))


def throughput(player: Player) -> float:
    """Average YE per turn across every card owned (§2.4).

    The +1 is the Rest turn: a cycle that plays N cards costs N+1 turns,
    because you have to spend one getting them back.
    """
    owned = list(player.hand) + list(player.played)
    if not owned:
        return 0.0
    return sum(nominal_output(c) for c in owned) / (len(owned) + 1)


# --------------------------------------------------------------------------
# Shortfall (§2.3)
# --------------------------------------------------------------------------

def shortfall(caravan: Sequence[int], cost: Sequence[int]) -> int:
    """How far this caravan is from paying `cost`, in upgrade steps.

    Golem costs are paid in exact colours, and crystals only move *up* the
    chain — so a crystal of level `l` can cover a cost crystal of level `c`
    only when `l <= c`, at a price of `c - l` upgrade steps. A magenta cannot
    pay a green cost, however expensive the magenta is.

    Costs are matched most-expensive-first against the highest crystal that
    fits. Anything left unmatched is charged its full value (`c + 1`, i.e. its
    YE), standing in for "acquire it from scratch".

    Returns 0 when the cost is already payable.

    Hot path — this is the most-called function in the simulator, so crystals
    are matched in batches per level rather than one at a time.
    """
    avail = [caravan[0], caravan[1], caravan[2], caravan[3]]
    total = 0
    for c in (3, 2, 1, 0):
        need = cost[c]
        if not need:
            continue
        level = c
        while need and level >= 0:
            have = avail[level]
            if have:
                take = have if have < need else need
                avail[level] = have - take
                total += (c - level) * take
                need -= take
            level -= 1
        if need:
            total += (c + 1) * need
    return total


def can_pay(caravan: Sequence[int], cost: Sequence[int]) -> bool:
    return (caravan[0] >= cost[0] and caravan[1] >= cost[1]
            and caravan[2] >= cost[2] and caravan[3] >= cost[3])


# --------------------------------------------------------------------------
# The solitaire search
# --------------------------------------------------------------------------

def enforce_limit(caravan: Caravan) -> Caravan:
    """The engine's caravan cap, cheapest-first, as a pure function.

    Mirrors `Game._enforce_caravan_limit`. If that rule ever becomes a player
    choice (HANDOVER §8.1) this has to change with it.
    """
    total = caravan[0] + caravan[1] + caravan[2] + caravan[3]
    if total <= CARAVAN_LIMIT:
        return caravan
    car = list(caravan)
    over = total - CARAVAN_LIMIT
    for i in range(4):
        if over <= 0:
            break
        drop = min(car[i], over)
        car[i] -= drop
        over -= drop
    return (car[0], car[1], car[2], car[3])


def _upgrade_results(caravan: Caravan, steps: int) -> list[Caravan]:
    """Every distinct caravan reachable with up to `steps` upgrades.

    Deduplicated by result, and each result expanded only once — reaching the
    same caravan in fewer steps dominates, since everything reachable from the
    longer path is reachable from the shorter one too.
    """
    seen: dict[Caravan, int] = {caravan: 0}
    frontier = [caravan]
    for depth in range(1, steps + 1):
        nxt = []
        for car in frontier:
            for c in range(3):
                if car[c]:
                    new = list(car)
                    new[c] -= 1
                    new[c + 1] += 1
                    t = (new[0], new[1], new[2], new[3])
                    if t not in seen:
                        seen[t] = depth
                        nxt.append(t)
        if not nxt:
            break
        frontier = nxt
    return list(seen)


def _trade_results(caravan: Caravan, cost: Caravan, gain: Caravan) -> list[Caravan]:
    """Every affordable repeat count of one trade, as resulting caravans.

    Repeat counts are never deduplicated: t repetitions move the caravan by
    t*(gain - cost), so two counts can only collide on a no-op trade, and no
    card in the compendium is one.
    """
    max_times = -1
    for i in range(4):
        ci = cost[i]
        if ci:
            v = caravan[i] // ci
            if max_times < 0 or v < max_times:
                max_times = v
    if max_times <= 0:
        return []
    d0 = gain[0] - cost[0]
    d1 = gain[1] - cost[1]
    d2 = gain[2] - cost[2]
    d3 = gain[3] - cost[3]
    c0, c1, c2, c3 = caravan
    return [(c0 + d0 * t, c1 + d1 * t, c2 + d2 * t, c3 + d3 * t)
            for t in range(1, max_times + 1)]


State = tuple[Caravan, tuple[int, ...], tuple[int, ...]]

_TTC_CACHE: dict[tuple, float] = {}


def clear_cache() -> None:
    _TTC_CACHE.clear()


def cache_size() -> int:
    return len(_TTC_CACHE)


def _successors(state: State, target: Caravan) -> list[State]:
    """Every state reachable in one turn.

    Pruning: an upgrade or trade result is dropped unless it reduces the
    shortfall to the target or raises total YE. Playing a card that does
    neither cannot help reach *this* cost any sooner, and keeping it would
    multiply the search width for nothing.
    """
    caravan, hand, played = state
    out: list[State] = []
    base_short = shortfall(caravan, target)
    base_ye = ye_of(caravan)
    seen: set[State] = set()

    for i, cid in enumerate(hand):
        rest_of_hand = hand[:i] + hand[i + 1:]
        new_played = tuple(sorted(played + (cid,)))
        desc = _DESCRIPTORS[cid]

        if desc[0] == CRYSTAL:
            gain = desc[1]
            car = enforce_limit((caravan[0] + gain[0], caravan[1] + gain[1],
                                 caravan[2] + gain[2], caravan[3] + gain[3]))
            cand = [car]
        elif desc[0] == UPGRADE:
            cand = [enforce_limit(c) for c in _upgrade_results(caravan, desc[1])
                    if c != caravan]
        else:
            cand = [enforce_limit(c) for c in _trade_results(caravan, desc[1], desc[2])]

        for car in cand:
            if desc[0] != CRYSTAL:
                if shortfall(car, target) >= base_short and ye_of(car) <= base_ye:
                    continue
            nxt = (car, rest_of_hand, new_played)
            if nxt not in seen:
                seen.add(nxt)
                out.append(nxt)

    if played:
        out.append((caravan, tuple(sorted(hand + played)), ()))
    return out


# Widest frontier the search will carry from one simulated turn to the next.
#
# Without this the search is exhaustive, and its cost explodes with hand size
# whenever the target is *not* reachable — which is roughly half of all calls
# (see API_NOTES §8.4). Measured at depth 3 against an unreachable 5M golem:
#
#     hand size    2      4      6      8     10     12     15
#     ms        0.020  0.036  0.209  0.242  0.621  1.326  10.295
#
# A bot that buys cards ends up holding 10-15, so this is the common case, not
# the tail. The beam keeps only the most promising states per turn — lowest
# shortfall first, then most yellow-equivalent — which bounds the work at
# roughly beam x depth x branching regardless of how big the hand gets.
#
# It makes TTC a heuristic rather than an exact breadth-first answer: a plan
# that needs an unpromising intermediate step can be missed, and TTC can come
# back higher than the truth. That is an acceptable trade for a feature input
# that is already an estimate half the time, and it is what makes millions of
# evaluations affordable in Step 6.
BEAM_WIDTH = 32


def ttc_state(caravan: Caravan, hand: tuple[int, ...], played: tuple[int, ...],
              target: Caravan, depth: int = 3,
              throughput_hint: float = 0.0, beam: int = BEAM_WIDTH) -> float:
    """Turns until `target` is payable from this state. See `ttc`."""
    if can_pay(caravan, target):
        return 0.0

    key = (caravan, hand, played, target, depth, round(throughput_hint, 3), beam)
    hit = _TTC_CACHE.get(key)
    if hit is not None:
        return hit

    best_short = shortfall(caravan, target)
    frontier: list[State] = [(caravan, hand, played)]
    visited: set[State] = {frontier[0]}
    result: Optional[float] = None

    for turn in range(1, depth + 1):
        scored: list[tuple[int, int, State]] = []
        for st in frontier:
            for succ in _successors(st, target):
                if succ in visited:
                    continue
                visited.add(succ)
                if can_pay(succ[0], target):
                    result = float(turn)
                    break
                s = shortfall(succ[0], target)
                if s < best_short:
                    best_short = s
                scored.append((s, -ye_of(succ[0]), succ))
            if result is not None:
                break
        if result is not None:
            break
        if not scored:
            break
        if len(scored) > beam:
            scored.sort(key=lambda t: (t[0], t[1]))
            del scored[beam:]
        frontier = [t[2] for t in scored]

    if result is None:
        # Nothing within the horizon. Extrapolate: the remaining shortfall at
        # the best state reached, paid off at the player's own production rate.
        rate = throughput_hint if throughput_hint > 0.5 else 0.5
        result = float(depth) + math.ceil(best_short / rate)

    _TTC_CACHE[key] = result
    return result


def ttc(player: Player, golem: PointCard, depth: int = 3) -> float:
    """Turns until `player` could pay for `golem`, playing solitaire.

    Counts only what this player already owns — their caravan, hand, played
    pile and the Rest that recycles it. Opponents, acquisitions and deck draws
    are all ignored, which makes this an optimistic-but-consistent estimate
    rather than a prediction.

    0 means payable right now. A value above `depth` is an extrapolation, not
    a searched result: nothing was found within the horizon, so the remaining
    shortfall is divided by the player's throughput.
    """
    return ttc_state(
        (player.caravan[0], player.caravan[1], player.caravan[2], player.caravan[3]),
        card_ids(player.hand),
        card_ids(player.played),
        cost_of(golem),
        depth,
        throughput(player),
    )


def ttc_row(player: Player, point_row: Sequence[Optional[PointCard]],
            depth: int = 3) -> list[Optional[float]]:
    """TTC for every occupied slot of the point row; None for empty slots."""
    car = (player.caravan[0], player.caravan[1], player.caravan[2], player.caravan[3])
    hand = card_ids(player.hand)
    played = card_ids(player.played)
    tp = throughput(player)
    return [None if pc is None else ttc_state(car, hand, played, cost_of(pc), depth, tp)
            for pc in point_row]

"""A crystal-flow lower bound, for the gap report (root positions only).

h credits every strong play with its best-case gain, but a trade only hits
that when the caravan already holds the right INPUT colour, and those inputs
have to be made first. This bound makes the inputs pay for themselves.

It is an operator-counting (state-equation) relaxation, solved as a small
integer program: count how often each card is played, how many crystals of
each colour those plays consume and produce, and require every colour to
balance against what the golems cost — ignoring the ORDER of moves. Every
real plan gives a feasible solution with the same number of turns, so the
optimum never exceeds the true remaining turns.

Variables, per card:
    y   plays (integer)
    z   bought (binary, cards not owned)             -> an Acquire turn each
    x   trade executions; at most 10 // (crystals per trade) per play
    k   output crystals KEPT, by colour: at most 10 per play in total, since
        the caravan ends every turn at 10 or fewer (discards only lose)
    u   upgrade steps, by colour moved from: at most `steps` per play
plus R, the Rests: a card played y times needs y Rests if it starts in the
played pile, y - 1 if it starts in hand or is bought (bought cards go to
hand), and Rests are shared across cards; and one binary per reachable golem,
choosing k golems that can fill claims 1..k (Hall's condition, as in h).

Balance, per colour: caravan + crystals on the row + made - used >= golems.
Row crystals count as yours (you could acquire them back) and payments and
discards are not modelled — all in the player's favour, so still a lower
bound.

Minimise plays + Rests + purchases; the bound is that plus the claims.
Too slow for every search node (tens of milliseconds); it is for measuring
the gap at the opening.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from bots._engine import (MERCHANT_CARDS, CrystalCard, Game, TradeCard,
                          UpgradeCard)
from bots.sim import cost_of
from solver.bound import _as_counts, reachable_golems

LIMIT = 10          # CARAVAN_LIMIT
MAX_PLAYS = 60      # per card; far above any real game


class _Vars:
    """Allocates column indices and remembers their integrality/bounds."""

    def __init__(self):
        self.n = 0
        self.integral: list[int] = []
        self.upper: list[float] = []

    def new(self, upper: float = np.inf, integer: bool = True) -> int:
        i = self.n
        self.n += 1
        self.integral.append(1 if integer else 0)
        self.upper.append(upper)
        return i


def flow_bound(game: Game) -> int:
    """Lower bound on the turns remaining, by crystal flow. Solo only."""
    player = game.players[0]
    claims_left = game.win_target - len(player.point_cards)
    if claims_left <= 0:
        return 0

    v = _Vars()
    rows: list[tuple[dict, float, float]] = []      # (coeffs, lo, hi)
    cost = {}                                       # objective coefficients

    rests = v.new(upper=MAX_PLAYS)
    cost[rests] = 1

    # colour balance terms, accumulated per colour: {var: coefficient}
    balance = [dict() for _ in range(4)]

    owned = [(c, True) for c in player.hand] + [(c, False) for c in player.played]
    owned_ids = {id(c) for c, _ in owned}
    cards = owned + [(c, None) for c in MERCHANT_CARDS if id(c) not in owned_ids]

    for card, in_hand in cards:
        plays = v.new(upper=MAX_PLAYS)
        cost[plays] = 1
        if in_hand is None:                         # must be bought first
            bought = v.new(upper=1)
            cost[bought] = 1
            rows.append(({plays: 1, bought: -MAX_PLAYS}, -np.inf, 0))
            # bought cards go to hand: y - 1 Rests (y - bought, for y = 0)
            rows.append(({rests: 1, plays: -1, bought: 1}, 0, np.inf))
        else:
            rows.append(({rests: 1, plays: -1}, -1 if in_hand else 0, np.inf))

        if isinstance(card, CrystalCard):
            for colour, n in enumerate(_as_counts(card.gain)):
                if n:
                    balance[colour][plays] = balance[colour].get(plays, 0) + n
        elif isinstance(card, UpgradeCard):
            steps = [v.new() for _ in range(3)]     # upgrades out of Y, G, B
            rows.append(({**{s: 1 for s in steps}, plays: -card.steps}, -np.inf, 0))
            for colour, s in enumerate(steps):
                balance[colour][s] = balance[colour].get(s, 0) - 1
                balance[colour + 1][s] = balance[colour + 1].get(s, 0) + 1
        elif isinstance(card, TradeCard):
            c_in, c_out = _as_counts(card.cost), _as_counts(card.gain)
            execs = v.new()
            rows.append(({execs: 1, plays: -(LIMIT // sum(c_in))}, -np.inf, 0))
            kept = []
            for colour in range(4):
                if c_in[colour]:
                    balance[colour][execs] = balance[colour].get(execs, 0) - c_in[colour]
                if c_out[colour]:
                    k = v.new()
                    kept.append(k)
                    rows.append(({k: 1, execs: -c_out[colour]}, -np.inf, 0))
                    balance[colour][k] = balance[colour].get(k, 0) + 1
            if kept:
                rows.append(({**{k: 1 for k in kept}, plays: -LIMIT}, -np.inf, 0))

    # golems: choose claims_left of the reachable ones, schedulable in time
    windows = reachable_golems(game, claims_left)
    picks = [v.new(upper=1) for _ in windows]
    rows.append(({p: 1 for p in picks}, claims_left, claims_left))
    for s in range(2, claims_left + 1):
        late = {p: 1 for p, (_, w) in zip(picks, windows) if w >= s}
        if late:
            rows.append((late, -np.inf, claims_left - s + 1))
    for p, (golem, _) in zip(picks, windows):
        for colour, n in enumerate(cost_of(golem)):
            if n:
                balance[colour][p] = balance[colour].get(p, 0) - n

    # what you hold: caravan plus every crystal sitting on the row
    held = list(player.caravan)
    for rc in game.row_crystals:
        for colour, n in rc.items():
            held[colour] += n
    for colour in range(4):
        rows.append((balance[colour], -held[colour], np.inf))

    A = np.zeros((len(rows), v.n))
    lo = np.empty(len(rows))
    hi = np.empty(len(rows))
    for r, (coeffs, a, b) in enumerate(rows):
        for i, c in coeffs.items():
            A[r, i] += c
        lo[r], hi[r] = a, b
    c = np.zeros(v.n)
    for i, w in cost.items():
        c[i] = w
    res = milp(c, constraints=LinearConstraint(A, lo, hi),
               integrality=np.array(v.integral),
               bounds=Bounds(np.zeros(v.n), np.array(v.upper)))
    if not res.success:
        raise RuntimeError(f"flow bound did not solve: {res.message}")
    # the solver works in floats; a lower bound must round UP only when the
    # value is genuinely above an integer, so allow a hair of tolerance
    building = int(np.ceil(res.fun - 1e-6))
    return claims_left + building

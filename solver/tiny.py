"""Step 7: tiny boards, and a brute-force search to check dfbb against.

On the real game neither search can play a whole game from the first move,
so the only positions where dfbb had been checked against a true optimum
were a few turns from the end. Tiny boards fix that: same engine, same rules,
a small deck and a low goal, so both searches run from the opening move.

Nothing here changes the engine. Game already takes custom decks; the goal
and the starting caravan are set on the solo game object after it is built.

Why tiny boards have to be REALLY tiny
--------------------------------------
Measured on the real game, a state offers ~21 moves, 73% of them Acquire —
each way to pay for a card is its own move. The cheap_payments rule (pay only
in yellow and green) cuts that to ~12. Still, the tree grows ~12x per turn,
so a board whose optimum is 5 turns already means hundreds of thousands of
states for the brute force. Hence two tiers:

    FAST       one golem, near-empty start caravan. Seconds per board; runs in
               the normal test suite.
    THOROUGH   two golems, a richer start. Slower; run by hand
               (`python -m solver.tiny`) and after every step-8 speed-up.
               Boards that turn out too big are skipped, not waited on.

The brute force
---------------
Deliberately naive and independent of everything dfbb relies on: no h, no
pruning, no solver.state.key. Breadth-first by turns, so the first win it
reaches is the fewest turns. It deduplicates on `_full_key`, which records
everything about a position, nothing collapsed — over-fine only makes it
slower, whereas over-coarse could merge different positions and hide the very
bug it exists to find.

How dfbb is checked
-------------------
dfbb starts with b = (brute-force optimum + 1) and an empty plan. To return
anything it must find a plan of exactly the optimal length with its pruning
on. If h ever overestimates on the optimal line, dfbb prunes that line,
cannot improve on b, and the board fails. That is the failure step 7 exists
to catch. (Starting from a loose b instead only changes how long dfbb takes,
which is step 8's problem, not a correctness question.)

Both searches use the SAME move list, so a disagreement always means dfbb's
pruning, never the move rule. Whether the move rule itself loses the
optimum is a separate question: `rule_check` answers it by running the brute
force with and without it.
"""

from __future__ import annotations

import random
import sys
import time
from collections import Counter
from dataclasses import dataclass
from typing import Optional

from bots._engine import Discard, Game, MERCHANT_CARDS, POINT_CARDS
from solver.bound import golem_value
from solver.search import (Moves, OutOfBudget, Stats, all_moves,
                           cheap_payments, dfbb)
from solver.solo import SOLO_SEAT, turns_in

CHEAPEST_GOLEMS = sorted(POINT_CARDS, key=golem_value)


@dataclass(frozen=True)
class Board:
    """A tiny problem instance, reproducible from its fields."""
    seed: int
    merchants: tuple
    golems: tuple
    target: int
    start: tuple            # starting caravan, (y, g, b, m)

    def game(self) -> Game:
        g = Game([SOLO_SEAT], seed=self.seed, discard_choice=True,
                 merchant_deck=list(self.merchants), point_deck=list(self.golems))
        g.win_target = self.target
        g.players[0].caravan = list(self.start)
        return g


def fast_board(seed: int) -> Board:
    """One golem from a near-empty caravan: the player still has to build."""
    rng = random.Random(seed)
    return Board(seed,
                 tuple(rng.sample(MERCHANT_CARDS, 6)),
                 tuple(rng.sample(CHEAPEST_GOLEMS[:10], 5)),
                 target=1,
                 start=(rng.randint(0, 2), 0, 0, 0))


def thorough_board(seed: int) -> Board:
    """Two golems from a richer start, so claims_left > 1 is exercised."""
    rng = random.Random(seed)
    return Board(seed,
                 tuple(rng.sample(MERCHANT_CARDS, 6)),
                 tuple(rng.sample(CHEAPEST_GOLEMS[:8], 5)),
                 target=2,
                 start=(4, 2, 0, 0))


# ---------------------------------------------------------------------------
# The brute force
# ---------------------------------------------------------------------------

def _full_key(game: Game) -> tuple:
    """Everything about a solo position, with nothing collapsed."""
    p = game.players[0]
    return (
        tuple(p.caravan),
        tuple(c.name for c in p.hand),
        tuple(c.name for c in p.played),
        tuple(c.name for c in p.point_cards),
        tuple(t.name for t in p.tokens),
        tuple(None if c is None else c.name for c in game.merchant_row),
        tuple(tuple(sorted((int(k), v) for k, v in rc.items())) for rc in game.row_crystals),
        tuple(None if c is None else c.name for c in game.point_row),
        tuple(tuple(t.name for t in pile) for pile in game.point_tokens),
        len(game.merchant_deck),
        len(game.point_deck),
        game.pending_discard,
        game.game_over,
    )


class TooBig(Exception):
    """The brute force hit its state limit."""


def brute_force(game: Game, max_turns: int = 12, max_states: int = 300_000,
                moves: Moves = all_moves) -> Optional[int]:
    """Fewest turns to win, by breadth-first search. None if not within
    `max_turns`; raises TooBig past `max_states`.

    Layer t holds every position first reachable in exactly t turns. A
    Discard costs no turn, so its result joins the layer it came from; every
    other move feeds the next layer.
    """
    layer = [game]
    seen = {_full_key(game)}
    for turns in range(max_turns + 1):
        nxt = []
        i = 0
        while i < len(layer):
            state = layer[i]
            i += 1
            if state.game_over:
                return turns
            for action in moves(state):
                child = state.clone()
                child.apply_action(action)
                k = _full_key(child)
                if k in seen:
                    continue
                seen.add(k)
                if len(seen) > max_states:
                    raise TooBig
                (layer if isinstance(action, Discard) else nxt).append(child)
        if not nxt:
            return None
        layer = nxt
    return None


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------

@dataclass
class Outcome:
    board: Board
    brute: Optional[int]         # None: too big, or no win within max_turns
    dfbb: Optional[int]          # None: not run, or hit its budget
    nodes: int = 0
    seconds: float = 0.0

    @property
    def status(self) -> str:
        if self.brute is None:
            return "skipped"
        if self.dfbb is None:
            return "dfbb-budget"
        return "agree" if self.dfbb == self.brute else "DISAGREE"


def replays(board: Board, plan: tuple, turns: int) -> bool:
    game = board.game()
    for action in plan:
        if game.game_over:
            return False
        game.apply_action(action)
    return game.game_over and turns_in(plan) == turns


def check(board: Board, moves: Moves = cheap_payments,
          node_budget: int = 200_000, max_states: int = 300_000) -> Outcome:
    """Brute force first, then dfbb with b = optimum + 1."""
    try:
        truth = brute_force(board.game(), max_states=max_states, moves=moves)
    except TooBig:
        truth = None
    if truth is None:
        return Outcome(board, None, None)

    best = {"turns": truth + 1, "actions": ()}
    stats = Stats()
    try:
        dfbb(board.game(), 0, [], best, stats, node_budget, None, moves)
    except OutOfBudget:
        return Outcome(board, truth, None, stats.nodes, stats.elapsed())
    if best["actions"] and not replays(board, best["actions"], best["turns"]):
        raise AssertionError(f"board {board.seed}: dfbb's plan does not replay")
    return Outcome(board, truth, best["turns"], stats.nodes, stats.elapsed())


def rule_check(board: Board, max_states: int = 300_000) -> Optional[tuple[int, int]]:
    """Does the move rule lose the optimum here? Returns (all moves, rule)
    optima, or None if either brute force is too big. Unequal means the rule
    cost turns on this board."""
    try:
        full = brute_force(board.game(), max_states=max_states, moves=all_moves)
        cut = brute_force(board.game(), max_states=max_states, moves=cheap_payments)
    except TooBig:
        return None
    if full is None or cut is None:
        return None
    return full, cut


def run(make_board, n_boards: int, first_seed: int = 0,
        verbose: bool = True) -> list[Outcome]:
    outcomes = []
    for seed in range(first_seed, first_seed + n_boards):
        o = check(make_board(seed))
        outcomes.append(o)
        if verbose and o.status != "agree":
            print(f"  board {seed}: {o.status}  brute={o.brute} dfbb={o.dfbb}", flush=True)
    return outcomes


def summarise(outcomes: list[Outcome]) -> str:
    tally = Counter(o.status for o in outcomes)
    ran = [o for o in outcomes if o.dfbb is not None]
    line = (f"{len(outcomes)} boards: " + ", ".join(
        f"{tally[s]} {s}" for s in ("agree", "DISAGREE", "dfbb-budget", "skipped")))
    if ran:
        nodes = sum(o.nodes for o in ran)
        secs = sum(o.seconds for o in ran)
        line += (f"\n  dfbb: {nodes:,} nodes in {secs:.1f}s "
                 f"({nodes / len(ran):,.0f} per board)")
    return line


if __name__ == "__main__":  # pragma: no cover - manual run
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    for label, make in (("fast", fast_board), ("thorough", thorough_board)):
        t = time.time()
        print(f"[{label}]")
        print(summarise(run(make, n)))
        print(f"  wall {time.time() - t:.0f}s\n")

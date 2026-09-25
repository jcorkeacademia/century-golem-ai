"""Tightening the upper bound: shorter complete plans.

DFBB's cost goes as branching^(b - h), and b from the bots is ~41 while h at
the root is ~11. Proving a full-game optimum is out of reach (see
HANDOFF_search_performance.md), so the target is a provable GAP per seed:

    lower   the larger of h and the crystal-flow bound at the opening
            (both admissible, both validated; see solver.flow)
    upper   the shortest plan any method finds, replayed to a real win

Two methods here push the upper end down. Neither proves anything about the
whole game; every plan they return is a real, verified win, so each is a
valid upper bound.

plan repair
    Walk backwards along a plan. At each position, run dfbb with b = the
    turns the plan still spends from there, on a node budget. If it finds a
    shorter finish, splice it in. Near the end, where dfbb can prove optima
    (~8 turns out), this replaces the tail with a PROVEN-optimal finish for
    that position; further back it is an anytime improvement. The prefix
    never changes, so every earlier position stays valid as the walk goes
    back.

beam search
    Breadth-first by turns, keeping only the `width` most promising positions
    in each layer, ranked by the tuned bot's own position evaluation. A
    Discard costs no turn, so its results join the layer they came from; all
    candidates in a layer have spent the same turns, so the first win found
    is the shortest this beam can see. On a fixed seed the deck order is
    known, so children are real positions — no sampling of hidden draws.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from bots._engine import Game
from bots.features import Scales, Weights, evaluate
from solver.bound import h
from solver.flow import flow_bound
from solver.fastclone import fast_clone
from solver.greedy import Plan, _solo_scoring, upper_bound, verify
from solver.search import (Moves, OutOfBudget, Stats, cheap_payments,
                           claims_first, dfbb)
from solver.solo import new_solo_game, turns_in
from solver.state import key


# ---------------------------------------------------------------------------
# Plan repair
# ---------------------------------------------------------------------------

def _positions(seed: int, actions: tuple) -> list[Game]:
    """The position before each action of `actions`."""
    game = new_solo_game(seed=seed)
    out = []
    for action in actions:
        out.append(fast_clone(game))
        game.apply_action(action)
    return out


def repair(seed: int, plan: Plan, node_budget: int = 2_000,
           moves: Moves = cheap_payments) -> Plan:
    """Shorten `plan` by re-solving its finish from each position, last first."""
    actions = plan.actions
    positions = _positions(seed, actions)
    improved = False
    for i in range(len(actions) - 1, -1, -1):
        tail = actions[i:]
        best = {"turns": turns_in(tail), "actions": tail}
        try:
            dfbb(fast_clone(positions[i]), 0, [], best, Stats(), node_budget,
                 None, moves=moves, seen={}, ordering=claims_first)
        except OutOfBudget:
            pass
        if best["turns"] < turns_in(tail):
            # positions[:i] are unchanged: they come before the splice.
            actions = actions[:i] + tuple(best["actions"])
            improved = True
    result = Plan(turns_in(actions), actions,
                  plan.bot + "+repair" if improved else plan.bot)
    verify(seed, result)
    return result


# ---------------------------------------------------------------------------
# Beam search
# ---------------------------------------------------------------------------

_WEIGHTS: Optional[Weights] = None
_SCALES: Optional[Scales] = None


def _scorer():
    global _WEIGHTS, _SCALES
    if _WEIGHTS is None:
        _WEIGHTS, _SCALES = Weights.load("tuned_split"), Scales.load()
    return _WEIGHTS, _SCALES


def beam(seed: int, width: int = 100, max_turns: int = 80,
         moves: Moves = cheap_payments) -> Optional[Plan]:
    """Shortest win a width-limited, bot-ranked breadth-first search finds."""
    weights, scales = _scorer()
    layer = [(new_solo_game(seed=seed), ())]
    with _solo_scoring():
        for _ in range(max_turns):
            candidates: dict = {}          # key -> (score, game, actions)
            frontier = list(layer)
            while frontier:
                parent, acts = frontier.pop()
                for action in moves(parent):
                    child = fast_clone(parent)
                    child.apply_action(action)
                    path = acts + (action,)
                    if child.game_over:
                        plan = Plan(turns_in(path), path, f"beam{width}")
                        verify(seed, plan)
                        return plan
                    if child.pending_discard is not None:
                        # the discard is part of this turn: expand it here
                        frontier.append((child, path))
                        continue
                    k = key(child)
                    if k in candidates:
                        continue
                    score, _ = evaluate(parent, child, 0, weights, scales)
                    candidates[k] = (score, child, path)
            ranked = sorted(candidates.values(), key=lambda t: -t[0])[:width]
            if not ranked:
                return None
            layer = [(g, p) for _, g, p in ranked]
    return None


# ---------------------------------------------------------------------------
# The gap report
# ---------------------------------------------------------------------------

@dataclass
class Gap:
    seed: int
    lower: int                     # max(h, flow bound) at the opening
    bots: int                      # step-5 incumbent
    beam: Optional[int]
    best: Plan                     # shortest verified plan of all

    @property
    def gap(self) -> int:
        return self.best.turns - self.lower


def gap_report(seed: int, width: int = 1000, repair_budget: int = 2_000) -> Gap:
    """Measured on seed 0: beam width 20/100/300/1000 gave 38/35/34/31
    against the bots' 41, and repair added nothing on top of a wide beam's
    plan (its endings are already good) — so only the best plan is repaired,
    as a cheap last pass."""
    opening = new_solo_game(seed=seed)
    lower = max(h(opening), flow_bound(opening))
    bots = upper_bound(seed)
    beamed = beam(seed, width)
    best = bots if beamed is None or bots.turns <= beamed.turns else beamed
    best = repair(seed, best, repair_budget)
    return Gap(seed, lower, bots.turns, beamed.turns if beamed else None, best)


if __name__ == "__main__":  # pragma: no cover - manual run
    import sys
    seeds = range(int(sys.argv[1])) if len(sys.argv) > 1 else range(10)
    print(f"{'seed':>4} {'h':>3} {'bots':>5} {'beam':>5} {'best':>5} {'gap':>4}  via")
    for s in seeds:
        t = time.time()
        g = gap_report(s)
        print(f"{s:>4} {g.lower:>3} {g.bots:>5} {g.beam or '-':>5} {g.best.turns:>5} "
              f"{g.gap:>4}  {g.best.bot}  ({time.time() - t:.0f}s)", flush=True)

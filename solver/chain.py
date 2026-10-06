"""Chained sub-goals: proven-fewest turns to the NEXT golem, six times over.

Full-game optimality is out of reach: the search pays ~x4-8 per turn of slack
between b and h, and the opening has ~14 (see docs/briefs/SOLVER_SEARCH_HANDOFF.md).
One golem at a time, the slack is a few turns, so each piece can be PROVEN:

    from this position, no plan claims one more golem in fewer turns.

Two claims must be kept apart in any write-up. Each segment is exactly
optimal for its own sub-goal. The chain of segments is NOT globally optimal:
racing to the next golem can leave a worse position for the rest of the game
(the myopia the paper's increments share). It is an upper bound like any
other plan, verified by replay.

Myopia is softened, not removed: among the plans that reach the next golem
in the proven-minimal number of turns, the one leaving the lowest full-game
h (then the highest potential) is taken. That keeps every segment optimal in
turns.

Measured, and the reason this is NOT the upper bound the gap report uses:

    one golem a segment    seed 0: 41 = 5+7+9+8+6+6     all proven, 2s
                           seed 1: 52 = 5+9+10+11+10+7  all proven, 15s
    two golems a segment   seed 0: 37 = 10+13+14?       last not proven
                           seed 1: 39 = 12+13+14?
    three                  seed 0: 47 = 18?+29?          none proven
    beam, width 1000       seed 0: 31, seed 1: 35

Every one-golem segment is provably fastest, yet the chain loses 10-20 turns:
racing to each golem never pays for a card engine, so the later ones get
slower. Longer segments are less myopic but stop being provable.

The sub-goal needs no engine change: the segment is searched on a clone whose
win_target is one more than the golems already held. The engine ends a solo
game on the claim that reaches win_target, and h reads win_target too. The
same actions replay on the real game, where the claim simply does not end it.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from bots._engine import Claim, Game
from bots.bots import GreedyBot
from solver.bound import h, potential
from solver.fastclone import fast_clone
from solver.greedy import Plan, verify
from solver.search import (Moves, OutOfBudget, Stats, cheap_payments, playable_moves,
                           claims_first, dfbb, turn_cost)
from solver.solo import new_solo_game, turns_in
from solver.state import key


@dataclass
class Segment:
    actions: tuple
    turns: int
    proven: bool             # no shorter route to this golem exists
    nodes: int


@dataclass
class Chain:
    plan: Plan
    segments: list[Segment] = field(default_factory=list)

    @property
    def all_proven(self) -> bool:
        return all(s.proven for s in self.segments)


def _sub_goal(game: Game, step: int = 1) -> Game:
    sub = fast_clone(game)
    sub.win_target = min(game.win_target, len(game.players[0].point_cards) + step)
    return sub


def _greedy_segment(game: Game, seed: int, step: int = 1, cap: int = 300) -> tuple:
    """GreedyBot up to and including the claim that reaches the sub-goal:
    the starting b."""
    sim, bot, rng = _sub_goal(game, step), GreedyBot(seed=seed), random.Random(seed)
    actions = []
    while not sim.game_over and len(actions) < cap:
        a = bot.choose(sim) or rng.choice(sim.legal_actions())
        sim.apply_action(a)
        actions.append(a)
    if not sim.game_over:
        raise RuntimeError("greedy bot never reached the next golem")
    return tuple(actions)


def _full_h(end: Game, real_target: int) -> int:
    saved = end.win_target
    end.win_target = real_target
    try:
        return h(end)
    finally:
        end.win_target = saved


def _best_ending(sub: Game, turns: int, real_target: int, moves: Moves,
                 node_budget: int) -> tuple | None:
    """Among plans reaching the sub-goal in exactly `turns`, the one leaving
    the best position: lowest full-game h, then highest potential. Explores
    only children that can still arrive in `turns` (g + h <= turns)."""
    best = [None, None]              # (rank, actions)
    seen: dict = {}
    budget = [node_budget]

    def walk(game: Game, g: int, path: list) -> None:
        budget[0] -= 1
        if budget[0] < 0:
            raise OutOfBudget
        if game.game_over:
            if g == turns:
                rank = (_full_h(game, real_target), -potential(game))
                if best[0] is None or rank < best[0]:
                    best[0], best[1] = rank, tuple(path)
            return
        for action in claims_first(game, moves(game)):
            child = fast_clone(game)
            child.apply_action(action)
            cg = g + turn_cost(action)
            if cg + h(child) > turns:
                continue
            k = key(child)
            if seen.get(k, 1 << 30) <= cg:
                continue
            seen[k] = cg
            path.append(action)
            walk(child, cg, path)
            path.pop()

    try:
        walk(fast_clone(sub), 0, [])
    except OutOfBudget:
        pass                         # keep the best ending found so far
    return best[1]


def next_golem(game: Game, seed: int, node_budget: int = 30_000,
               tie_budget: int = 20_000, moves: Moves = playable_moves,
               step: int = 1) -> Segment:
    """Fewest turns from `game` to `step` more golems, proven if within
    budget."""
    real_target = game.win_target
    sub = _sub_goal(game, step)
    start = _greedy_segment(game, seed, step)
    best = {"turns": turns_in(start), "actions": start}
    stats = Stats()
    proven = True
    try:
        dfbb(fast_clone(sub), 0, [], best, stats, node_budget, None,
             moves=moves, seen={}, ordering=claims_first)
    except OutOfBudget:
        proven = False
    actions = tuple(best["actions"])
    if proven:
        ending = _best_ending(sub, best["turns"], real_target, moves, tie_budget)
        if ending is not None:
            actions = ending
    return Segment(actions, turns_in(actions), proven, stats.nodes)


def chain(seed: int, node_budget: int = 30_000, tie_budget: int = 20_000,
          step: int = 1) -> Chain:
    game = new_solo_game(seed=seed)
    segments = []
    while not game.game_over:
        seg = next_golem(game, seed, node_budget, tie_budget, step=step)
        for action in seg.actions:
            game.apply_action(action)
        if not isinstance(seg.actions[-1], Claim):
            raise AssertionError("a segment must end on its claim")
        segments.append(seg)
    actions = tuple(a for s in segments for a in s.actions)
    plan = Plan(turns_in(actions), actions, "chain")
    verify(seed, plan)
    return Chain(plan, segments)


if __name__ == "__main__":  # pragma: no cover - manual run
    import sys
    import time
    for s in (range(int(sys.argv[1])) if len(sys.argv) > 1 else range(10)):
        t = time.time()
        c = chain(s)
        parts = " + ".join(f"{x.turns}{'' if x.proven else '?'}" for x in c.segments)
        print(f"seed {s}: {c.plan.turns} turns = {parts}   "
              f"({'every segment proven' if c.all_proven else '? = not proven'}, "
              f"{time.time() - t:.0f}s)", flush=True)

"""Step 8: the benchmark every speed-up is measured against.

Step 7 checked correctness with dfbb started at b = optimum + 1. That says
nothing about speed in the realistic case, where dfbb starts from a loose
bound and has to find AND prove the optimum itself. This measures that, on
two fixed suites:

    tiny   30 fast tiny boards, dfbb started at b = 15 (the optima are 4-7).
           Every answer is compared with the brute force, so a speed-up that
           loses the optimum shows up here as a wrong answer.

    late   real-game positions with 4 golems claimed (8 seeds), dfbb started
           from the greedy bot's own remaining line. No brute force can check
           these; they measure how much of a real game the search can finish.

Each run prints nodes, time, and for `late` how many positions finished
within the node budget. A speed-up earns its place by cutting nodes or time
without changing a single `tiny` answer.

    python -m solver.bench                 # every config in CONFIGS
    python -m solver.bench baseline seen   # just these

To add your own speed-up: give dfbb a keyword for it, then add an entry to
CONFIGS holding the dfbb keywords that switch it on.
"""

from __future__ import annotations

import random
import sys
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

from bots.bots import GreedyBot
from solver.search import (OutOfBudget, Stats, cheap_payments, claims_first,
                           dfbb, produce_first)
from solver.solo import new_solo_game, turns_in
from solver.tiny import brute_force, fast_board

TINY_BOARDS = range(30)
TINY_B = 15
TINY_BUDGET = 200_000

LATE_SEEDS = range(8)
LATE_CLAIMED = 4
LATE_BUDGET = 20_000

# Named configurations. Each is a FUNCTION returning the dfbb keyword
# arguments, called afresh for every search: a seen-state table shared
# between two different positions would skip states from the wrong game.
# Every entry keeps the yellow/green payment rule from step 7.
CONFIGS: dict[str, Callable[[], dict]] = {
    "baseline": lambda: {"moves": cheap_payments},
    "seen":     lambda: {"moves": cheap_payments, "seen": {}},
    "seen+claims":  lambda: {"moves": cheap_payments, "seen": {},
                             "ordering": claims_first},
    "seen+produce": lambda: {"moves": cheap_payments, "seen": {},
                             "ordering": produce_first},
}

# Changes that are not switches (like the faster h, which replaced the old
# one outright) are measured by running the same config before and after.


@lru_cache(maxsize=None)
def tiny_truth(seed: int) -> int:
    return brute_force(fast_board(seed).game(), moves=cheap_payments)


@lru_cache(maxsize=None)
def late_positions() -> tuple:
    """One position per seed: the first with LATE_CLAIMED golems, taken from
    a GreedyBot game, with that game's remaining line as the starting plan."""
    out = []
    for seed in LATE_SEEDS:
        game = new_solo_game(seed=seed)
        bot, rng = GreedyBot(seed=seed), random.Random(seed)
        line = []
        while not game.game_over:
            action = bot.choose(game) or rng.choice(game.legal_actions())
            line.append((game.clone(), action))
            game.apply_action(action)
        for i, (snap, _) in enumerate(line):
            if len(snap.players[0].point_cards) == LATE_CLAIMED:
                out.append((seed, snap, tuple(a for _, a in line[i:])))
                break
    return tuple(out)


@dataclass
class Report:
    name: str
    tiny_nodes: int = 0
    tiny_seconds: float = 0.0
    tiny_wrong: int = 0
    tiny_unfinished: int = 0
    late_nodes: int = 0
    late_seconds: float = 0.0
    late_finished: int = 0
    late_total: int = 0
    late_turns: int = 0          # sum of best turns found, finished or not

    def lines(self) -> str:
        return (f"{self.name:>16} | tiny: {self.tiny_nodes:>9,} nodes "
                f"{self.tiny_seconds:6.1f}s  wrong {self.tiny_wrong} "
                f"unfinished {self.tiny_unfinished} | late: "
                f"{self.late_finished}/{self.late_total} finished "
                f"{self.late_nodes:>8,} nodes {self.late_seconds:6.1f}s "
                f"turns {self.late_turns}")


def run_config(name: str, make_kwargs: Callable[[], dict]) -> Report:
    r = Report(name)

    for seed in TINY_BOARDS:
        truth = tiny_truth(seed)
        best = {"turns": TINY_B, "actions": ()}
        stats = Stats()
        try:
            dfbb(fast_board(seed).game(), 0, [], best, stats, TINY_BUDGET, None,
                 **make_kwargs())
        except OutOfBudget:
            r.tiny_unfinished += 1
        else:
            r.tiny_wrong += best["turns"] != truth
        r.tiny_nodes += stats.nodes
        r.tiny_seconds += stats.elapsed()

    for seed, snap, rest in late_positions():
        best = {"turns": turns_in(rest), "actions": rest}
        stats = Stats()
        try:
            dfbb(snap.clone(), 0, [], best, stats, LATE_BUDGET, None, **make_kwargs())
        except OutOfBudget:
            pass
        else:
            r.late_finished += 1
        r.late_total += 1
        r.late_nodes += stats.nodes
        r.late_seconds += stats.elapsed()
        r.late_turns += best["turns"]
    return r


if __name__ == "__main__":  # pragma: no cover - manual run
    names = sys.argv[1:] or list(CONFIGS)
    t = time.time()
    for s in TINY_BOARDS:
        tiny_truth(s)
    late_positions()
    print(f"(suites prepared in {time.time() - t:.0f}s)")
    for name in names:
        print(run_config(name, CONFIGS[name]).lines(), flush=True)

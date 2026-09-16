"""Head-to-head comparison, paired and seat-swapped.

The minimum needed to answer "does A beat B?" honestly. Step 5 grows this
into the real arena (multiprocessing, per-seat breakdowns, JSON output); this
module exists so Step 4's ">60% of games" bar can be checked at all.

    python -m bots.match --a handset_v1 --b greedy --games 300

WHY PAIRED AND SEAT-SWAPPED

Century is not seat-symmetric. Later seats start with better crystals (seat 0
gets 3Y, seats 1-2 get 4Y, seats 3-4 get 3Y+1G) and the engine breaks score
ties toward the *highest* seat. So "A won 55%" means nothing unless A and B
each played each seat equally often.

Every seed is therefore played twice, once with A in seat 0 and once with B
there, on the identical deck shuffle. Any seat advantage cancels exactly, and
the comparison measures the bots rather than the seating.
"""

from __future__ import annotations

import argparse
import math
import random
import statistics
from dataclasses import dataclass, field
from typing import Callable, Optional

from bots.bots import ACTION_CAP, GreedyBot, RandomBot, WeightedBot, play_game
from bots.features import Scales, Weights

BotFactory = Callable[[int], object]     # seed -> bot


def wilson(wins: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% confidence interval for a win rate.

    Wilson rather than the textbook normal interval: it stays inside [0, 1]
    and behaves at small samples and extreme rates, where the normal one
    produces nonsense like a 103% upper bound.
    """
    if n == 0:
        return (0.0, 1.0)
    p = wins / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    halfwidth = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - halfwidth), min(1.0, centre + halfwidth))


@dataclass
class MatchResult:
    a_name: str
    b_name: str
    games: int = 0
    a_wins: float = 0.0
    b_wins: float = 0.0
    a_scores: list[float] = field(default_factory=list)
    b_scores: list[float] = field(default_factory=list)
    margins: list[float] = field(default_factory=list)     # a - b
    a_wins_by_seat: dict[int, float] = field(default_factory=dict)
    seat_games: dict[int, int] = field(default_factory=dict)
    lengths: list[int] = field(default_factory=list)
    capped: int = 0
    a_golems: list[int] = field(default_factory=list)
    b_golems: list[int] = field(default_factory=list)

    @property
    def a_rate(self) -> float:
        return self.a_wins / self.games if self.games else 0.0

    @property
    def ci(self) -> tuple[float, float]:
        return wilson(self.a_wins, self.games)

    def summary(self) -> str:
        lo, hi = self.ci
        beats = "yes" if lo > 0.5 else ("no" if hi < 0.5 else "inconclusive")
        lines = [
            f"{self.a_name} vs {self.b_name}   ({self.games} games, seats swapped)",
            f"  {self.a_name} win rate : {self.a_rate:.1%}  "
            f"95% CI [{lo:.1%}, {hi:.1%}]   better than coin-flip: {beats}",
            f"  mean score       : {statistics.fmean(self.a_scores):.1f} "
            f"vs {statistics.fmean(self.b_scores):.1f}",
            f"  mean margin      : {statistics.fmean(self.margins):+.1f}",
            f"  mean golems      : {statistics.fmean(self.a_golems):.2f} "
            f"vs {statistics.fmean(self.b_golems):.2f}",
            f"  game length      : {statistics.fmean(self.lengths):.0f} actions"
            f"  (capped: {self.capped})",
        ]
        for seat in sorted(self.seat_games):
            n = self.seat_games[seat]
            w = self.a_wins_by_seat.get(seat, 0.0)
            lo_s, hi_s = wilson(w, n)
            lines.append(f"  {self.a_name} in seat {seat}: {w / n:.1%} "
                         f"of {n}  CI [{lo_s:.1%}, {hi_s:.1%}]")
        return "\n".join(lines)


def run_match(make_a: BotFactory, make_b: BotFactory, seeds, a_name="A", b_name="B",
              cap: int = ACTION_CAP) -> MatchResult:
    """Play every seed twice, swapping which bot sits in seat 0."""
    res = MatchResult(a_name=a_name, b_name=b_name)

    for seed in seeds:
        for a_seat in (0, 1):
            # Bot RNG is derived from the seed so a run is reproducible, but
            # differs per arrangement so the two halves aren't correlated.
            bot_a = make_a(seed * 4 + a_seat)
            bot_b = make_b(seed * 4 + a_seat + 2)
            line = [bot_a, bot_b] if a_seat == 0 else [bot_b, bot_a]
            out = play_game(line, seed=seed, cap=cap)

            ai, bi = (0, 1) if a_seat == 0 else (1, 0)
            res.games += 1
            res.a_scores.append(out["scores"][ai])
            res.b_scores.append(out["scores"][bi])
            res.margins.append(out["scores"][ai] - out["scores"][bi])
            res.a_golems.append(out["golems"][ai])
            res.b_golems.append(out["golems"][bi])
            res.lengths.append(out["actions"])
            res.capped += bool(out["capped"])

            res.seat_games[ai] = res.seat_games.get(ai, 0) + 1
            if out["winner"] == ai:
                res.a_wins += 1
                res.a_wins_by_seat[ai] = res.a_wins_by_seat.get(ai, 0.0) + 1
            else:
                res.b_wins += 1
    return res


# --------------------------------------------------------------------------
# Factories
# --------------------------------------------------------------------------

def make_factory(spec: str, scales: Optional[Scales] = None,
                 samples: int = 1) -> tuple[BotFactory, str]:
    """'random' / 'greedy' / a weights-file name -> (factory, display name)."""
    if spec == "random":
        return (lambda s: RandomBot(seed=s)), "random"
    if spec == "greedy":
        return (lambda s: GreedyBot(seed=s)), "greedy"
    w = Weights.load(spec)
    sc = scales if scales is not None else Scales.load()
    return (lambda s: WeightedBot(w, sc, seed=s, samples=samples, name=w.name)), w.name


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="handset_v1")
    ap.add_argument("--b", default="greedy")
    ap.add_argument("--games", type=int, default=200,
                    help="seed count; each seed is played twice (seats swapped)")
    ap.add_argument("--seed-base", type=int, default=0,
                    help="use a DIFFERENT base for tuning and for reporting")
    ap.add_argument("--samples", type=int, default=1)
    args = ap.parse_args()

    fa, na = make_factory(args.a, samples=args.samples)
    fb, nb = make_factory(args.b, samples=args.samples)
    seeds = range(args.seed_base, args.seed_base + args.games)
    res = run_match(fa, fb, seeds, a_name=na, b_name=nb)
    print(res.summary())


if __name__ == "__main__":
    main()

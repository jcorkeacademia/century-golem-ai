"""Run many games between bots and report who actually wins.

    python -m bots.arena --bots handset_v1 greedy --players 2 --games 1000 --workers 8

Everything after this step is a claim about a win rate, so this module has one
job: produce win rates that are properties of the *bots* rather than of the
seats they sat in or the shuffles they happened to get.

Two devices do that work.

PAIRED SEEDS — every lineup plays the identical list of seeds, so both bots
meet the same decks. Without this, one bot's "advantage" can be nothing but a
luckier sample of shuffles.

SEAT ROTATION — Century is not seat-symmetric. Starting crystals differ by
seat (3Y / 4Y / 4Y / 3Y+1G / 3Y+1G) and the engine breaks score ties toward
the *highest* seat. So each seed is played once per cyclic rotation: in a
3-player match, seed 42 is played three times with the bots shifted round by
one each time. Every bot then occupies every seat exactly equally and the
asymmetry cancels exactly rather than approximately.

---------------------------------------------------------------------------
WHY BOTS ARE DESCRIBED BY STRINGS

This machine has no `fork` — Windows multiprocessing only offers `spawn`, so
everything sent to a worker must pickle, and a lambda or a live bot object
does not. Workers therefore receive *specs* ("greedy", "handset_v1",
"greedy:build_until=0") and build their own bots, caching them per process so
a weights file is read once rather than once per game.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import os
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from bots.bots import ACTION_CAP, GreedyBot, RandomBot, WeightedBot, play_game
from bots.features import Scales, Weights

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results" / "arena"


# --------------------------------------------------------------------------
# Specs -> bots
# --------------------------------------------------------------------------

# Cache the expensive, immutable part — a parsed weights file and the scales —
# never the bot itself. A bot carries live RNG state, so reusing one across
# games makes a game's outcome depend on what ran before it in that worker,
# and the whole run stops being reproducible. (It did: worker counts of 1 and
# 4 produced different scores until this was split.)
_WEIGHTS_CACHE: dict[str, tuple[Weights, Scales]] = {}


def parse_spec(spec: str) -> tuple[str, dict]:
    """'greedy:build_until=3' -> ('greedy', {'build_until': 3}).

    Splits on the LAST colon and only when the tail actually looks like
    options, because a spec is often a Windows path: `C:\\...\\cand.json`
    would otherwise parse as the bot named "C" with junk options.
    """
    head, sep, tail = spec.rpartition(":")
    if not sep or "=" not in tail:
        head, tail = spec, ""
    opts: dict[str, object] = {}
    for part in filter(None, tail.split(",")):
        k, _, v = part.partition("=")
        try:
            opts[k] = int(v)
        except ValueError:
            try:
                opts[k] = float(v)
            except ValueError:
                opts[k] = v
    return head, opts


def build_bot(spec: str, seed: int):
    """Construct a FRESH bot for one game, with weights loaded at most once.

    Fresh every time on purpose — see `_WEIGHTS_CACHE`. The seed makes the
    bot's randomness a pure function of the task, so a run reproduces
    regardless of how the work was divided between processes.
    """
    head, opts = parse_spec(spec)
    if head == "random":
        return RandomBot(seed=seed, name="random", **opts)
    if head == "greedy":
        return GreedyBot(seed=seed, name="greedy", **opts)
    got = _WEIGHTS_CACHE.get(head)
    if got is None:
        got = (Weights.load(head), Scales.load())
        _WEIGHTS_CACHE[head] = got
    w, sc = got
    return WeightedBot(w, sc, seed=seed, name=w.name, **opts)


def spec_label(spec: str) -> str:
    """A short display name, unique per spec position."""
    head, opts = parse_spec(spec)
    if head.endswith(".json") or "/" in head or "\\" in head:
        head = Path(head).stem          # a weights path prints as its name
    if not opts:
        return head
    return head + "[" + ",".join(f"{k}={v}" for k, v in opts.items()) + "]"


# --------------------------------------------------------------------------
# One game, in a worker
# --------------------------------------------------------------------------

def _play_one(task) -> dict:
    """(specs, n_players, seed, rotation, cap) -> per-bot outcome.

    `rotation` shifts which seat each bot occupies. Bot b sits in seat
    (b + rotation) % n, so summing over rotations puts every bot in every
    seat the same number of times.
    """
    specs, n_players, seed, rotation, cap = task
    n = n_players
    seat_of = [(b + rotation) % n for b in range(n)]
    bot_in_seat = [0] * n
    for b, s in enumerate(seat_of):
        bot_in_seat[s] = b

    # Bot RNG depends on the arrangement as well as the seed, so the two
    # halves of a paired comparison are not correlated — but it is still a
    # pure function of the task, so the whole run reproduces exactly.
    line = [build_bot(specs[bot_in_seat[s]], (seed * 131 + rotation * 17 + s))
            for s in range(n)]
    out = play_game(line, seed=seed, cap=cap)

    per_bot = []
    for b in range(n):
        s = seat_of[b]
        per_bot.append({
            "bot": b, "seat": s,
            "score": out["scores"][s],
            "golems": out["golems"][s],
            "golem_points": out["golem_points"][s],
            "won": out["winner"] == s,
            "ended": out["ender"] == s,
        })
    best_other = [max(out["scores"][t] for t in range(n) if t != seat_of[b])
                  for b in range(n)]
    for b in range(n):
        per_bot[b]["margin"] = per_bot[b]["score"] - best_other[b]

    return {
        "seed": seed, "rotation": rotation,
        "actions": out["actions"], "capped": out["capped"],
        "finished": out["finished"], "bots": per_bot,
    }


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------

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
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


@dataclass
class BotStats:
    label: str
    games: int = 0
    wins: float = 0.0
    scores: list[float] = field(default_factory=list)
    margins: list[float] = field(default_factory=list)
    golems: list[int] = field(default_factory=list)
    golem_points: list[int] = field(default_factory=list)
    ended: int = 0
    wins_by_seat: dict[int, float] = field(default_factory=dict)
    games_by_seat: dict[int, int] = field(default_factory=dict)

    @property
    def win_rate(self) -> float:
        return self.wins / self.games if self.games else 0.0

    @property
    def ci(self) -> tuple[float, float]:
        return wilson(self.wins, self.games)

    @property
    def points_per_golem(self) -> float:
        total = sum(self.golems)
        return sum(self.golem_points) / total if total else 0.0

    def as_dict(self) -> dict:
        lo, hi = self.ci
        return {
            "label": self.label, "games": self.games, "wins": self.wins,
            "win_rate": self.win_rate, "ci_low": lo, "ci_high": hi,
            "mean_score": statistics.fmean(self.scores) if self.scores else 0.0,
            "mean_margin": statistics.fmean(self.margins) if self.margins else 0.0,
            "mean_golems": statistics.fmean(self.golems) if self.golems else 0.0,
            "points_per_golem": self.points_per_golem,
            "ended_share": self.ended / self.games if self.games else 0.0,
            "win_rate_by_seat": {
                str(s): (self.wins_by_seat.get(s, 0.0) / n if n else 0.0)
                for s, n in sorted(self.games_by_seat.items())
            },
            "games_by_seat": {str(s): n for s, n in sorted(self.games_by_seat.items())},
        }


@dataclass
class ArenaResult:
    specs: list[str]
    labels: list[str]
    n_players: int
    seeds: list[int]
    rotate_seats: bool
    stats: list[BotStats]
    games: int = 0
    capped: int = 0
    lengths: list[int] = field(default_factory=list)
    unfinished: int = 0
    elapsed: float = 0.0
    meta: dict = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            f"{' vs '.join(self.labels)}   "
            f"{self.n_players}p, {self.games} games "
            f"({len(self.seeds)} seeds x {self.n_players if self.rotate_seats else 1} rotations)",
            f"  {self.elapsed:.1f}s   {self.games / self.elapsed:.1f} games/s"
            f"   mean length {statistics.fmean(self.lengths):.0f} actions"
            f"   capped {self.capped}   unfinished {self.unfinished}",
            "",
            f"  {'bot':<18}{'win rate':>10}{'95% CI':>18}{'score':>8}{'margin':>8}"
            f"{'golems':>8}{'pts/gol':>9}{'ended':>8}",
            "  " + "-" * 87,
        ]
        for st in self.stats:
            lo, hi = st.ci
            lines.append(
                f"  {st.label:<18}{st.win_rate:>9.1%}"
                f"{f'[{lo:.1%}, {hi:.1%}]':>18}"
                f"{statistics.fmean(st.scores):>8.1f}"
                f"{statistics.fmean(st.margins):>+8.1f}"
                f"{statistics.fmean(st.golems):>8.2f}"
                f"{st.points_per_golem:>9.1f}"
                f"{st.ended / st.games:>8.1%}")
        lines.append("")
        lines.append("  win rate by seat (each bot plays every seat equally often):")
        for st in self.stats:
            cells = []
            for s, n in sorted(st.games_by_seat.items()):
                w = st.wins_by_seat.get(s, 0.0)
                cells.append(f"seat {s}: {w / n:5.1%}")
            lines.append(f"    {st.label:<18}" + "   ".join(cells))
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {
            "meta": self.meta,
            "specs": self.specs, "labels": self.labels,
            "n_players": self.n_players, "rotate_seats": self.rotate_seats,
            "seeds": [self.seeds[0], self.seeds[-1]] if self.seeds else [],
            "n_seeds": len(self.seeds),
            "games": self.games, "capped": self.capped,
            "unfinished": self.unfinished,
            "mean_length": statistics.fmean(self.lengths) if self.lengths else 0.0,
            "elapsed_s": self.elapsed,
            "games_per_s": self.games / self.elapsed if self.elapsed else 0.0,
            "bots": [st.as_dict() for st in self.stats],
        }


# --------------------------------------------------------------------------
# The runner
# --------------------------------------------------------------------------

def git_commit() -> Optional[str]:
    """Log the code version with the results (brief §5.8)."""
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=Path(__file__).resolve().parent.parent,
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except Exception:
        return None


def run_arena(specs: Sequence[str], n_players: int, seeds: Sequence[int],
              rotate_seats: bool = True, workers: int = 1,
              cap: int = ACTION_CAP, progress: bool = False) -> ArenaResult:
    """Play every seed under every seat rotation and aggregate."""
    specs = list(specs)
    if len(specs) != n_players:
        raise ValueError(f"{len(specs)} bots for a {n_players}-player game")
    seeds = list(seeds)
    labels = [spec_label(s) for s in specs]
    # Two bots with the same spec would otherwise be indistinguishable in the
    # output; suffix duplicates by position.
    counts = {lab: labels.count(lab) for lab in set(labels)}
    seen: dict[str, int] = {}
    for i, lab in enumerate(labels):
        if counts[lab] > 1:
            seen[lab] = seen.get(lab, 0) + 1
            labels[i] = f"{lab}#{seen[lab]}"

    rotations = range(n_players) if rotate_seats else (0,)
    tasks = [(specs, n_players, seed, rot, cap)
             for seed in seeds for rot in rotations]

    stats = [BotStats(label=lab) for lab in labels]
    result = ArenaResult(specs=specs, labels=labels, n_players=n_players,
                         seeds=seeds, rotate_seats=rotate_seats, stats=stats)

    t0 = time.perf_counter()
    if workers <= 1:
        outputs = map(_play_one, tasks)
    else:
        pool = mp.Pool(processes=workers)
        outputs = pool.imap_unordered(_play_one, tasks, chunksize=4)

    done = 0
    try:
        for out in outputs:
            done += 1
            result.games += 1
            result.lengths.append(out["actions"])
            result.capped += bool(out["capped"])
            result.unfinished += (not out["finished"])
            for row in out["bots"]:
                st = stats[row["bot"]]
                st.games += 1
                st.scores.append(row["score"])
                st.margins.append(row["margin"])
                st.golems.append(row["golems"])
                st.golem_points.append(row["golem_points"])
                st.ended += bool(row["ended"])
                seat = row["seat"]
                st.games_by_seat[seat] = st.games_by_seat.get(seat, 0) + 1
                if row["won"]:
                    st.wins += 1
                    st.wins_by_seat[seat] = st.wins_by_seat.get(seat, 0.0) + 1
            if progress and done % 200 == 0:
                el = time.perf_counter() - t0
                print(f"    {done}/{len(tasks)} games  {done / el:.1f}/s",
                      file=sys.stderr)
    finally:
        if workers > 1:
            pool.close()
            pool.join()

    result.elapsed = time.perf_counter() - t0
    result.meta = {
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "python": sys.version.split()[0],
        "workers": workers,
        "cap": cap,
        "cpu_count": os.cpu_count(),
    }
    return result


def save(result: ArenaResult, root: Path = RESULTS_DIR) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = root / stamp
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(result.as_dict(), indent=2))
    (out / "summary.txt").write_text(result.summary() + "\n")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Run a bot tournament.")
    ap.add_argument("--bots", nargs="+", required=True,
                    help="one spec per seat: random | greedy | <weights name>, "
                         "with options as 'greedy:build_until=3'")
    ap.add_argument("--players", type=int, default=None,
                    help="defaults to the number of bots given")
    ap.add_argument("--games", type=int, default=200,
                    help="seed count; total games = seeds x rotations")
    ap.add_argument("--seed-base", type=int, default=0,
                    help="use a DIFFERENT base for tuning and for reporting")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--cap", type=int, default=ACTION_CAP)
    ap.add_argument("--no-rotate", action="store_true")
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    n_players = args.players or len(args.bots)
    specs = list(args.bots)
    if len(specs) == 1:
        specs *= n_players
    if len(specs) != n_players:
        ap.error(f"{len(specs)} bots given for a {n_players}-player game")

    seeds = range(args.seed_base, args.seed_base + args.games)
    res = run_arena(specs, n_players, seeds, rotate_seats=not args.no_rotate,
                    workers=args.workers, cap=args.cap, progress=not args.quiet)
    print(res.summary())
    if not args.no_save:
        print(f"\nsaved to {save(res)}")


if __name__ == "__main__":
    main()

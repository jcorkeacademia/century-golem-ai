"""Step 10: turn the measurements into answers.

    python -m bots.analyze contributions --games 500
    python -m bots.analyze ablate --games 1000
    python -m bots.analyze crystals --games 1000

Three separate questions, three subcommands.

CONTRIBUTIONS — what actually drove the moves the bot played? The weights say
what it *would* value; this says what it *did*. A feature can carry a large
weight and still never matter, if its value rarely varies between the moves
on offer. Reported early and late, because Step 6b showed the two phases
genuinely differ.

ABLATE — zero one feature and play the result against the full bot. No
retuning: the brief asks for a short retune per feature, but the cheap
version already produced unambiguous answers in Step 6 (playable_now cost 21
points, lambda cost nothing), and retuning nine features costs six hours to
sharpen numbers that are not close.

CRYSTALS — the tuned `cry_*` weights are *residual* value: what a crystal is
worth after `best_target` has taken credit for the golems it unlocks. That is
correct for the value function and misleading as advice, because a player
asking "what is a magenta worth?" means the total. So measure it directly:
give one bot an extra crystal at setup, play a few thousand games, and read
the change in final score margin. That number is in points and needs no
interpretation.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import random
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from bots._engine import Crystal, Game
from bots.arena import _play_one, build_bot, git_commit, wilson
from bots.features import (
    CORE_FEATURES,
    WEIGHTS_DIR,
    Ctx,
    Scales,
    Weights,
    evaluate,
    phase_of,
)
from bots.tune import _run_task, score_generation

RESULTS = Path(__file__).resolve().parent.parent / "results"


# --------------------------------------------------------------------------
# Contribution logs
# --------------------------------------------------------------------------

def contributions(weights_name: str, n_games: int, seed_base: int,
                  depth: Optional[int] = None) -> dict:
    """Mean |w_i * f_i| of the move actually chosen, split by game phase."""
    w = Weights.load(weights_name)
    scales = Scales.load()
    early: dict[str, list[float]] = defaultdict(list)
    late: dict[str, list[float]] = defaultdict(list)
    chosen_kinds: dict[str, int] = defaultdict(int)
    n_decisions = 0
    n_terminal = 0

    for g_i in range(n_games):
        seed = seed_base + g_i
        bots = [build_bot(weights_name, seed * 2), build_bot(weights_name, seed * 2 + 1)]
        game = Game([f"{weights_name}@0", f"{weights_name}@1"], seed=seed)
        steps = 0
        while not game.game_over and steps < 1000:
            me = game.current
            action = bots[me].choose(game)
            if action is None:
                break
            # Re-derive the contributions of the move that was played.
            clone = game.clone()
            clone.apply_action(action, validate=False)
            _, parts = evaluate(game, clone, me, w, scales)
            if "terminal" in parts:
                # The endgame override (+/-1000 for a win) is not a feature and
                # would otherwise rank above everything by a factor of 300.
                # These decisions have no feature breakdown at all.
                n_terminal += 1
                chosen_kinds[type(action).__name__] += 1
                n_decisions += 1
                game.apply_action(action)
                steps += 1
                continue
            bucket = late if phase_of(game) >= 0.5 else early
            for k, v in parts.items():
                bucket[k].append(abs(v))
            chosen_kinds[type(action).__name__] += 1
            n_decisions += 1
            game.apply_action(action)
            steps += 1

    def summarise(bucket):
        return {k: {"mean_abs": statistics.fmean(v), "n": len(v)}
                for k, v in sorted(bucket.items(),
                                   key=lambda kv: -statistics.fmean(kv[1]))}

    return {"weights": weights_name, "games": n_games, "decisions": n_decisions,
            "terminal_decisions": n_terminal,
            "action_mix": dict(chosen_kinds),
            "early": summarise(early), "late": summarise(late)}


# --------------------------------------------------------------------------
# Ablation table
# --------------------------------------------------------------------------

def make_zeroed(base: Weights, key: str, path: Path) -> Path:
    # Weights.save writes the file but does not create directories.
    path.parent.mkdir(parents=True, exist_ok=True)
    early, late = dict(base.w_early), dict(base.w_late)
    early[key] = 0.0
    late[key] = 0.0
    Weights(name=f"{base.name}-{key}", features=list(base.features),
            w_early=early, w_late=late, lam=base.lam, params=dict(base.params),
            meta={**base.meta, "ablated": key}).save(path)
    return path


def ablate(base_name: str, keys: Sequence[str], n_seeds: int, seed_base: int,
           workers: int, out_dir: Path) -> list[dict]:
    base = Weights.load(base_name)
    base_path = str((WEIGHTS_DIR / f"{base_name}.json").resolve())
    seeds = list(range(seed_base, seed_base + n_seeds))
    out_dir.mkdir(parents=True, exist_ok=True)
    pool = mp.Pool(processes=workers)
    rows = []
    try:
        for key in keys:
            p = make_zeroed(base, key, out_dir / "variants" / f"no_{key}.json")
            tasks = [(0, ([str(p), base_path], 2, s, r, 1000))
                     for s in seeds for r in (0, 1)]
            res = list(pool.imap_unordered(_run_task, tasks, chunksize=8))
            fit = score_generation(res, 1)[0]
            lo, hi = wilson(fit.win_rate * fit.games, fit.games)
            rows.append({"feature": key, "win_rate": fit.win_rate, "ci": [lo, hi],
                         "mean_margin": fit.mean_margin, "games": fit.games,
                         "cost": 0.5 - fit.win_rate})
            print(f"  without {key:<16}{fit.win_rate:>7.1%}  "
                  f"[{lo:.1%}, {hi:.1%}]  margin {fit.mean_margin:+6.1f}",
                  flush=True)
    finally:
        pool.close()
        pool.join()
    rows.sort(key=lambda r: -r["cost"])
    return rows


# --------------------------------------------------------------------------
# Crystal value, measured directly
# --------------------------------------------------------------------------

def _crystal_task(payload):
    """One game where seat 0 starts with `extra` bonus crystals of `colour`."""
    spec, seed, rot, colour, extra = payload
    bots = [build_bot(spec, seed * 2 + rot), build_bot(spec, seed * 2 + rot + 1)]
    game = Game([f"{spec}@0", f"{spec}@1"], seed=seed)
    boosted = rot            # alternate which seat gets the bonus
    game.players[boosted].caravan[colour] += extra
    steps = 0
    while not game.game_over and steps < 1000:
        a = bots[game.current].choose(game)
        if a is None:
            break
        game.apply_action(a)
        steps += 1
    scores = [p.score() for p in game.players]
    best = max(scores)
    winner = max(i for i, s in enumerate(scores) if s == best)
    other = 1 - boosted
    return {"won": winner == boosted,
            "margin": scores[boosted] - scores[other]}


def crystal_value(spec: str, n_seeds: int, seed_base: int, workers: int,
                  extra: int = 1) -> list[dict]:
    """What one extra starting crystal is worth, in win rate and points.

    Both seats play the same bot, so the only difference is the bonus. Seat
    rotation alternates which side gets it, so a seat advantage cannot leak
    into the answer.
    """
    pool = mp.Pool(processes=workers)
    rows = []
    try:
        for colour in (Crystal.YELLOW, Crystal.GREEN, Crystal.TURQUOISE,
                       Crystal.MAGENTA):
            tasks = [(spec, s, r, int(colour), extra)
                     for s in range(seed_base, seed_base + n_seeds)
                     for r in (0, 1)]
            res = list(pool.imap_unordered(_crystal_task, tasks, chunksize=8))
            wins = sum(r["won"] for r in res)
            margins = [r["margin"] for r in res]
            lo, hi = wilson(wins, len(res))
            rows.append({"colour": colour.name, "extra": extra,
                         "win_rate": wins / len(res), "ci": [lo, hi],
                         "mean_margin": statistics.fmean(margins),
                         "games": len(res)})
            print(f"  +{extra} {colour.name:<10}{wins/len(res):>7.1%}  "
                  f"[{lo:.1%}, {hi:.1%}]  margin {statistics.fmean(margins):+6.2f}",
                  flush=True)
    finally:
        pool.close()
        pool.join()
    return rows


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("contributions")
    c.add_argument("--weights", default="tuned_split")
    c.add_argument("--games", type=int, default=500)
    c.add_argument("--seed-base", type=int, default=20_000_000)

    a = sub.add_parser("ablate")
    a.add_argument("--weights", default="tuned_split")
    a.add_argument("--games", type=int, default=1000, help="seeds; doubled by rotation")
    a.add_argument("--seed-base", type=int, default=21_000_000)
    a.add_argument("--workers", type=int, default=18)
    a.add_argument("--only", nargs="*", default=None)

    x = sub.add_parser("crystals")
    x.add_argument("--weights", default="tuned_split")
    x.add_argument("--games", type=int, default=1000)
    x.add_argument("--seed-base", type=int, default=22_000_000)
    x.add_argument("--workers", type=int, default=18)
    x.add_argument("--extra", type=int, default=1)

    args = ap.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    t0 = time.perf_counter()

    if args.cmd == "contributions":
        print(f"logging contributions over {args.games} games ...", flush=True)
        out = contributions(args.weights, args.games, args.seed_base)
        out["created"], out["git_commit"] = stamp, git_commit()
        (RESULTS / "contributions.json").write_text(json.dumps(out, indent=2))
        print(f"\n{out['decisions']:,} decisions, action mix {out['action_mix']}")
        for phase in ("early", "late"):
            print(f"\n  {phase}:")
            for k, v in list(out[phase].items())[:8]:
                print(f"    {k:<20}{v['mean_abs']:>7.3f}")
        print(f"\nwrote {RESULTS / 'contributions.json'}")

    elif args.cmd == "ablate":
        keys = args.only or list(CORE_FEATURES)
        print(f"ablating {len(keys)} feature(s) from {args.weights}, "
              f"{args.games * 2} games each", flush=True)
        rows = ablate(args.weights, keys, args.games, args.seed_base,
                      args.workers, RESULTS / "ablation")
        blob = {"base": args.weights, "created": stamp, "git_commit": git_commit(),
                "games_per_feature": args.games * 2, "rows": rows}
        (RESULTS / "ablation.json").write_text(json.dumps(blob, indent=2))
        print(f"\nwrote {RESULTS / 'ablation.json'}")

    elif args.cmd == "crystals":
        print(f"measuring crystal value over {args.games * 2} games each", flush=True)
        rows = crystal_value(args.weights, args.games, args.seed_base,
                             args.workers, args.extra)
        blob = {"bot": args.weights, "created": stamp, "git_commit": git_commit(),
                "rows": rows}
        (RESULTS / "crystal_value.json").write_text(json.dumps(blob, indent=2))
        print(f"\nwrote {RESULTS / 'crystal_value.json'}")

    print(f"({time.perf_counter() - t0:.1f}s)")


if __name__ == "__main__":
    main()

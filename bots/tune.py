"""CMA-ES weight tuning.

    python -m bots.tune --generations 50 --games 200 --workers 18
    python -m bots.tune --resume results/tune/<run_id>

The step the project has been building toward: instead of a human asserting
that a magenta crystal is worth 0.55 points, thousands of self-play games
decide it.

---------------------------------------------------------------------------
WHAT CMA-ES DOES

It keeps a cloud of guesses in parameter space — a mean and a covariance.
Each generation it draws `popsize` candidates from that cloud, scores them,
keeps the better half, and reshapes the cloud toward them. No gradients, no
assumptions about the shape of the landscape, and it handles a noisy fitness
(which a win rate over 200 games very much is).

---------------------------------------------------------------------------
WHY THE PARAMETERS ARE IN POINTS, NOT WEIGHTS

The obvious parameter vector is the weights themselves. That is a trap. The
handset weights span 0.0053 (`cry_y`) to 1.0 (`golem_points`) — a 190x range,
because each weight absorbs its feature's scale. CMA-ES perturbs every
parameter by the same initial step, so `sigma0=0.5` would obliterate `cry_y`
and barely move the large ones. Every parameter needs comparable magnitude.

So the vector is `VALUE[feature]` — victory points per raw unit, the same
currency `make_handset.py` uses — which runs 0.05 to 2.0 across all features.
`golem_points` is pinned at 1.0 as the anchor, since scaling every value at
once would just rescale V without changing any decision.

The output is then directly readable: "tuning decided magenta is worth 0.9
points" rather than "0.0334".
---------------------------------------------------------------------------
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import pickle
import random
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from bots.arena import _play_one, git_commit, wilson
from bots.features import CORE_FEATURES, Scales, Weights
from bots.make_handset import ANCHOR, LAMBDA, VALUE

TUNE_DIR = Path(__file__).resolve().parent.parent / "results" / "tune"

# Every feature except the anchor, in a fixed order, plus lambda at the end.
PARAM_KEYS: tuple[str, ...] = tuple(k for k in CORE_FEATURES if k != ANCHOR)
N_PARAMS = len(PARAM_KEYS) + 1

# How the fitness opponents are sampled. RandomBot is a small share — it is
# there to punish anything that forgets how to play at all, not to be beaten.
POOL_SHARES = {"random": 0.10, "greedy": 0.30, "handset": 0.30, "hof": 0.30}

# Per-parameter search step, in points.
#
# CMA-ES starts spherical: one `sigma0` for every coordinate. That is wrong
# here even in points-space, because the values do not share a magnitude —
# `cry_y` is 0.05 and `dead_hand` is -2.0, a 40x spread. The brief's
# sigma0=0.5 was measured and is far too coarse: it perturbs `best_target`
# (0.35) by up to a full point, which is exactly the regime where a promise
# outprices the points it promises and the bot stops claiming. A three-
# generation trial with a flat 0.5 produced best win rates of 5-15% against a
# pool the starting weights beat about 73% of the time — CMA-ES was spending
# its entire budget climbing back to where it started.
#
# These are "how far might the truth plausibly be from my guess", per feature.
# CMA-ES adapts them as it learns the landscape; they only need to be the
# right order of magnitude.
PARAM_STDS: dict[str, float] = {
    "token_points": 0.25,
    "cry_y": 0.20, "cry_g": 0.25, "cry_b": 0.30, "cry_m": 0.35,
    "best_target": 0.15,     # deliberately tight: this one is dangerous above 1
    "token_race": 0.15,
    "throughput": 0.50,      # plausibly anywhere from 0 to 4 points per YE/turn
    "playable_now": 0.15,
    "exhausted": 0.20,
    "dead_hand": 1.00,       # already -2; the plausible range is wide
}
LAMBDA_STD = 0.20


# --------------------------------------------------------------------------
# Parameter vector <-> weights file
# --------------------------------------------------------------------------

def x0_from_handset() -> list[float]:
    return [VALUE[k] for k in PARAM_KEYS] + [LAMBDA]


def param_stds() -> list[float]:
    """Initial search step per coordinate — see PARAM_STDS."""
    return [PARAM_STDS[k] for k in PARAM_KEYS] + [LAMBDA_STD]


def x_to_values(x: Sequence[float]) -> tuple[dict[str, float], float]:
    values = {ANCHOR: 1.0}
    for k, v in zip(PARAM_KEYS, x):
        values[k] = float(v)
    return values, float(x[-1])


def write_candidate(x: Sequence[float], scales: Scales, path: Path,
                    name: str, depth: int, meta: Optional[dict] = None) -> Path:
    """Materialise a parameter vector as a weights file a worker can load."""
    values, lam = x_to_values(x)
    anchor_scale = scales.get(ANCHOR)
    w = {k: values[k] * scales.get(k) / anchor_scale for k in CORE_FEATURES}
    blob = Weights(
        name=name,
        features=list(CORE_FEATURES),
        w_early=w,
        w_late=dict(w),
        # lambda is a share of the opponent term; negative would mean *helping*
        # the leader, and above 1 would mean caring more about them than about
        # yourself. Neither is a position worth searching.
        lam=min(1.5, max(0.0, lam)),
        params={"ttc_depth": depth, "alpha": 1.0, "beta": 1.0},
        meta={"source": "cma", "value_in_points": values, **(meta or {})},
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    blob.save(path)
    return path


# --------------------------------------------------------------------------
# Fitness
# --------------------------------------------------------------------------

@dataclass
class Fitness:
    win_rate: float
    mean_margin: float
    games: int

    @property
    def score(self) -> float:
        """Higher is better. Margin is a tie-breaker, not a goal — at 0.01 a
        full extra point of margin is worth 1% of win rate, enough to separate
        two candidates that both win half their games and no more."""
        return self.win_rate + 0.01 * self.mean_margin

    @property
    def loss(self) -> float:
        return -self.score


def build_pool(handset_spec: str, hof: Sequence[str]) -> list[tuple[str, float]]:
    """(spec, share) pairs. Hall-of-fame share is split across its members."""
    pool = [("random", POOL_SHARES["random"]),
            ("greedy", POOL_SHARES["greedy"]),
            (handset_spec, POOL_SHARES["handset"])]
    if hof:
        each = POOL_SHARES["hof"] / len(hof)
        pool += [(spec, each) for spec in hof]
    else:
        # No hall of fame yet: give its share to greedy and handset.
        pool = [("random", POOL_SHARES["random"]),
                ("greedy", POOL_SHARES["greedy"] + 0.15),
                (handset_spec, POOL_SHARES["handset"] + 0.15)]
    return pool


def allocate(seeds: Sequence[int], pool: Sequence[tuple[str, float]]) -> list[tuple[str, list[int]]]:
    """Split one seed list across pool opponents by share.

    The *same* split is used for every candidate in a generation — common
    random numbers. Two candidates are then compared on identical decks
    against identical opponents, so a difference between them is a difference
    in play rather than in luck.
    """
    out, i, n = [], 0, len(seeds)
    for k, (spec, share) in enumerate(pool):
        take = n - i if k == len(pool) - 1 else max(1, round(n * share))
        out.append((spec, list(seeds[i:i + take])))
        i += take
    return [(s, xs) for s, xs in out if xs]


def generation_tasks(cand_specs: Sequence[str], pool_alloc, cap: int):
    """Every game the generation needs, as picklable arena tasks."""
    tasks = []
    for ci, cand in enumerate(cand_specs):
        for spec, seeds in pool_alloc:
            for seed in seeds:
                for rot in (0, 1):          # both seatings
                    tasks.append((ci, ([cand, spec], 2, seed, rot, cap)))
    return tasks


def score_generation(results, n_candidates: int) -> list[Fitness]:
    wins = [0.0] * n_candidates
    games = [0] * n_candidates
    margins: list[list[float]] = [[] for _ in range(n_candidates)]
    for ci, out in results:
        row = out["bots"][0]            # the candidate always sits at index 0
        games[ci] += 1
        wins[ci] += bool(row["won"])
        margins[ci].append(row["margin"])
    return [Fitness(win_rate=wins[i] / games[i] if games[i] else 0.0,
                    mean_margin=statistics.fmean(margins[i]) if margins[i] else 0.0,
                    games=games[i])
            for i in range(n_candidates)]


def _run_task(payload):
    ci, task = payload
    return ci, _play_one(task)


# --------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------

@dataclass
class TuneConfig:
    generations: int = 50
    games: int = 200            # per candidate, per generation
    popsize: int = 12
    sigma0: float = 1.0     # multiplier on PARAM_STDS, not a distance in points
    seed: int = 1
    depth: int = 2
    workers: int = 18
    cap: int = 1000
    validate_every: int = 10
    validate_games: int = 500   # seeds; doubled by rotation
    hof_every: int = 5
    handset: str = "handset_v1"

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def validate(best_path: Path, cfg: TuneConfig, pool: mp.Pool, seed_base: int) -> dict:
    """Fresh games against fixed opponents — a yardstick the tuner never saw."""
    out = {}
    seeds = range(seed_base, seed_base + cfg.validate_games)
    for opponent in ("greedy", cfg.handset):
        tasks = [(0, ([str(best_path), opponent], 2, s, r, cfg.cap))
                 for s in seeds for r in (0, 1)]
        res = list(pool.imap_unordered(_run_task, tasks, chunksize=8))
        fit = score_generation(res, 1)[0]
        lo, hi = wilson(fit.win_rate * fit.games, fit.games)
        out[opponent] = {"win_rate": fit.win_rate, "ci": [lo, hi],
                         "mean_margin": fit.mean_margin, "games": fit.games}
    return out


def run(cfg: TuneConfig, run_dir: Path, resume: bool = False) -> None:
    import cma

    run_dir.mkdir(parents=True, exist_ok=True)
    cand_dir = run_dir / "candidates"
    cand_dir.mkdir(exist_ok=True)
    scales = Scales.load()
    state_path = run_dir / "state.pkl"

    if resume and state_path.exists():
        with open(state_path, "rb") as fh:
            saved = pickle.load(fh)
        es, start_gen, hof = saved["es"], saved["generation"], saved["hof"]
        print(f"resuming {run_dir.name} at generation {start_gen}")
    else:
        es = cma.CMAEvolutionStrategy(
            x0_from_handset(), cfg.sigma0,
            {"popsize": cfg.popsize, "seed": cfg.seed, "verbose": -9,
             # A per-coordinate step, so sigma0 is a multiplier on sensible
             # per-feature ranges rather than one distance for all of them.
             "CMA_stds": param_stds()})
        start_gen, hof = 0, []
        (run_dir / "config.json").write_text(json.dumps({
            "config": cfg.as_dict(),
            "param_keys": list(PARAM_KEYS),
            "anchor": ANCHOR,
            "x0": x0_from_handset(),
            "git_commit": git_commit(),
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, indent=2))

    n_seeds = max(1, cfg.games // 2)     # each seed is played in both seatings
    rng = random.Random(cfg.seed)
    pool = mp.Pool(processes=cfg.workers)
    t_start = time.perf_counter()

    try:
        for gen in range(start_gen, cfg.generations):
            t0 = time.perf_counter()
            xs = es.ask()

            specs = []
            for i, x in enumerate(xs):
                p = write_candidate(x, scales, cand_dir / f"g{gen:03d}_c{i:02d}.json",
                                    name=f"g{gen:03d}c{i:02d}", depth=cfg.depth,
                                    meta={"generation": gen, "candidate": i})
                specs.append(str(p))

            # Common random numbers: one seed list for the whole generation,
            # different each generation so nothing can be overfitted.
            base = rng.randrange(10_000_000)
            seeds = list(range(base, base + n_seeds))
            alloc = allocate(seeds, build_pool(cfg.handset, hof))
            tasks = generation_tasks(specs, alloc, cfg.cap)
            results = list(pool.imap_unordered(_run_task, tasks, chunksize=8))
            fits = score_generation(results, len(xs))

            es.tell(xs, [f.loss for f in fits])

            best_i = min(range(len(fits)), key=lambda i: fits[i].loss)
            best_x = list(xs[best_i])
            best_path = run_dir / "best.json"
            write_candidate(best_x, scales, best_path, name=f"tuned_g{gen:03d}",
                            depth=cfg.depth,
                            meta={"generation": gen,
                                  "win_rate": fits[best_i].win_rate,
                                  "mean_margin": fits[best_i].mean_margin})

            if (gen + 1) % cfg.hof_every == 0:
                hof_path = cand_dir / f"hof_g{gen:03d}.json"
                write_candidate(best_x, scales, hof_path, name=f"hof_g{gen:03d}",
                                depth=cfg.depth, meta={"generation": gen})
                hof.append(str(hof_path))
                hof[:] = hof[-4:]        # keep the last four

            elapsed = time.perf_counter() - t0
            values, lam = x_to_values(best_x)
            record = {
                "generation": gen,
                "elapsed_s": elapsed,
                "games": len(tasks),
                "sigma": float(es.sigma),
                "best_loss": fits[best_i].loss,
                "best_win_rate": fits[best_i].win_rate,
                "best_mean_margin": fits[best_i].mean_margin,
                "mean_loss": statistics.fmean(f.loss for f in fits),
                "best_values": values,
                "best_lambda": lam,
                "mean_x": [float(v) for v in es.result.xfavorite],
                "hof": list(hof),
            }

            if (gen + 1) % cfg.validate_every == 0:
                record["validation"] = validate(best_path, cfg, pool,
                                                seed_base=90_000_000 + gen * 10_000)

            (run_dir / f"gen_{gen:03d}.json").write_text(json.dumps(record, indent=2))
            with open(state_path, "wb") as fh:
                pickle.dump({"es": es, "generation": gen + 1, "hof": hof}, fh)

            total = time.perf_counter() - t_start
            done = gen - start_gen + 1
            eta = (cfg.generations - gen - 1) * (total / done)
            line = (f"gen {gen:3d}  win {fits[best_i].win_rate:5.1%}  "
                    f"margin {fits[best_i].mean_margin:+6.1f}  "
                    f"sigma {float(es.sigma):.3f}  "
                    f"{elapsed:5.1f}s  eta {eta / 60:5.1f}m")
            if "validation" in record:
                v = record["validation"]
                line += (f"   [validate: greedy {v['greedy']['win_rate']:.1%}"
                         f"  {cfg.handset} {v[cfg.handset]['win_rate']:.1%}]")
            print(line, flush=True)
    finally:
        pool.close()
        pool.join()

    print(f"\ndone. best weights: {run_dir / 'best.json'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--generations", type=int, default=50)
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--popsize", type=int, default=12)
    ap.add_argument("--sigma0", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--workers", type=int, default=18)
    ap.add_argument("--validate-every", type=int, default=10)
    ap.add_argument("--validate-games", type=int, default=500)
    ap.add_argument("--resume", default=None, metavar="RUN_DIR")
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args()

    if args.resume:
        run_dir = Path(args.resume)
        cfg_blob = json.loads((run_dir / "config.json").read_text())["config"]
        cfg = TuneConfig(**cfg_blob)
        cfg.generations = args.generations or cfg.generations
        run(cfg, run_dir, resume=True)
        return

    cfg = TuneConfig(generations=args.generations, games=args.games,
                     popsize=args.popsize, sigma0=args.sigma0, seed=args.seed,
                     depth=args.depth, workers=args.workers,
                     validate_every=args.validate_every,
                     validate_games=args.validate_games)
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run(cfg, TUNE_DIR / run_id)


if __name__ == "__main__":
    main()

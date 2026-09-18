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
from bots.features import CORE_FEATURES, WEIGHTS_DIR, Scales, Weights
from bots.make_handset import ANCHOR, LAMBDA, VALUE

TUNE_DIR = Path(__file__).resolve().parent.parent / "results" / "tune"

# --------------------------------------------------------------------------
# Step 9 archetypes
# --------------------------------------------------------------------------
# Three constrained bots, tuned separately, to find out whether Century has
# more than one viable way to play.
#
# `shaped_target` REPLACES `best_target` rather than joining it. They are the
# same quantity — shaped_target at alpha=beta=1 is numerically identical, and
# a test pins that — so swapping is lossless, while *adding* it was measured
# at 23.4% in the Step 7 screen because two copies of the points-over-distance
# term double the "promise" side of V and the bot stops claiming.
#
# This is the second chance the brief allows: Step 7 says keep a feature if it
# improves the win rate "or it enables an archetype in Step 9". shaped_target
# and golem_count both failed the win-rate test and are admitted here only as
# archetype machinery.
#
#   Rush      beta >= 2 punishes distance hard, so near golems dominate, and
#             golem_count is pinned high: take many cheap ones, end fast.
#   Big-card  alpha >= 1.5 rewards raw points superlinearly and golem_count is
#             pinned at 0: wait for the expensive golems, ignore the count.
#   Balanced  unconstrained, alpha = beta = 1 — i.e. the Step 6 bot.
ARCHETYPE_FEATURES: tuple[str, ...] = tuple(
    "shaped_target" if k == "best_target" else k for k in CORE_FEATURES
) + ("golem_count",)

ARCHETYPES: dict[str, dict] = {
    "rush": {"alpha": 1.0, "beta": 2.5, "fixed": {"golem_count": 1.5}},
    "bigcard": {"alpha": 1.6, "beta": 1.0, "fixed": {"golem_count": 0.0}},
    "balanced": {"alpha": 1.0, "beta": 1.0, "fixed": {}},
}

# Every feature except the anchor, in a fixed order.
PARAM_KEYS: tuple[str, ...] = tuple(k for k in CORE_FEATURES if k != ANCHOR)


def param_keys(features: Sequence[str] = CORE_FEATURES,
               fixed: Optional[dict] = None) -> tuple[str, ...]:
    """The coordinates CMA actually searches.

    Step 9 needs two departures from the core twelve: a different feature set
    (archetypes swap `best_target` for `shaped_target`, which is the same
    quantity with tunable exponents) and pinned parameters (an archetype is
    *defined* by holding one weight at a constraint while the rest adapt
    around it).
    """
    fixed = fixed or {}
    return tuple(k for k in features if k != ANCHOR and k not in fixed)

# Lambda is no longer searched. It never converged in three independent runs
# (-0.01, 0.89, 1.32) and an ablation at the averaged optimum showed removing
# it entirely is free: 50.2% CI [47.1, 53.3] against the baseline over 1000
# games. That is a fact about Century rather than about the tuner - the game
# has no blocking or direct interaction, so a bot loses nothing by ignoring
# its opponent and racing. Fixing it at 0 also drops a dimension from the
# search and skips the opponent's TTC during evaluation.
#
# It is kept as a constant rather than deleted so the opponent term can be
# switched back on if a later feature (Step 7's contested_target or denial)
# makes opponent modelling matter.
FIXED_LAMBDA = 0.0

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
    # Step 9 only. shaped_target replaces best_target in an archetype, so it
    # inherits its deliberately tight step; golem_count is a count like the
    # crystals and gets a comparable one.
    "shaped_target": 0.15,
    "golem_count": 0.30,
}
# Lambda's step, widened along with its clamp (see LAMBDA_MAX). Run 01
# walked it from 0.5 to 1.25 over 30 generations at a 0.20 step; if the real
# optimum is above 2, a step that small would not reach it inside a run.
LAMBDA_STD = 0.35

# How much the bot may care about the leading opponent relative to itself.
#
# Originally 1.5, on the reasoning that valuing an opponent's position above
# your own is absurd. Run 01 converged to 1.25 and was still climbing, which
# means the bound may have been binding a real preference rather than
# excluding a silly one — an invented constraint shaping the answer. Raised so
# the search can express a preference above 1.5 if the games actually support
# one. Zero remains the floor: negative lambda would mean helping the leader.
LAMBDA_MAX = 3.0


# --------------------------------------------------------------------------
# Parameter vector <-> weights file
# --------------------------------------------------------------------------

# Typical readings on the point row, used to undo the rescaling that alpha
# and beta apply to `shaped_target`. Both are measured: mean points per golem
# claimed is ~12.2 across arena runs, and median TTC is ~2 (API_NOTES §8.4).
REF_POINTS = 12.2
REF_TTC = 2.0


def shaped_seed_factor(alpha: float, beta: float) -> float:
    """How much to shrink a seeded `shaped_target` value for alpha/beta.

    THIS IS NOT COSMETIC. `shaped_target` is points^alpha / (1+TTC)^beta, and
    its scale was calibrated at alpha = beta = 1. Changing either exponent
    changes the feature's magnitude, so the calibrated divisor no longer
    normalises it and the seeded weight means something different.

    Measured: bigcard (alpha 1.6) inflates a typical golem ~4.4x, which starts
    the search deep in the regime where the points-over-distance term
    outprices actual points and the bot hoards. It scored 17-23% against a
    pool the balanced bot beats ~80% of the time, with sigma still 0.93 at
    generation 5 — not converging, just flailing. Rush (beta 2.5) has the
    mirror problem, shrinking values ~5x; milder, and it recovered, but it
    wasted generations climbing back.

    CMA could eventually absorb this into the weight, but starting a
    constrained search from a knowingly wrong point wastes most of its budget
    and makes the archetypes incomparable.
    """
    return (REF_POINTS ** (1.0 - alpha)) * ((1.0 + REF_TTC) ** (beta - 1.0))


def base_values(source: Optional[str] = None,
                keys: Sequence[str] = PARAM_KEYS,
                alpha: float = 1.0, beta: float = 1.0) -> dict[str, float]:
    """Starting point: the hand-set intent, or a weights file's own intent.

    A key the source does not carry falls back to the hand-set value, which is
    what lets an archetype seed `shaped_target` from `best_target`'s tuned
    value — they are the same quantity at alpha = beta = 1, and corrected by
    `shaped_seed_factor` when they are not.
    """
    fallback = {**VALUE, "shaped_target": VALUE["best_target"], "golem_count": 0.3}
    if source is None:
        return {k: fallback[k] for k in keys}
    path = Path(source)
    blob = json.loads(path.read_text()) if path.exists() else         json.loads((WEIGHTS_DIR / f"{source}.json").read_text())
    got = blob["meta"]["value_in_points"]
    out = {}
    for k in keys:
        if k in got:
            out[k] = float(got[k])
        elif k == "shaped_target" and "best_target" in got:
            out[k] = float(got["best_target"])
        else:
            out[k] = fallback[k]
    if "shaped_target" in out and (alpha != 1.0 or beta != 1.0):
        out["shaped_target"] *= shaped_seed_factor(alpha, beta)
    return out


def x0_from(source: Optional[str] = None, split: bool = False,
            keys: Sequence[str] = PARAM_KEYS,
            alpha: float = 1.0, beta: float = 1.0) -> list[float]:
    """Parameter vector. Phase-split doubles it: early values then late."""
    base = base_values(source, keys, alpha, beta)
    v = [base[k] for k in keys]
    return v + v if split else v


def param_stds(split: bool = False,
               keys: Sequence[str] = PARAM_KEYS) -> list[float]:
    """Initial search step per coordinate — see PARAM_STDS."""
    v = [PARAM_STDS[k] for k in keys]
    return v + v if split else v


def x_to_values(x: Sequence[float], keys: Sequence[str] = PARAM_KEYS,
                fixed: Optional[dict] = None
                ) -> tuple[dict[str, float], dict[str, float]]:
    """-> (early values, late values). Identical unless the run is split.

    `fixed` holds the archetype constraints, merged in after the searched
    coordinates so a pinned weight cannot drift.
    """
    keys = list(keys)
    n = len(keys)
    base = {ANCHOR: 1.0, **(fixed or {})}
    early = dict(base)
    for k, v in zip(keys, x[:n]):
        early[k] = float(v)
    if len(x) < 2 * n:
        return early, dict(early)
    late = dict(base)
    for k, v in zip(keys, x[n:2 * n]):
        late[k] = float(v)
    return early, late


def write_candidate(x: Sequence[float], scales: Scales, path: Path,
                    name: str, depth: int, meta: Optional[dict] = None,
                    lam: float = FIXED_LAMBDA,
                    features: Sequence[str] = CORE_FEATURES,
                    fixed: Optional[dict] = None,
                    alpha: float = 1.0, beta: float = 1.0) -> Path:
    """Materialise a parameter vector as a weights file a worker can load."""
    keys = param_keys(features, fixed)
    early, late = x_to_values(x, keys, fixed)
    anchor_scale = scales.get(ANCHOR)

    def to_w(values):
        return {k: values.get(k, 0.0) * scales.get(k) / anchor_scale
                for k in features}

    blob = Weights(
        name=name,
        features=list(features),
        w_early=to_w(early),
        w_late=to_w(late),
        lam=min(LAMBDA_MAX, max(0.0, lam)),
        params={"ttc_depth": depth, "alpha": alpha, "beta": beta},
        meta={"source": "cma", "value_in_points": early,
              "value_in_points_late": late,
              "phase_split": early != late,
              "fixed": dict(fixed or {}), **(meta or {})},
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
    # The fitness pool's handset opponent runs at the CANDIDATES' depth, so a
    # candidate is judged against the same brain it has. handset_v1 ships at
    # ttc_depth=3; leaving it there made 45% of every generation's games pay
    # the slow path (12.2 games/s at depth 2 against 5.4 at depth 3) and gave
    # the benchmark a deeper search than the bots being scored. Measured: 527s
    # for generation 0, a 7.2-hour projection for 50 generations.
    split: bool = False         # 6b: separate early-game and late-game weights
    start_from: Optional[str] = None   # weights file to seed x0 from
    # --- Step 9 archetypes ---------------------------------------------
    # `features` lets an archetype swap best_target for shaped_target;
    # `fixed` pins the weights that define the archetype; alpha/beta shape
    # the points-versus-distance trade-off that Rush and Big-card differ on.
    features: tuple = CORE_FEATURES
    fixed: dict = field(default_factory=dict)
    alpha: float = 1.0
    beta: float = 1.0
    pool_handset: str = "depth2"
    # Validation is against the Step 4 artefact exactly as it ships, so the
    # number stays comparable to the 90.8% recorded in API_NOTES §11.
    validate_handset: str = "handset_v1"

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def validate(best_path: Path, cfg: TuneConfig, pool: mp.Pool, seed_base: int) -> dict:
    """Fresh games against fixed opponents — a yardstick the tuner never saw.

    Point this at the distribution CENTRE, never at the best sample. The best
    sample is the luckiest of `popsize` noisy draws and can sit far from the
    mean: run 02's generation-10 best had cry_b 1.18 and cry_m 1.64 against
    its own mean of 0.71 and 0.80. Validating samples made run 01 and run 02
    look 23 points apart (79.0% against 55.6% vs handset_v1) when their means
    are statistically indistinguishable (78.2% [75.5, 80.6] against 75.2%
    [71.6, 78.5]). That very nearly got recorded as "tuning is not
    reproducible".
    """
    out = {}
    seeds = range(seed_base, seed_base + cfg.validate_games)
    for opponent in ("greedy", cfg.validate_handset):
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
        keys = param_keys(cfg.features, cfg.fixed)
        print(f"resuming {run_dir.name} at generation {start_gen}")
    else:
        keys = param_keys(cfg.features, cfg.fixed)
        es = cma.CMAEvolutionStrategy(
            x0_from(cfg.start_from, cfg.split, keys, cfg.alpha, cfg.beta),
            cfg.sigma0,
            {"popsize": cfg.popsize, "seed": cfg.seed, "verbose": -9,
             # A per-coordinate step, so sigma0 is a multiplier on sensible
             # per-feature ranges rather than one distance for all of them.
             "CMA_stds": param_stds(cfg.split, keys)})
        start_gen, hof = 0, []
        (run_dir / "config.json").write_text(json.dumps({
            "config": cfg.as_dict(),
            "param_keys": list(PARAM_KEYS),
            "anchor": ANCHOR,
            "x0": x0_from(cfg.start_from, cfg.split, keys, cfg.alpha, cfg.beta),
            "param_keys_used": list(keys),
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
                                    meta={"generation": gen, "candidate": i},
                                    features=cfg.features, fixed=cfg.fixed,
                                    alpha=cfg.alpha, beta=cfg.beta)
                specs.append(str(p))

            # Common random numbers: one seed list for the whole generation,
            # different each generation so nothing can be overfitted.
            base = rng.randrange(10_000_000)
            seeds = list(range(base, base + n_seeds))
            alloc = allocate(seeds, build_pool(cfg.pool_handset, hof))
            tasks = generation_tasks(specs, alloc, cfg.cap)
            results = list(pool.imap_unordered(_run_task, tasks, chunksize=8))
            fits = score_generation(results, len(xs))

            es.tell(xs, [f.loss for f in fits])

            best_i = min(range(len(fits)), key=lambda i: fits[i].loss)
            best_x = list(xs[best_i])
            write_candidate(best_x, scales, run_dir / "best.json",
                            name=f"tuned_g{gen:03d}",
                            depth=cfg.depth,
                            meta={"generation": gen,
                                  "win_rate": fits[best_i].win_rate,
                                  "mean_margin": fits[best_i].mean_margin},
                            features=cfg.features, fixed=cfg.fixed,
                            alpha=cfg.alpha, beta=cfg.beta)

            # The estimate of the optimum, and the thing worth shipping and
            # validating — see validate(). `best.json` is kept alongside it
            # only for comparison.
            mean_x = [float(v) for v in es.result.xfavorite]
            mean_path = run_dir / "mean.json"
            write_candidate(mean_x, scales, mean_path, name=f"mean_g{gen:03d}",
                            depth=cfg.depth, meta={"generation": gen},
                            features=cfg.features, fixed=cfg.fixed,
                            alpha=cfg.alpha, beta=cfg.beta)

            if (gen + 1) % cfg.hof_every == 0:
                hof_path = cand_dir / f"hof_g{gen:03d}.json"
                write_candidate(best_x, scales, hof_path, name=f"hof_g{gen:03d}",
                                depth=cfg.depth, meta={"generation": gen})
                hof.append(str(hof_path))
                hof[:] = hof[-4:]        # keep the last four

            elapsed = time.perf_counter() - t0
            early_v, late_v = x_to_values(best_x, keys, cfg.fixed)
            record = {
                "generation": gen,
                "elapsed_s": elapsed,
                "games": len(tasks),
                "sigma": float(es.sigma),
                "best_loss": fits[best_i].loss,
                "best_win_rate": fits[best_i].win_rate,
                "best_mean_margin": fits[best_i].mean_margin,
                "mean_loss": statistics.fmean(f.loss for f in fits),
                "best_values": early_v,
                "best_values_late": late_v,
                "phase_split": cfg.split,
                "mean_x": [float(v) for v in es.result.xfavorite],
                "hof": list(hof),
            }

            if (gen + 1) % cfg.validate_every == 0:
                record["validation"] = validate(mean_path, cfg, pool,
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
                         f"  {cfg.validate_handset} "
                         f"{v[cfg.validate_handset]['win_rate']:.1%}]")
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
    ap.add_argument("--archetype", choices=sorted(ARCHETYPES),
                    help="Step 9: tune a constrained archetype")
    ap.add_argument("--split", action="store_true",
                    help="6b: tune separate early-game and late-game weights")
    ap.add_argument("--start-from", default=None,
                    help="weights file to seed x0 from (default: hand-set)")
    ap.add_argument("--pool-handset", default="depth2",
                    help="handset opponent in the fitness pool; should match "
                         "the candidates' ttc_depth")
    ap.add_argument("--validate-handset", default="handset_v1",
                    help="handset opponent for validation; the shipped artefact")
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

    extra = {}
    if args.archetype:
        a = ARCHETYPES[args.archetype]
        extra = {"features": ARCHETYPE_FEATURES, "fixed": a["fixed"],
                 "alpha": a["alpha"], "beta": a["beta"]}
    cfg = TuneConfig(generations=args.generations, games=args.games,
                     popsize=args.popsize, sigma0=args.sigma0, seed=args.seed,
                     depth=args.depth, workers=args.workers,
                     validate_every=args.validate_every,
                     validate_games=args.validate_games,
                     split=args.split, start_from=args.start_from,
                     pool_handset=args.pool_handset,
                     validate_handset=args.validate_handset, **extra)
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run(cfg, TUNE_DIR / run_id)


if __name__ == "__main__":
    main()

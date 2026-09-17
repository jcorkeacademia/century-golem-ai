"""Cheap first pass over candidate features, before anything gets retuned.

    python -m bots.screen --base tuned_split --games 1000 --workers 18

WHY SCREEN AT ALL

The brief's protocol per feature is: add it, retune from the current best,
validate. That is ~35 minutes each, so all 18 candidates is most of a day. A
lot of that budget would be spent retuning features that turn out to do
nothing at any weight.

So: bolt the feature onto the already-tuned weights at a few fixed values,
play it against the same weights without it, and only spend the retune on
candidates that show a pulse. A feature that cannot help when simply added is
unlikely to become useful once the other weights shift — and if it does, the
full ablation in Step 10 catches it.

HOW THE SWEEP VALUES ARE CHOSEN

A raw weight is meaningless across features (that is the whole scale problem),
so the sweep is defined by *contribution*: how much the feature adds to V in a
position where it reads near its 95th percentile. `golem_points` contributes
about 3.2 there, so a contribution of 1.0 is a large-but-not-absurd voice, and
0.3 is a tiebreaker. Both signs are tried, because for several candidates
(`overflow_waste`, `snipe_risk`, `row_bounty`) the useful direction is
negative and guessing wrong would read as "no effect".

    contribution at ref = w * ref / scale   =>   w = c * scale / ref

`ref` is the p95, or the std when p95 is zero — which happens for the three
features that fire in under 5% of positions.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from bots.arena import _play_one, git_commit, wilson
from bots.features import FEATURES, SCREEN_ORDER, WEIGHTS_DIR, Scales, Weights
from bots.tune import _run_task, score_generation

RESULTS = Path(__file__).resolve().parent.parent / "results" / "screen"

# Contributions to try, in V units, at a position where the feature reads p95.
SWEEP = (-1.0, -0.3, 0.3, 1.0)


def weight_for(key: str, contribution: float, scales: Scales) -> float:
    d = scales.diagnostics.get(key, {})
    ref = abs(d.get("p95", 0.0)) or abs(d.get("std", 0.0)) or 1.0
    return contribution * scales.get(key) / ref


def make_variant(base: Weights, key: str, contribution: float,
                 scales: Scales, path: Path) -> Path:
    """Base weights plus one feature, at a fixed weight in both phases."""
    w = weight_for(key, contribution, scales)
    early = dict(base.w_early)
    late = dict(base.w_late)
    early[key] = w
    late[key] = w
    out = Weights(
        name=f"{base.name}+{key}@{contribution:+.1f}",
        features=list(base.features) + [key],
        w_early=early, w_late=late, lam=base.lam,
        params=dict(base.params),
        meta={**base.meta, "screen_feature": key,
              "screen_contribution": contribution, "screen_weight": w},
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    out.save(path)
    return path


def head_to_head(variant: str, base: str, seeds: Sequence[int],
                 pool: mp.Pool, cap: int = 1000) -> dict:
    tasks = [(0, ([variant, base], 2, s, r, cap)) for s in seeds for r in (0, 1)]
    res = list(pool.imap_unordered(_run_task, tasks, chunksize=8))
    fit = score_generation(res, 1)[0]
    lo, hi = wilson(fit.win_rate * fit.games, fit.games)
    return {"win_rate": fit.win_rate, "ci": [lo, hi],
            "mean_margin": fit.mean_margin, "games": fit.games}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="tuned_split")
    ap.add_argument("--games", type=int, default=1000,
                    help="seeds per variant; doubled by seat rotation")
    ap.add_argument("--workers", type=int, default=18)
    ap.add_argument("--seed-base", type=int, default=8_000_000)
    ap.add_argument("--only", nargs="*", default=None,
                    help="screen just these features")
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args()

    scales = Scales.load()
    base = Weights.load(args.base)
    base_path = str((WEIGHTS_DIR / f"{args.base}.json").resolve())
    keys = list(args.only) if args.only else list(SCREEN_ORDER)
    missing = [k for k in keys if k not in scales.values]
    if missing:
        raise SystemExit(f"no scale for {missing} — run "
                         f"`python -m bots.calibrate --features new --merge`")

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = RESULTS / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    seeds = list(range(args.seed_base, args.seed_base + args.games))

    print(f"screening {len(keys)} feature(s) against {args.base}, "
          f"{args.games * 2} games per variant, {len(SWEEP)} weights each")
    print(f"{'feature':<18}{'contrib':>9}{'win rate':>10}{'95% CI':>18}{'margin':>9}")
    print("-" * 66)

    pool = mp.Pool(processes=args.workers)
    records = []
    t0 = time.perf_counter()
    try:
        for key in keys:
            best = None
            for c in SWEEP:
                p = make_variant(base, key, c, scales,
                                 out_dir / "variants" / f"{key}{c:+.1f}.json")
                r = head_to_head(str(p), base_path, seeds, pool)
                r.update(feature=key, contribution=c,
                         weight=weight_for(key, c, scales))
                records.append(r)
                lo, hi = r["ci"]
                flag = "  <-- beats base" if lo > 0.5 else ""
                print(f"{key:<18}{c:>+9.1f}{r['win_rate']:>9.1%}"
                      f"{f'[{lo:.1%}, {hi:.1%}]':>18}{r['mean_margin']:>+9.1f}{flag}")
                if best is None or r["win_rate"] > best["win_rate"]:
                    best = r
            (out_dir / "results.json").write_text(json.dumps(
                {"base": args.base, "games_per_variant": args.games * 2,
                 "sweep": list(SWEEP), "git_commit": git_commit(),
                 "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "records": records}, indent=2))
            print(f"{'':<18}{'best:':>9}{best['win_rate']:>9.1%}  "
                  f"at contribution {best['contribution']:+.1f}")
    finally:
        pool.close()
        pool.join()

    el = time.perf_counter() - t0
    survivors = sorted({r["feature"] for r in records if r["ci"][0] > 0.5})
    print(f"\n{el / 60:.1f} min. Survivors (lower CI above 50%): "
          f"{', '.join(survivors) if survivors else 'none'}")
    print(f"wrote {out_dir / 'results.json'}")


if __name__ == "__main__":
    main()

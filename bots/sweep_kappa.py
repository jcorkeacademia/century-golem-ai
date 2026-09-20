"""Pick the cost deduction for `best_target` (features.net_points).

    python -u -m bots.sweep_kappa --seeds 400 --workers 18

Every variant plays the shipped bot head to head, seats rotated. Two arms:

  kappa=K   the fix: price a target at points - K * YE(cost).
  scale=F   the control: leave the feature gross and multiply its weight by
            F instead.

The control is the point of the exercise. Deducting a cost also shrinks the
feature, so a kappa that wins could be winning only because best_target now
counts for less. If the two arms peak at the same height, that is all this
was; if kappa peaks higher, the ranking change - cheap golems rising above
expensive ones - is doing real work.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import time
from datetime import datetime, timezone
from pathlib import Path

from bots.arena import git_commit, wilson
from bots.features import WEIGHTS_DIR, Weights
from bots.tune import _run_task, score_generation

RESULTS = Path(__file__).resolve().parent.parent / "results"


def variant(base: Weights, out: Path, *, kappa: float = 0.0,
            bt_scale: float = 1.0) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    early, late = dict(base.w_early), dict(base.w_late)
    early["best_target"] *= bt_scale
    late["best_target"] *= bt_scale
    params = dict(base.params)
    params["kappa"] = kappa
    Weights(name=out.stem, features=list(base.features), w_early=early,
            w_late=late, lam=base.lam, params=params,
            meta={**base.meta, "variant": out.stem}).save(out)
    return str(out.resolve())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="tuned_split")
    ap.add_argument("--seeds", type=int, default=400)
    ap.add_argument("--seed-base", type=int, default=31_000_000)
    ap.add_argument("--workers", type=int, default=18)
    ap.add_argument("--kappas", type=float, nargs="*",
                    default=[0.10, 0.20, 0.30, 0.45, 0.60])
    ap.add_argument("--scales", type=float, nargs="*",
                    default=[0.80, 0.60, 0.40])
    args = ap.parse_args()

    base = Weights.load(args.base)
    base_path = str((WEIGHTS_DIR / f"{args.base}.json").resolve())
    out_dir = RESULTS / "kappa" / "variants"
    seeds = range(args.seed_base, args.seed_base + args.seeds)

    arms = [("kappa", k, variant(base, out_dir / f"kappa_{k:.2f}.json", kappa=k))
            for k in args.kappas]
    arms += [("scale", f, variant(base, out_dir / f"scale_{f:.2f}.json", bt_scale=f))
             for f in args.scales]

    print(f"{len(arms)} variants x {args.seeds * 2} games vs {args.base}", flush=True)
    pool = mp.Pool(processes=args.workers)
    rows = []
    t0 = time.perf_counter()
    try:
        for arm, val, path in arms:
            tasks = [(0, ([path, base_path], 2, s, r, 1000))
                     for s in seeds for r in (0, 1)]
            res = list(pool.imap_unordered(_run_task, tasks, chunksize=8))
            fit = score_generation(res, 1)[0]
            lo, hi = wilson(fit.win_rate * fit.games, fit.games)
            rows.append({"arm": arm, "value": val, "win_rate": fit.win_rate,
                         "ci": [lo, hi], "mean_margin": fit.mean_margin,
                         "games": fit.games})
            print(f"  {arm}={val:<6.2f}{fit.win_rate:>7.1%}  [{lo:.1%}, {hi:.1%}]"
                  f"  margin {fit.mean_margin:+6.2f}", flush=True)
    finally:
        pool.close()
        pool.join()

    blob = {"base": args.base, "games_per_variant": args.seeds * 2,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "git_commit": git_commit(), "rows": rows}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "kappa_sweep.json").write_text(json.dumps(blob, indent=2))
    print(f"\nwrote {RESULTS / 'kappa_sweep.json'}  ({time.perf_counter() - t0:.0f}s)")


if __name__ == "__main__":
    main()

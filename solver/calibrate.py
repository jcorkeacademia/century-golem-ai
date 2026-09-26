"""Which side of the bracket is loose? Calibrate on games small enough to prove.

The full game's bracket is ~14 turns wide and we cannot tell whether the
truth sits near the lower bound or the upper. So play the SAME seeds with a
smaller goal — 2, 3, 4 golems instead of 6 — where dfbb can sometimes prove
the true optimum from the opening, and measure each bound's distance from it:

    h, flow    lower bounds (admissible), under the lowered goal
    beam       the beam search's plan, width 1000 (an upper bound)
    truth      dfbb from the opening, started at the beam's plan, on a time
               budget. If it finishes, `truth` is proven; if not, it is only
               the best found, and the row says so.

If the beam sits on the truth while the bounds sit well below it, the full
game's gap is mostly a weak lower bound; if the reverse, a weak upper bound.

Caveat: the proof uses the yellow/green payment rule (search.cheap_payments),
evidence-backed but unproven. The lower bounds hold for every move, so
`truth - lower` is if anything slightly overstated; the beam uses the same
rule as the proof, so `beam - truth` is like for like.

    python -m solver.calibrate [seeds] [seconds per proof]
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from solver.bound import h
from solver.flow import flow_bound
from solver.improve import beam
from solver.search import OutOfBudget, Stats, cheap_payments, claims_first, dfbb
from solver.solo import new_solo_game

TARGETS = (2, 3, 4)
OUT = Path(__file__).resolve().parent.parent / "results"


def calibrate(seed: int, seconds: float = 600, width: int = 1000) -> list[dict]:
    rows = []
    for target in TARGETS:
        game = new_solo_game(seed=seed)
        game.win_target = target
        row = {"seed": seed, "target": target,
               "h": h(game), "flow": flow_bound(game)}
        plan = beam(seed, width, target=target)
        row["beam"] = plan.turns
        best = {"turns": plan.turns, "actions": plan.actions}
        stats = Stats()
        try:
            dfbb(game, 0, [], best, stats, None, time.perf_counter() + seconds,
                 moves=cheap_payments, seen={}, ordering=claims_first)
            row["proven"] = True
        except OutOfBudget:
            row["proven"] = False
        row["best"] = best["turns"]
        row["nodes"] = stats.nodes
        row["seconds"] = round(stats.elapsed())
        rows.append(row)
        if not row["proven"]:
            break                      # a bigger goal will not prove either
    return rows


def _write(rows: list[dict], seconds: float) -> None:
    (OUT / "solver_calibration.json").write_text(
        json.dumps({"seconds_per_proof": seconds, "rows": rows}, indent=1),
        encoding="utf-8")
    lines = [
        "# Calibrating the bracket on smaller goals",
        "",
        "Same seeds, goal lowered to 2-4 golems, where the true optimum can be",
        f"proven from the opening (dfbb, {seconds:.0f}s budget per case). `truth` is",
        "proven where marked; otherwise it is only the best plan found.",
        "",
        "| seed | golems | h | flow | beam | truth | proven | h gap | flow gap | beam gap |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        t = r["best"]
        lines.append(
            f"| {r['seed']} | {r['target']} | {r['h']} | {r['flow']} | {r['beam']} | "
            f"{t} | {'yes' if r['proven'] else 'no'} | {t - r['h']} | "
            f"{t - r['flow']} | {r['beam'] - t} |")
    for target in TARGETS:
        proven = [r for r in rows if r["target"] == target and r["proven"]]
        if proven:
            n = len(proven)
            lines.append("")
            lines.append(
                f"{target} golems, {n} proven: mean truth - h "
                f"{sum(r['best'] - r['h'] for r in proven) / n:.1f}, truth - flow "
                f"{sum(r['best'] - r['flow'] for r in proven) / n:.1f}, beam - truth "
                f"{sum(r['beam'] - r['best'] for r in proven) / n:.1f}.")
    (OUT / "solver_calibration.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover - manual run
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 600
    t = time.time()
    with ProcessPoolExecutor(max_workers=min(n, 10)) as pool:
        rows = [r for rs in pool.map(calibrate, range(n), [seconds] * n) for r in rs]
    _write(rows, seconds)
    for r in rows:
        print(f"seed {r['seed']} goal {r['target']}: h {r['h']} flow {r['flow']} "
              f"beam {r['beam']} truth {r['best']}{'' if r['proven'] else '?'} "
              f"({r['nodes']:,} nodes, {r['seconds']}s)")
    print(f"wrote results/solver_calibration.md  ({time.time() - t:.0f}s wall)")

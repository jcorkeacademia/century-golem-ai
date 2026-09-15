"""Measure each feature's spread, so weights become comparable.

`python -m bots.calibrate [--games 200] [--players 2]`

Writes `bots/weights/feature_scales.json`: a divisor per feature, plus the
distribution it came from. Weights are then interpretable against each other —
"magenta is worth 3.4 yellows" only means something once both are normalised.

THE SCALE TRAP. The brief says `scale = max(std, 1e-6)`. That floor protects
against nothing: a feature that barely varies gets a small std, and dividing
by it multiplies that feature's influence. A binary feature true 2% of the
time has std ~0.14, so a raw value of 1 normalises to ~7 — bigger than a
90-point golem haul divided by its own std. CMA-ES would compensate by
learning a smaller weight, but hand-set weights would be badly misleading.

So this script keeps the brief's formula and adds the diagnostic that
actually matters: `norm p95` = p95 / scale, i.e. what a weight of 1.0 buys
from that feature in a strong position. Features in the same band are
comparable; anything outside it is flagged rather than shipped silently.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone

from bots._engine import Acquire, Claim, Game, PlayCrystal, PlayTrade, PlayUpgrade, Rest
from bots import sim
from bots.features import CORE_FEATURES, Ctx, FEATURES, SCALES_PATH, DEFAULT_TTC_DEPTH
from bots.sim import can_pay, cost_of, shortfall

# What matters is not std on its own but the *normalised* magnitude: p95/std
# is roughly what a weight of 1.0 buys you from this feature in a typical
# strong position. If every feature lands in the same band, normalisation is
# doing its job and hand-set weights mean the same thing everywhere. A feature
# far outside the band silently dominates or vanishes.
NORM_P95_BAND = (1.5, 6.0)
DEGENERATE_STD = 0.05


class TempGreedyBot:
    """A stand-in until Step 4 builds the real GreedyBot.

    Deliberately simple and rule-based — its only job is to generate positions
    that look like real play rather than the nonsense random play produces
    (which empties the merchant row and never claims anything). Calibration
    scales depend on how the sampling bot plays, so these must be recomputed
    once the real GreedyBot exists.
    """

    def __init__(self, rng: random.Random):
        self.rng = rng

    def choose(self, game: Game):
        acts = game.legal_actions(pruned=True)
        if not acts:
            return None
        me = game.players[game.current]

        # 1. claim the best golem available, preferring the token slots
        claims = [a for a in acts if isinstance(a, Claim)]
        if claims:
            return max(claims, key=lambda a: (
                game.point_row[a.row_index].points + (3 if a.row_index == 0 else
                                                      1 if a.row_index == 1 else 0),
                -a.row_index))

        # 2. the play that most reduces the shortfall to the best target
        target = self._best_target(game, me)
        plays = [a for a in acts if isinstance(a, (PlayCrystal, PlayTrade, PlayUpgrade))]
        if target is not None and plays:
            base = shortfall(me.caravan, target)
            best, best_gain = None, 0
            for a in plays:
                c = game.clone()
                c.apply_action(a, validate=False)
                gain = base - shortfall(c.players[game.current].caravan, target)
                if gain > best_gain:
                    best, best_gain = a, gain
            if best is not None:
                return best

        # 3. rest if nothing in hand does anything
        rests = [a for a in acts if isinstance(a, Rest)]
        if not plays and rests:
            return rests[0]

        # 4. take a cheap merchant card
        acqs = [a for a in acts if isinstance(a, Acquire) and a.row_index <= 2]
        if acqs and self.rng.random() < 0.6:
            return min(acqs, key=lambda a: a.row_index)

        if plays:
            return self.rng.choice(plays)
        if rests:
            return rests[0]
        return self.rng.choice(acts)

    @staticmethod
    def _best_target(game: Game, me):
        best, best_v = None, -1.0
        for pc in game.point_row:
            if pc is None:
                continue
            cost = cost_of(pc)
            v = pc.points / (1.0 + shortfall(me.caravan, cost))
            if v > best_v:
                best, best_v = cost, v
        return best


def run(n_games: int, n_players: int, depth: int, seed: int, cap: int = 1200):
    samples: dict[str, list[float]] = defaultdict(list)
    lengths, finished = [], 0
    t0 = time.perf_counter()

    for gi in range(n_games):
        rng = random.Random(seed + gi)
        bot = TempGreedyBot(rng)
        g = Game([f"P{i}" for i in range(n_players)], seed=seed + gi)
        steps = 0
        while not g.game_over and steps < cap:
            action = bot.choose(g)
            if action is None:
                break
            before = g.clone()
            g.apply_action(action)
            steps += 1
            # Record the resulting position from the acting seat's view.
            pid = before.current
            ctx = Ctx(g, depth)
            for key in CORE_FEATURES:
                samples[key].append(FEATURES[key].fn(before, g, pid, ctx))
        lengths.append(steps)
        finished += g.game_over
        if gi % 25 == 0:
            sim.clear_cache()

    elapsed = time.perf_counter() - t0
    return samples, lengths, finished, elapsed


def summarise(samples):
    scales, diags, flagged = {}, {}, []
    for key in CORE_FEATURES:
        xs = samples[key]
        std = statistics.pstdev(xs) if len(xs) > 1 else 0.0
        scale = max(std, 1e-6)
        scales[key] = scale
        srt = sorted(xs)
        diags[key] = {
            "mean": statistics.fmean(xs),
            "std": std,
            "min": srt[0],
            "p05": srt[int(len(srt) * 0.05)],
            "p50": srt[len(srt) // 2],
            "p95": srt[int(len(srt) * 0.95)],
            "max": srt[-1],
            "zero_fraction": sum(1 for x in xs if x == 0.0) / len(xs),
            "n": len(xs),
        }
        # What a weight of 1.0 buys from this feature in a strong position.
        diags[key]["norm_p95"] = abs(diags[key]["p95"]) / scale
        if std < DEGENERATE_STD or not (
                NORM_P95_BAND[0] <= diags[key]["norm_p95"] <= NORM_P95_BAND[1]):
            flagged.append(key)
    return scales, diags, flagged


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--players", type=int, default=2)
    ap.add_argument("--depth", type=int, default=DEFAULT_TTC_DEPTH)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--out", default=str(SCALES_PATH))
    args = ap.parse_args()

    print(f"calibrating on {args.games} TempGreedyBot self-play games "
          f"({args.players}p, ttc_depth={args.depth}) ...")
    samples, lengths, finished, elapsed = run(args.games, args.players, args.depth, args.seed)
    scales, diags, flagged = summarise(samples)

    n = len(samples[CORE_FEATURES[0]])
    print(f"  {finished}/{args.games} games finished, "
          f"mean {statistics.fmean(lengths):.0f} actions, "
          f"{n:,} feature observations in {elapsed:.1f}s\n")

    hdr = (f"  {'feature':<14}{'mean':>8}{'std':>8}{'p50':>7}{'p95':>8}{'max':>7}"
           f"{'zero%':>7}{'norm p95':>10}")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for key in CORE_FEATURES:
        d = diags[key]
        mark = "  <--" if key in flagged else ""
        print(f"  {key:<14}{d['mean']:>8.2f}{d['std']:>8.2f}{d['p50']:>7.1f}"
              f"{d['p95']:>8.1f}{d['max']:>7.1f}{d['zero_fraction']*100:>6.0f}%"
              f"{d['norm_p95']:>10.2f}{mark}")
    print()
    print("  'norm p95' is what a weight of 1.0 buys from that feature in a strong")
    print("  position. Comparable numbers mean normalisation is doing its job and a")
    print("  weight means roughly the same thing across features.")

    if flagged:
        print(f"\n  WARNING: {len(flagged)} feature(s) outside the normalised band "
              f"{NORM_P95_BAND}:")
        for key in flagged:
            d = diags[key]
            why = ("near-constant" if d["std"] < DEGENERATE_STD
                   else "dominates" if d["norm_p95"] > NORM_P95_BAND[1] else "vanishes")
            print(f"    {key:<14} std {d['std']:.3f}  norm p95 {d['norm_p95']:.2f}  ({why})")
        print("  CMA-ES compensates by learning a different weight, so this does not")
        print("  break tuning — but hand-set weights for these features do not mean")
        print("  what they appear to mean. Adjust them accordingly.")
    else:
        print(f"\n  All {len(CORE_FEATURES)} features sit inside the band "
              f"{NORM_P95_BAND}, so hand-set weights are directly comparable.")

    blob = {
        "scales": scales,
        "diagnostics": diags,
        "meta": {
            "games": args.games, "players": args.players, "ttc_depth": args.depth,
            "seed": args.seed, "sampler": "TempGreedyBot",
            "observations": n, "finished": finished,
            "mean_game_length": statistics.fmean(lengths),
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "note": "Scales depend on the sampling policy. Recompute after "
                    "Step 4 replaces TempGreedyBot with the real GreedyBot.",
        },
    }
    with open(args.out, "w") as fh:
        json.dump(blob, fh, indent=2)
    print(f"\n  wrote {args.out}")


if __name__ == "__main__":
    main()

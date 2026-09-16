"""Generate hand-set weights from intent expressed in points.

    python -m bots.make_handset [--out bots/weights/handset_v1.json]

WHY NOT JUST TYPE THE WEIGHTS

A weight is not what it looks like. Every feature is divided by its own scale
before being weighted, so the influence of `w` depends on that feature's
spread. `throughput` has a scale of ~0.28 and `golem_points` ~18.7 — a weight
of 1.0 on throughput contributes roughly 9 units to V, while a weight of 1.0
on golem_points contributes about 3. Typing "0.5" for both does not mean what
it appears to mean, and hand-set weights chosen that way are indefensible.

So intent is written in a unit that *is* meaningful:

    VALUE[feature] = how many victory points one raw unit of this feature
                     is worth to me

One magenta crystal is worth 1 point at the end of the game, plus something
for the golems it unlocks — call it 1.4. One `dead_hand` (a wasted turn) costs
maybe 3. Those are claims a person can argue with, which is the whole point.

The conversion falls out of wanting equal value to give equal contribution:

    contribution = w * raw / scale
    w = VALUE * scale / scale[golem_points]        (with w[golem_points] = 1)

Re-run this after every recalibration. The weights change; the intent does not.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from bots.features import CORE_FEATURES, DEFAULT_TTC_DEPTH, SCALES_PATH, Scales, Weights

ANCHOR = "golem_points"

# Victory points per raw unit of each feature. Argue with these numbers, not
# with the weights they produce.
VALUE: dict[str, float] = {
    # --- things that already are points -------------------------------
    "golem_points": 1.0,     # by definition; the anchor
    "token_points": 1.0,     # a point is a point

    # --- crystals: endgame value only ---------------------------------
    # Deliberately NOT "value plus a premium for the golems they unlock".
    # That premium is already counted by best_target: you are holding four
    # blue *because* you are aiming at a blue golem, and pricing both means
    # paying twice for one fact. Double-counted, the pair made claiming an
    # 11-point golem cost about 10.6 points of forfeited promise to gain 11 —
    # so the bot hoarded. These are the endgame numbers and nothing more:
    # yellow scores 0, everything else scores 1, with a small slope up the
    # chain because higher crystals are harder to replace.
    "cry_y": 0.05,
    "cry_g": 0.25,
    "cry_b": 0.40,
    "cry_m": 0.55,

    # --- progress toward scoring --------------------------------------
    # MUST be well below golem_points, and it is worth understanding why:
    # best_target is points/(1 + TTC), so for a golem you can claim right now
    # (TTC = 0) it equals that golem's full face value. It is a *promise* of
    # points. Price the promise near the points and claiming becomes a loss —
    # you trade a large best_target for a smaller golem_points and V falls.
    #
    # Not hypothetical. At 1.5 the first handset bot skipped 48 legal claims
    # in one game and lost 120 of 120 to GreedyBot, 0.75 golems to 5.99. At
    # 0.6 it still skipped 28 and scored 0 golems. A promise is worth a
    # fraction of the thing promised.
    "best_target": 0.35,
    "token_race": 0.35,

    # --- engine quality ------------------------------------------------
    # Production compounds, so an extra YE per turn pays off over a game —
    # but every one of these rewards *holding* what a claim spends, so they
    # are kept small on purpose. Their job is to break ties between moves
    # that do not score, never to outvote a move that does.
    "throughput": 1.0,
    "playable_now": 0.15,    # usable now is worth something; it is not score
    "exhausted": -0.05,      # value stranded in the played pile, pending a Rest
    "dead_hand": -2.0,       # a turn that achieves nothing
}

LAMBDA = 0.5                 # weight on the leading opponent's symmetric features


def build(scales: Scales) -> dict[str, float]:
    anchor_scale = scales.get(ANCHOR)
    return {k: round(VALUE[k] * scales.get(k) / anchor_scale, 5) for k in CORE_FEATURES}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(SCALES_PATH).parent / "handset_v1.json"))
    ap.add_argument("--name", default="handset_v1")
    args = ap.parse_args()

    scales = Scales.load()
    if not scales.values:
        raise SystemExit("no feature_scales.json — run `python -m bots.calibrate` first")

    w = build(scales)
    weights = Weights(
        name=args.name,
        features=list(CORE_FEATURES),
        w_early=w,
        w_late=dict(w),          # one weight set until Step 6b
        lam=LAMBDA,
        params={"ttc_depth": DEFAULT_TTC_DEPTH, "alpha": 1.0, "beta": 1.0},
        meta={
            "player_counts": [2],
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "handset, generated by bots.make_handset from VALUE",
            "value_in_points": VALUE,
            "scales_from": scales.diagnostics.get(ANCHOR, {}).get("n"),
        },
    )
    weights.save(Path(args.out))

    print(f"{'feature':<14}{'points/unit':>13}{'scale':>9}{'weight':>10}{'contrib@p95':>13}")
    print("-" * 59)
    for k in CORE_FEATURES:
        d = scales.diagnostics.get(k, {})
        contrib = w[k] * d.get("p95", 0.0) / scales.get(k)
        print(f"{k:<14}{VALUE[k]:>13.2f}{scales.get(k):>9.2f}{w[k]:>10.4f}{contrib:>13.2f}")
    print(f"\nlambda = {LAMBDA}")
    print(f"wrote {args.out}")
    print("\n'contrib@p95' is what this feature adds to V in a strong position.")
    print("Those are the numbers that should look sensible relative to each")
    print("other — the weights themselves are an implementation detail.")


if __name__ == "__main__":
    main()

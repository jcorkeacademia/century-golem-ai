"""Roadmap step 9: what do near-optimal solo plans actually do?

The calibration (solver/calibrate.py) found the beam's plans within ~0-1 turn
of the proven optimum on every game small enough to prove, so they are a
trustworthy picture of good solo play. This runs the beam (plus plan repair)
over many seeds, replays each plan, and records what it does — alongside the
tuned bot's plans on the same seeds, so the comparison shows what
near-optimal play does DIFFERENTLY.

Per plan:
    tempo      total turns, and the turn each golem is claimed
    buying     every card acquired: which, when, from which slot
    offers     every merchant card that appeared in the row, so buying can
               be read as a pick rate (bought / offered) rather than a raw
               count that just rewards common cards
    playing    how often each card is played
    golems     which are claimed, what they cost, whether a token came too
    mix        counts of each kind of move

    python -m solver.study [seeds] [beam width] [workers] [first seed]

Seeds already in results/solver_study.json at the same beam width are kept
and new ones merged in, so a study can be grown in instalments. Writes
results/solver_study.json (every plan's record) and results/solver_study.md
(the summary, with 95% ranges on every pick rate).
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from math import sqrt
from statistics import mean, stdev

from bots._engine import (Acquire, Claim, Discard, PlayCrystal, PlayTrade,
                          PlayUpgrade, Rest)
from solver.bracket import action_to_json
from solver.greedy import Plan, upper_bound, verify
from solver.improve import beam, repair
from solver.solo import new_solo_game, turns_in

OUT = Path(__file__).resolve().parent.parent / "results"


def describe(seed: int, plan: Plan) -> dict:
    """Replay `plan` and record what it does, turn by turn."""
    verify(seed, plan)
    game = new_solo_game(seed=seed)
    turn = 0
    rec = {
        "turns": plan.turns, "claims": [], "bought": [], "offered": [],
        "played": Counter(), "mix": Counter(), "owned_at_first_claim": None,
    }
    offered = set()
    for action in plan.actions:
        if not isinstance(action, Discard):
            turn += 1
        for card in game.merchant_row:          # what this turn could buy
            if card is not None and card.name not in offered:
                offered.add(card.name)
        p = game.players[0]
        kind = type(action).__name__
        rec["mix"][kind] += 1
        if isinstance(action, Acquire):
            card = game.merchant_row[action.row_index]
            rec["bought"].append({"card": card.name, "turn": turn,
                                  "slot": action.row_index})
        elif isinstance(action, (PlayCrystal, PlayUpgrade, PlayTrade)):
            rec["played"][p.hand[action.hand_index].name] += 1
        elif isinstance(action, Claim):
            golem = game.point_row[action.row_index]
            if rec["owned_at_first_claim"] is None:
                rec["owned_at_first_claim"] = len(p.hand) + len(p.played)
            rec["claims"].append({
                "golem": golem.name, "turn": turn, "slot": action.row_index,
                "cost": sum(n for _, n in golem.cost), "points": golem.points,
                "token": action.row_index in (0, 1)
                         and bool(game.point_tokens[action.row_index])})
        game.apply_action(action)
    rec["offered"] = sorted(offered)
    rec["played"] = dict(rec["played"])
    rec["mix"] = dict(rec["mix"])
    return rec


def study_seed(seed: int, width: int = 1000) -> dict:
    t0 = time.time()
    best = repair(seed, beam(seed, width), 2_000)
    bots = upper_bound(seed)
    return {
        "seed": seed,
        "best": describe(seed, best),
        "bots": describe(seed, bots),
        "plan": [action_to_json(a) for a in best.actions],
        "seconds": round(time.time() - t0),
    }


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% range for a rate k/n (Wilson score interval): honest at small n
    and near 0% or 100%, where the plain +/- formula is not."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def _summary(rows: list[dict], who: str) -> dict:
    recs = [r[who] for r in rows]
    buys = Counter(b["card"] for r in recs for b in r["bought"])
    offers = Counter(c for r in recs for c in r["offered"])
    plays = Counter()
    for r in recs:
        plays.update(r["played"])
    claim_turns = [[c["turn"] for c in r["claims"]] for r in recs]
    return {
        "turns": [r["turns"] for r in recs],
        "claim_turn_means": [round(mean(t[i] for t in claim_turns), 1) for i in range(6)],
        "buys_per_game": mean(len(r["bought"]) for r in recs),
        "buys_before_first_claim": mean(
            sum(1 for b in r["bought"] if b["turn"] < r["claims"][0]["turn"]) for r in recs),
        "last_buy_turn": mean(max((b["turn"] for b in r["bought"]), default=0) for r in recs),
        "buy_slot_mean": mean(b["slot"] for r in recs for b in r["bought"]) if buys else 0,
        "owned_at_first_claim": mean(r["owned_at_first_claim"] for r in recs),
        "rests_per_game": mean(r["mix"].get("Rest", 0) for r in recs),
        "plays_per_game": mean(sum(r["played"].values()) for r in recs),
        "golem_cost_mean": mean(c["cost"] for r in recs for c in r["claims"]),
        "tokens_per_game": mean(sum(c["token"] for c in r["claims"]) for r in recs),
        "pick_rate": {name: (buys[name], offers[name]) for name in offers},
        "plays": dict(plays),
    }


def _write(rows: list[dict], width: int) -> None:
    (OUT / "solver_study.json").write_text(
        json.dumps({"beam_width": width, "seeds": rows}, indent=1, default=int),
        encoding="utf-8")
    best, bots = _summary(rows, "best"), _summary(rows, "bots")
    n = len(rows)

    def line(label, key, fmt="{:.1f}"):
        return f"| {label} | {fmt.format(best[key])} | {fmt.format(bots[key])} |"

    lines = [
        "# What near-optimal solo plans do",
        "",
        f"Beam search (width {width}) plus plan repair on {n} seeds, against the",
        "tuned bot's own plans on the same seeds. The calibration puts the beam",
        "within ~0-1 turn of the proven optimum wherever a proof was possible.",
        "",
        "## Tempo and habits",
        "",
        "| | near-optimal | tuned bot |",
        "|---|---|---|",
        f"| turns to win (mean ± 95%) | {mean(best['turns']):.1f} ± "
        f"{1.96 * stdev(best['turns']) / sqrt(n):.1f} | {mean(bots['turns']):.1f} ± "
        f"{1.96 * stdev(bots['turns']) / sqrt(n):.1f} |",
        f"| turns to win (range) | {min(best['turns'])}-{max(best['turns'])} | "
        f"{min(bots['turns'])}-{max(bots['turns'])} |",
        "| turn of golem 1-6 (mean) | " + ", ".join(map(str, best["claim_turn_means"]))
        + " | " + ", ".join(map(str, bots["claim_turn_means"])) + " |",
        line("cards bought per game", "buys_per_game"),
        line("...of which before the first golem", "buys_before_first_claim"),
        line("turn of the last purchase", "last_buy_turn"),
        line("mean slot bought from (0 = free)", "buy_slot_mean", "{:.2f}"),
        line("cards owned at the first claim", "owned_at_first_claim"),
        line("card plays per game", "plays_per_game"),
        line("Rests per game", "rests_per_game"),
        line("mean golem cost (crystals)", "golem_cost_mean", "{:.2f}"),
        line("bonus tokens per game", "tokens_per_game", "{:.2f}"),
        "",
        "## Cards near-optimal plans buy, by pick rate",
        "",
        "Bought / times the card appeared in the row across all plans, with the 95%",
        f"range; cards offered at least {max(3, n // 10)} times. **Differs** marks the",
        "cards whose two ranges do not overlap: the only differences to trust.",
        "",
        "| card | near-optimal | 95% range | tuned bot | 95% range | |",
        "|---|---|---|---|---|---|",
    ]
    floor = max(3, n // 10)
    ranked = sorted(((b / o, name, b, o) for name, (b, o) in best["pick_rate"].items()
                     if o >= floor), reverse=True)
    for rate, name, b, o in ranked:
        bb, bo = bots["pick_rate"].get(name, (0, 0))
        lo, hi = wilson(b, o)
        blo, bhi = wilson(bb, bo)
        differs = "**differs**" if hi < blo or bhi < lo else ""
        bot_rate = f"{bb}/{bo} ({bb / bo:.0%})" if bo else "-"
        lines.append(f"| {name} | {b}/{o} ({rate:.0%}) | {lo:.0%}-{hi:.0%} | "
                     f"{bot_rate} | {blo:.0%}-{bhi:.0%} | {differs} |")
    lines += ["", "## Most-played cards (near-optimal plans)", "",
              "| card | plays | per game |", "|---|---|---|"]
    for name, count in Counter(best["plays"]).most_common(12):
        lines.append(f"| {name} | {count} | {count / n:.1f} |")
    (OUT / "solver_study.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _existing(width: int) -> dict[int, dict]:
    path = OUT / "solver_study.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("beam_width") != width:
        return {}                       # a different width is a different study
    return {r["seed"]: r for r in data["seeds"]}


if __name__ == "__main__":  # pragma: no cover - manual run
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    width = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 16
    first = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    t = time.time()
    have = _existing(width)
    todo = [s for s in range(first, first + n) if s not in have]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for row in pool.map(study_seed, todo, [width] * len(todo)):
            have[row["seed"]] = row
            if len(have) % 25 == 0:     # save as it goes: hours-long runs
                _write([have[k] for k in sorted(have)], width)
    rows = [have[k] for k in sorted(have)]
    _write(rows, width)
    print(f"wrote results/solver_study.md  ({len(rows)} seeds, {len(todo)} new, "
          f"{time.time() - t:.0f}s wall)")

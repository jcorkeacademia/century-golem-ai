"""A turn-by-turn log of a seed's best plan: the board, your cards, every move.

For each turn: the move in plain words (which card was bought and what it
cost, what a trade converted, which golem was claimed and whether a token
came with it, what a Rest returned, what was discarded), then the whole
position it was made from — the merchant row with any crystals sitting on
its cards, the golem row, the token piles, the next cards to be drawn (the
solver knows the deck order on a fixed seed, so the log shows it too), and
your caravan, hand, played pile and golems.

The plan logged is the shortest saved one for that seed: the bracket report
(seeds 0-9, beam width 3000) and the step-9 study (500 seeds, width 1000).
A seed in neither is solved on the spot with beam + plan repair.

    python -m solver.replay_log SEED [SEED ...]

Writes results/solver_logs/seed_NNN.md. (results/ subfolders are not
tracked by git; these regenerate from the saved plans in seconds.)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from bots._engine import (Acquire, Claim, Crystal, CrystalCard, Discard, Game,
                          PlayCrystal, PlayTrade, PlayUpgrade, Rest, Token,
                          TradeCard, UpgradeCard)
from solver.bracket import action_from_json
from solver.greedy import Plan, verify
from solver.solo import new_solo_game, turns_in

RESULTS = Path(__file__).resolve().parent.parent / "results"
OUT = RESULTS / "solver_logs"
LETTER = "YGBM"
NAME = {Crystal.YELLOW: "yellow", Crystal.GREEN: "green",
        Crystal.TURQUOISE: "blue", Crystal.MAGENTA: "magenta"}


# ---------------------------------------------------------------------------
# Finding the best saved plan
# ---------------------------------------------------------------------------

def best_saved_plan(seed: int) -> tuple[Plan, str]:
    """The shortest plan saved for `seed`, and where it came from."""
    found = []
    for file, label in (("solver_bracket.json", "bracket"), ("solver_study.json", "study")):
        path = RESULTS / file
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data["seeds"]:
            if row["seed"] == seed:
                actions = tuple(action_from_json(d) for d in row["plan"])
                width = data.get("beam_width", "?")
                found.append((Plan(turns_in(actions), actions, label),
                              f"{label} (beam width {width})"))
    if not found:
        from solver.improve import beam, repair
        plan = repair(seed, beam(seed, 1000), 2_000)
        return plan, "solved now (beam width 1000 + repair)"
    return min(found, key=lambda t: t[0].turns)


# ---------------------------------------------------------------------------
# Words for things
# ---------------------------------------------------------------------------

def crystals(counts) -> str:
    """[2,1,0,1] -> 'Y Y G M'  (and '-' for none)."""
    out = [LETTER[c] for c in range(4) for _ in range(counts[c])]
    return " ".join(out) if out else "-"


def pairs(pairs_) -> str:
    counts = [0, 0, 0, 0]
    for colour, n in pairs_:
        counts[colour] += n
    return crystals(counts)


def card(c) -> str:
    return c.name if c is not None else "(empty)"


def golem(g) -> str:
    if g is None:
        return "(empty)"
    return f"{g.name}  [costs {pairs(g.cost)}, {g.points} pts]"


def board(game: Game, peek: int = 3) -> list[str]:
    p = game.players[0]
    lines = ["  Merchant row (slot: card, crystals on it):"]
    for j, c in enumerate(game.merchant_row):
        on = crystals([game.row_crystals[j].get(k, 0) for k in range(4)])
        lines.append(f"    [{j}] {card(c)}" + (f"   <- {on} on it" if on != "-" else ""))
    lines.append("  Golem row:")
    for j, g in enumerate(game.point_row):
        pile = game.point_tokens[j]
        token = ""
        if pile:
            kind = "copper" if pile[-1] == Token.COPPER else "silver"
            token = f"   + {kind} token ({len(pile)} left)"
        lines.append(f"    [{j}] {golem(g)}{token}")
    upcoming_m = [c.name for c in reversed(game.merchant_deck[-peek:])]
    upcoming_g = [g.name for g in reversed(game.point_deck[-peek:])]
    lines.append(f"  Next merchant cards drawn: {', '.join(upcoming_m) or '(deck empty)'}")
    lines.append(f"  Next golems drawn: {', '.join(upcoming_g) or '(deck empty)'}")
    lines.append(f"  Caravan ({sum(p.caravan)}/10): {crystals(p.caravan)}")
    lines.append(f"  Hand: {', '.join(c.name for c in p.hand) or '-'}")
    lines.append(f"  Played pile: {', '.join(c.name for c in p.played) or '-'}")
    lines.append(f"  Golems claimed ({len(p.point_cards)}/{game.win_target}): "
                 f"{', '.join(g.name for g in p.point_cards) or '-'}")
    return lines


def describe_move(game: Game, action) -> str:
    """The move in plain words, read off the position BEFORE it is made."""
    p = game.players[0]
    if isinstance(action, PlayCrystal):
        c = p.hand[action.hand_index]
        return f"Play **{c.name}**: gain {pairs(c.gain)}"
    if isinstance(action, PlayUpgrade):
        c = p.hand[action.hand_index]
        steps = ", ".join(f"{NAME[x]} -> {NAME[Crystal(x + 1)]}" for x in action.upgrades)
        return f"Play **{c.name}**: upgrade {steps or 'nothing'}"
    if isinstance(action, PlayTrade):
        c = p.hand[action.hand_index]
        return (f"Play **{c.name}** x{action.times}: pay {pairs(c.cost)} each time, "
                f"get {pairs(c.gain)} each time")
    if isinstance(action, Acquire):
        c = game.merchant_row[action.row_index]
        on = crystals([game.row_crystals[action.row_index].get(k, 0) for k in range(4)])
        if action.payment:
            paid = (f"pay {' '.join(LETTER[x] for x in action.payment)} "
                    "(one onto each card to its left)")
        else:
            paid = "free (slot 0)"
        extra = f", and pick up {on} sitting on it" if on != "-" else ""
        return f"Acquire **{c.name}** from slot {action.row_index}: {paid}{extra}"
    if isinstance(action, Rest):
        return f"Rest: {', '.join(c.name for c in p.played)} return to hand"
    if isinstance(action, Claim):
        g = game.point_row[action.row_index]
        pile = game.point_tokens[action.row_index] if action.row_index in (0, 1) else []
        token = ""
        if pile:
            token = f", and take a {'copper' if pile[-1] == Token.COPPER else 'silver'} token"
        return f"Claim golem **{g.name}** from slot {action.row_index}: pay {pairs(g.cost)}{token}"
    if isinstance(action, Discard):
        return f"Discard {crystals(action.counts)} (caravan over 10)"
    return repr(action)


# ---------------------------------------------------------------------------
# The log
# ---------------------------------------------------------------------------

def log(seed: int, plan: Optional[Plan] = None, source: str = "") -> str:
    if plan is None:
        plan, source = best_saved_plan(seed)
    verify(seed, plan)
    game = new_solo_game(seed=seed)
    lines = [f"# Seed {seed}: won in {plan.turns} turns",
             "",
             f"Plan from: {source}. Replayed and verified. Crystals: Y yellow, "
             "G green, B blue, M magenta. Each turn shows the position, then the "
             "move made from it.",
             ""]
    turn = 0
    for action in plan.actions:
        if isinstance(action, Discard):
            lines.append(f"- *same turn:* {describe_move(game, action)}")
        else:
            turn += 1
            lines += ["", f"## Turn {turn}", "", "```"] + board(game) + ["```", ""]
            lines.append(f"- **Move:** {describe_move(game, action)}")
        game.apply_action(action)
        if isinstance(action, Claim):
            got = len(game.players[0].point_cards)
            lines.append(f"- golem {got} of {game.win_target}")
    # An at-a-glance list of every move, placed under the title.
    glance = ["## At a glance", ""]
    current = None
    for line in lines:
        if line.startswith("## Turn "):
            current = line[3:]
        elif line.startswith("- **Move:** "):
            glance.append(f"- {current}: {line[len('- **Move:** '):]}")
        elif line.startswith("- *same turn:* ") or line.startswith("- golem "):
            glance.append(f"  {line}")
    lines[5:5] = glance + [""]
    lines += ["", "## Final position", "", "```"] + board(game) + ["```", ""]
    lines.append(f"Won on turn {turn}, with {game.players[0].score()} points.")
    return "\n".join(lines) + "\n"


def write(seed: int) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"seed_{seed:03d}.md"
    path.write_text(log(seed), encoding="utf-8")
    return path


if __name__ == "__main__":  # pragma: no cover - manual run
    for arg in sys.argv[1:] or ["0"]:
        print(write(int(arg)))

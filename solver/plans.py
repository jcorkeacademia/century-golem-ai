"""Saved plans: actions to and from JSON, and loading a seed's best plan.

Deliberately light — no scipy, no search — because the game server imports it
for guided TEST rooms (solver/guide.py), and the server should not need the
solver's heavier dependencies just to read a list of moves.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from bots._engine import (Acquire, Claim, Crystal, Discard, IllegalAction,
                          PlayCrystal, PlayTrade, PlayUpgrade, Rest)
from solver.solo import turns_in

RESULTS = Path(__file__).resolve().parent.parent / "results"
SAVED = (("solver_bracket.json", "bracket"), ("solver_study.json", "study"))


def action_to_json(a) -> dict:
    if isinstance(a, PlayCrystal):
        return {"play": "crystal", "hand": a.hand_index}
    if isinstance(a, PlayUpgrade):
        return {"play": "upgrade", "hand": a.hand_index, "upgrades": [int(c) for c in a.upgrades]}
    if isinstance(a, PlayTrade):
        return {"play": "trade", "hand": a.hand_index, "times": a.times}
    if isinstance(a, Acquire):
        return {"acquire": a.row_index, "payment": [int(c) for c in a.payment]}
    if isinstance(a, Rest):
        return {"rest": True}
    if isinstance(a, Claim):
        return {"claim": a.row_index}
    if isinstance(a, Discard):
        return {"discard": list(a.counts)}
    raise TypeError(a)


def action_from_json(d: dict):
    if "play" in d:
        kind = d["play"]
        if kind == "crystal":
            return PlayCrystal(d["hand"])
        if kind == "upgrade":
            return PlayUpgrade(d["hand"], tuple(Crystal(c) for c in d["upgrades"]))
        return PlayTrade(d["hand"], d["times"])
    if "acquire" in d:
        return Acquire(d["acquire"], tuple(Crystal(c) for c in d["payment"]))
    if "rest" in d:
        return Rest()
    if "claim" in d:
        return Claim(d["claim"])
    return Discard(tuple(d["discard"]))


def _opening(seed: int):
    from solver.solo import new_solo_game
    return new_solo_game(seed=seed)


def best_saved(seed: int) -> Optional[tuple[tuple, str]]:
    """(actions, where from) for the shortest saved plan for `seed` that
    follows the full-upgrade rule, or None. Not otherwise replay-checked;
    callers that need that verify it themselves."""
    found = []
    for file, label in SAVED:
        path = RESULTS / file
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data["seeds"]:
            if row["seed"] == seed:
                actions = tuple(action_from_json(d) for d in row["plan"])
                try:
                    if partial_upgrades(_opening(seed), actions):
                        continue  # breaks the full-upgrade rule: not playable
                except IllegalAction:
                    continue      # saved under older card data; no longer legal
                found.append((turns_in(actions), actions,
                              f"{label} (beam width {data.get('beam_width', '?')})"))
    if not found:
        return None
    _, actions, source = min(found, key=lambda t: t[0])
    return actions, source


def partial_upgrades(game, actions) -> list[int]:
    """Turns (1-based) where `actions`, played from `game`, upgrade fewer
    steps than the card has — breaking the house rule that an Upgrade card is
    used in full (see solver.search.uses_every_step). Empty means the plan is
    one a player can make in the web client. `game` is not modified."""
    from bots._engine import PlayUpgrade
    from solver.fastclone import fast_clone
    sim = fast_clone(game)
    bad, turn = [], 0
    for a in actions:
        if not isinstance(a, Discard):
            turn += 1
        if isinstance(a, PlayUpgrade) and len(a.upgrades) != sim.player.hand[a.hand_index].steps:
            bad.append(turn)
        sim.apply_action(a)
    return bad

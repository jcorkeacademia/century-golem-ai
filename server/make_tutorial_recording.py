"""Finds and writes the recorded game the interactive tutorial replays.

    cd server && python make_tutorial_recording.py [first_seed] [seeds_to_try]

The tutorial (tutorial.py) needs one real 2-player game, stored as a seed
plus every move in CONTRACT.md §2's message format, with:

- seat 0's very first move taking the 3rd merchant card (row_index 2), so
  scene 6 can hand the player exactly that move. Only seeds where the hard
  bot *chose* that move itself are kept, so the tutorial is showing a move a
  strong player would make, not one forced on the game.
- seat 0 winning, so the player inherits a winning position in scene 11.
- a hand-off point: seat 0 to move, three of its own turns from claiming its
  6th golem, with the opponent on 3 golems or fewer — 3 claims in the 2 turns
  it gets before then is impossible, so the opponent cannot end the game first.

Seat 0 is played by the hard bot and seat 1 by medium. The bots draw on
game.rng, but the engine only uses its rng to shuffle at setup, so replaying
the same moves from the same seed rebuilds the identical game without them
(test_tutorial.py checks this).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import engine_path  # noqa: F401  (sys.path + compendium, must run first)
from century_engine import Acquire, Claim, Game, PlayCrystal, PlayTrade, PlayUpgrade, Rest
from bot_policy import pick_action

OUT = Path(__file__).resolve().parent / "tutorial_recording.json"
LETTER = "YGBM"
BOTS = ("hard", "medium")
TURNS_FROM_SIXTH = 3      # seat 0's own turns, the hand-off turn included
MAX_ACTIONS = 400


def action_to_msg(a) -> dict:
    """Engine action -> the client message that rebuilds it (actions.build_action)."""
    if isinstance(a, PlayCrystal):
        return {"type": "play_crystal", "hand_index": a.hand_index}
    if isinstance(a, PlayUpgrade):
        return {"type": "play_upgrade", "hand_index": a.hand_index, "upgrades": [LETTER[c] for c in a.upgrades]}
    if isinstance(a, PlayTrade):
        return {"type": "play_trade", "hand_index": a.hand_index, "times": a.times}
    if isinstance(a, Acquire):
        return {"type": "acquire", "row_index": a.row_index, "payment": [LETTER[c] for c in a.payment]}
    if isinstance(a, Rest):
        return {"type": "rest"}
    if isinstance(a, Claim):
        return {"type": "claim", "row_index": a.row_index}
    raise TypeError(f"no message form for {a!r}")


def play(seed: int):
    """One bot game. Returns (moves, golem counts before each move, game),
    or None if seat 0's first move isn't the 3rd card."""
    game = Game(["You", "Bot"], seed=seed)
    moves, golems_before = [], []
    while not game.game_over and len(moves) < MAX_ACTIONS:
        a = pick_action(game, BOTS[game.current])
        if not moves and not (isinstance(a, Acquire) and a.row_index == 2):
            return None
        golems_before.append([len(p.point_cards) for p in game.players])
        moves.append(a)
        game.apply_action(a)
    return moves, golems_before, game


def find_handoff(moves, golems_before) -> int | None:
    """Index of the move where control passes to the player, or None."""
    sixth = next((i for i, a in enumerate(moves)
                  if i % 2 == 0 and isinstance(a, Claim) and golems_before[i][0] == 5), None)
    if sixth is None:
        return None
    handoff = sixth - 2 * (TURNS_FROM_SIXTH - 1)   # seat 0 moves on even indices
    if handoff <= 2 or golems_before[handoff][1] > 3:
        return None
    return handoff


def main() -> None:
    first = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    tries = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    for seed in range(first, first + tries):
        result = play(seed)
        if result is None:
            continue
        moves, golems_before, game = result
        if not game.game_over or game._winner_index() != 0:
            continue
        handoff = find_handoff(moves, golems_before)
        if handoff is None:
            continue
        third = Game(["You", "Bot"], seed=seed).merchant_row[2]
        record = {
            "seed": seed,
            "players": ["You", "Bot"],
            "bots": list(BOTS),
            "moves": [action_to_msg(a) for a in moves],
            "handoff": handoff,
            "summary": {
                "first_move_takes": third.name,
                "total_moves": len(moves),
                "golems_at_handoff": golems_before[handoff],
                "final_scores": [p.score() for p in game.players],
            },
        }
        OUT.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
        print(f"seed {seed}: wrote {OUT.name}")
        print(json.dumps(record["summary"], indent=1))
        return
    print("no seed in range met every condition")


if __name__ == "__main__":
    main()

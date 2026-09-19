"""
Dev-only helper: fast-forward a running Game to game_over by repeatedly
calling the same legal_actions()/apply_action() every real client goes
through — no engine or turn-handling logic touched, just automated input.

Also backs the live bot seats (main.py's auto-play loop) with the exact
same policy, one action at a time, so "fast-forward to the end" and
"the other 4 seats play themselves while you watch" are guaranteed to
behave identically instead of drifting into two different bots.

The policy itself lives in bot_policy.py, which offers three difficulties.
This module re-exports it so the fast-forward endpoint and the live bot
seats stay guaranteed to use the same one rather than drifting into two
different bots.

Fast-forwarding defaults to `easy` on purpose: it exists to reach a
mid-game or finished position quickly, and the naive policy is both the
cheapest and the one whose behaviour the dev endpoint has always had.
"""

from __future__ import annotations

from typing import Optional

import engine_path  # noqa: F401  (sys.path + compendium plug-in, must run first)
from century_engine import Action, Game

from bot_policy import DEFAULT_DIFFICULTY, EASY, pick_action  # noqa: F401


def play_to_end(game: Game, max_actions: int = 5000,
                difficulty: str = EASY) -> int:
    """Applies actions until game_over (or max_actions as a safety net).
    Returns how many actions were applied."""
    taken = 0
    while not game.game_over and taken < max_actions:
        action = pick_action(game, difficulty)
        if action is None:
            break
        game.apply_action(action)
        taken += 1
    return taken

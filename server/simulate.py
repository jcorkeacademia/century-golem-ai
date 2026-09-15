"""
Dev-only helper: fast-forward a running Game to game_over by repeatedly
calling the same legal_actions()/apply_action() every real client goes
through — no engine or turn-handling logic touched, just automated input.

Also backs the live bot seats (main.py's auto-play loop) with the exact
same policy, one action at a time, so "fast-forward to the end" and
"the other 4 seats play themselves while you watch" are guaranteed to
behave identically instead of drifting into two different bots.

Policy mirrors the naive self-play loop already sketched in
century_engine.py's own __main__ block: prefer claiming a golem (that's
what actually ends the game), else a random legal action, using the game's
own seeded RNG for reproducibility.
"""

from __future__ import annotations

from typing import Optional

import engine_path  # noqa: F401  (sys.path + compendium plug-in, must run first)
from century_engine import Action, Game, Claim


def pick_action(game: Game) -> Optional[Action]:
    """One turn's worth of policy: prefer claiming a golem, else a random
    legal action. Returns None if the seat to move has no legal action at
    all (shouldn't happen mid-game, but Rest is always legal, so this is
    really just a "game already over" guard)."""
    acts = game.legal_actions()
    if not acts:
        return None
    claim = next((a for a in acts if isinstance(a, Claim)), None)
    return claim or game.rng.choice(acts)


def play_to_end(game: Game, max_actions: int = 5000) -> int:
    """Applies actions until game_over (or max_actions as a safety net).
    Returns how many actions were applied."""
    taken = 0
    while not game.game_over and taken < max_actions:
        action = pick_action(game)
        if action is None:
            break
        game.apply_action(action)
        taken += 1
    return taken

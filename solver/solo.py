"""The solo board: one seat, a fixed seed, the real compendium.

Step 1 of the solver roadmap. Deliberately thin — every interesting decision
belongs to the search, not here. What this module pins down is the *problem
instance*, so that every later step (the bound, DFBB, the brute-force check)
is talking about the same board.

Three properties the search relies on, all verified in tests/test_solo.py:

1. **One seat.** `Game` accepts a single player as of the solo-mode change in
   century_engine.__init__. Nothing else in the engine needed a special case.
2. **The game ends on the claiming turn.** With one player, `_advance_turn`
   wraps to seat 0 every turn, so `game_over` goes true the moment the target
   golem is claimed. No trailing final round to subtract: the number of
   actions applied *is* the turn count the solver minimises.
3. **A seed fixes the whole board**, both deck orders included. That is what
   makes approach 1 of the handover (fix the seed, search deterministically)
   well defined.
"""

from __future__ import annotations

from typing import Optional

# The engine import shim lives in bots/ (see its docstring: it is the single
# place that touches sys.path). Importing it from here is a deliberate reuse,
# not a layering mistake — duplicating it would give the repo two copies of
# the same fragile path insert.
from bots._engine import Game

SOLO_SEAT = "solo"


def new_solo_game(seed: Optional[int] = None, log: bool = False) -> Game:
    """A one-player game on the real compendium.

    `seed` fixes both deck shuffles, so the same seed always yields the same
    problem instance. Pass `seed=None` only for smoke tests — the search has
    nothing to be optimal *about* on a board it cannot reproduce.
    """
    return Game([SOLO_SEAT], seed=seed, log=log)


def goal(game: Game) -> int:
    """Golems needed to end the game. Six, solo — but read it off the engine
    rather than hard-coding it, so a future variant target cannot silently
    disagree with the bound.
    """
    return game.win_target


def claimed(game: Game) -> int:
    """Golems the solo player has claimed so far."""
    return len(game.players[0].point_cards)


if __name__ == "__main__":  # pragma: no cover - manual smoke check
    g = new_solo_game(seed=0)
    print(f"seat={g.players[0].name} goal={goal(g)} caravan={g.players[0].caravan}")
    print(f"merchant row={[c.name for c in g.merchant_row]}")
    print(f"golem row={[c.name for c in g.point_row]}")

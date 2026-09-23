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
   golem is claimed. There is no trailing final round to subtract.

   Careful with what counts as a turn, though. With `discard_choice` on (the
   default here, see below) an over-limit discard is applied through
   `apply_action` like anything else, but it is a *sub-decision*, not a turn:
   the engine does not advance the turn until it is resolved. So the turn
   count is `turns_in(plan)`, not `len(plan)`. They are equal only on a plan
   that never overflows the caravan.
3. **A seed fixes the whole board**, both deck orders included. That is what
   makes approach 1 of the handover (fix the seed, search deterministically)
   well defined.
"""

from __future__ import annotations

from typing import Iterable, Optional

# The engine import shim lives in bots/ (see its docstring: it is the single
# place that touches sys.path). Importing it from here is a deliberate reuse,
# not a layering mistake — duplicating it would give the repo two copies of
# the same fragile path insert.
from bots._engine import Discard, Game

SOLO_SEAT = "solo"


def new_solo_game(seed: Optional[int] = None, log: bool = False,
                  discard_choice: bool = True) -> Game:
    """A one-player game on the real compendium.

    `seed` fixes both deck shuffles, so the same seed always yields the same
    problem instance. Pass `seed=None` only for smoke tests — the search has
    nothing to be optimal *about* on a board it cannot reproduce.

    `discard_choice` defaults to True here, the opposite of the engine's own
    default: the solver wants the real rule, where going over the caravan
    limit is a choice. The engine's cheapest-first fallback throws away the
    yellow that pays for acquisitions, which can make an optimal line look
    slower than it is. Pass False only to compare against the old behaviour.
    """
    return Game([SOLO_SEAT], seed=seed, log=log, discard_choice=discard_choice)


def goal(game: Game) -> int:
    """Golems needed to end the game. Six, solo — but read it off the engine
    rather than hard-coding it, so a future variant target cannot silently
    disagree with the bound.
    """
    return game.win_target


def claimed(game: Game) -> int:
    """Golems the solo player has claimed so far."""
    return len(game.players[0].point_cards)


def turns_in(plan: Iterable[object]) -> int:
    """Turns a plan costs. Discards ride along with the move that caused them
    and cost nothing, so they do not count — see the module docstring.

    This is the `g` of the branch-and-bound search, and the number the whole
    solver is minimising. Anywhere `len(plan)` is used for it instead, a plan
    that overflows the caravan will silently score too high.
    """
    return sum(1 for a in plan if not isinstance(a, Discard))


if __name__ == "__main__":  # pragma: no cover - manual smoke check
    g = new_solo_game(seed=0)
    print(f"seat={g.players[0].name} goal={goal(g)} caravan={g.players[0].caravan}")
    print(f"merchant row={[c.name for c in g.merchant_row]}")
    print(f"golem row={[c.name for c in g.point_row]}")

"""Guided play: the best plan's next move, for the game's TEST rooms.

Room code TEST plays seed 0 solo, TEST42 seed 42, and so on. The server keeps
one Guide per guided game (server/main.py's _run_guided) and asks it, before
every state it sends, which move the plan makes next; the web client draws a
red border on that card, slot or button and shows the details as a line of
text.

Following the plan. After each move the guide compares the position you
reached with the position the plan's own move reaches. Whole positions are
compared, not actions, because two different clicks can land in the same
place (upgrading one crystal twice, or two crystals once, can leave the same
caravan) — being in the plan's position is what "on the plan" means.

Discards. The web client has no discard prompt yet, so when a move overflows
the caravan the guide resolves it itself: the plan's own discard when you are
on the plan, otherwise the cheapest crystals. It says which.

Leaving the plan. The guide re-plans from wherever you are, with a quick beam
search (width REPLAN_WIDTH, a few seconds). The server runs that in a
separate PROCESS — replan_worker() — never in its own: the beam temporarily
swaps bots.features.terminal_value for a solo version, and doing that inside
the game server could reach a practice-mode bot deciding a move at the same
moment. A re-plan is good, not the saved best; the hint says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from bots._engine import (Acquire, Claim, Crystal, Discard, Game, PlayCrystal,
                          PlayTrade, PlayUpgrade, Rest)
from solver.fastclone import fast_clone
from solver.plans import (action_from_json, action_to_json, best_saved,
                          partial_upgrades)
from solver.replay_log import describe_move
from solver.solo import turns_in
from solver.tiny import _full_key

REPLAN_WIDTH = 100
LETTER = "YGBM"
_ROOM = re.compile(r"^TEST(\d{0,6})$")


def guided_seed(room_id: str) -> Optional[int]:
    """TEST -> 0, TEST42 -> 42; None for every other room code."""
    m = _ROOM.match((room_id or "").strip().upper())
    if m is None:
        return None
    return int(m.group(1)) if m.group(1) else 0


def new_guided_game(seed: int, name: str) -> Game:
    """The solo game a guided room plays: the real deck for `seed`, and the
    discard as a choice, which is what the saved plans were found with."""
    return Game([name], seed=seed, log=True, discard_choice=True)


@dataclass
class Guide:
    seed: int
    plan: tuple = ()                  # the moves still to come
    source: str = ""                  # where the plan came from
    turns_taken: int = 0
    history: list = field(default_factory=list)   # every move made, discards too
    replans: int = 0
    replanning: bool = False
    note: str = ""                    # the latest thing worth telling the player

    # -- starting ----------------------------------------------------------

    @classmethod
    def start(cls, seed: int, game: Game) -> "Guide":
        guide = cls(seed)
        saved = best_saved(seed)
        if saved is not None and _replays(game, saved[0]) and not partial_upgrades(game, saved[0]):
            guide.plan, guide.source = saved[0], f"saved best plan, {saved[1]}"
        else:
            # No saved plan, or one that upgrades fewer steps than a card has,
            # which the web client cannot do: plan afresh (the server calls
            # replan_worker at once).
            guide.replanning = True
            guide.source = ("no saved plan for this seed" if saved is None
                            else "saved plan broke the full-upgrade rule")
        return guide

    # -- what to do next -----------------------------------------------------

    def next_action(self):
        return self.plan[0] if self.plan else None

    def hint(self, game: Game) -> dict:
        """What the client shows: the next move, and where the game stands."""
        out = {
            "seed": self.seed,
            "source": self.source,
            "turn": self.turns_taken + 1,
            "planned_total": self.turns_taken + turns_in(self.plan) if self.plan else None,
            "replans": self.replans,
            "status": ("finished" if game.game_over
                       else "replanning" if self.replanning else "guiding"),
            "note": self.note,
            "action": None,
            "text": "",
        }
        action = self.next_action()
        if action is not None and not game.game_over and not self.replanning:
            out["action"] = _action_for_client(action)
            out["text"] = _client_text(game, action)
        return out

    # -- after the player moves ---------------------------------------------

    def observe(self, before: Game, action, after: Game) -> None:
        """Call right after the player's move is applied (before any discard
        is resolved). Advances the plan if the move reached the plan's own
        position; otherwise flags a re-plan."""
        self.history.append(action)
        if not isinstance(action, Discard):
            self.turns_taken += 1
        self.note = ""
        planned = self.next_action()
        if planned is not None:
            expected = fast_clone(before)
            try:
                expected.apply_action(planned)
                on_plan = _full_key(expected) == _full_key(after)
            except Exception:
                on_plan = False
            if on_plan:
                self.plan = self.plan[1:]
                return
        if not after.game_over:
            self.replanning = True
            self.note = "You left the best path, so it is being recalculated from here."

    def resolve_discards(self, game: Game) -> None:
        """Settle any pending discard the client cannot ask about."""
        while game.pending_discard is not None:
            planned = self.next_action()
            if not self.replanning and isinstance(planned, Discard):
                choice = planned
                self.plan = self.plan[1:]
            else:
                choice = _cheapest_discard(game)
            game.apply_action(choice)
            self.history.append(choice)
            dropped = " ".join(LETTER[c] for c in range(4) for _ in range(choice.counts[c]))
            self.note = (self.note + " " if self.note else "") + \
                f"Discarded {dropped} automatically (caravan over 10)."

    def adopt(self, plan_json: list[dict]) -> None:
        """Take a fresh plan from replan_worker."""
        self.plan = tuple(action_from_json(d) for d in plan_json)
        self.replanning = False
        if self.history:                  # not the very first plan
            self.replans += 1
        self.source = f"recalculated from your position (beam width {REPLAN_WIDTH})"


def replan_worker(seed: int, name: str, history_json: list[dict],
                  width: int = REPLAN_WIDTH) -> list[dict]:
    """Rebuild the game from its move history and beam-search a plan from
    there. Runs in a worker PROCESS (see the module docstring)."""
    from solver.improve import beam_from   # heavy imports stay in the worker
    game = new_guided_game(seed, name)
    for d in history_json:
        game.apply_action(action_from_json(d))
    actions = beam_from(game, width)
    if actions is None:
        return []
    return [action_to_json(a) for a in actions]


# ---------------------------------------------------------------------------

def _replays(game: Game, actions: tuple) -> bool:
    sim = fast_clone(game)
    try:
        for a in actions:
            sim.apply_action(a)
    except Exception:
        return False
    return sim.game_over


def _cheapest_discard(game: Game) -> Discard:
    left = game.pending_discard
    caravan = game.players[0].caravan
    counts = [0, 0, 0, 0]
    for colour in range(4):
        take = min(left, caravan[colour])
        counts[colour] = take
        left -= take
    return Discard(tuple(counts))


_ORDINAL = ("1st", "2nd", "3rd", "4th", "5th", "6th")
_WORD = {"Y": "yellow", "G": "green", "B": "blue", "M": "magenta"}


def _client_text(game: Game, action) -> str:
    """describe_move's words, adjusted to what the player does in the web
    client: an acquire payment is dragged crystal by crystal onto the cards
    to the left, and WHICH crystal lands on which card matters (the engine
    records it), so the hint spells out each one."""
    if isinstance(action, Acquire) and action.payment:
        name = game.merchant_row[action.row_index].name
        drops = ", ".join(f"{_WORD[LETTER[c]]} on the {_ORDINAL[k]} card"
                          for k, c in enumerate(action.payment))
        return f"Buy {name} (the {_ORDINAL[action.row_index]} card): first drag {drops}, then click it"
    if isinstance(action, Acquire):
        return f"Buy {game.merchant_row[0].name} (the 1st card, free): click it"
    if isinstance(action, Rest):
        return "Rest (the Reset button): every played card returns to your hand"
    return describe_move(game, action).replace("**", "")


def _action_for_client(a) -> dict:
    """The planned move, in the terms the web client's elements use."""
    if isinstance(a, (PlayCrystal, PlayUpgrade, PlayTrade)):
        out = {"kind": "play", "hand_index": a.hand_index}
        if isinstance(a, PlayTrade):
            out["times"] = a.times
        if isinstance(a, PlayUpgrade):
            out["upgrades"] = [LETTER[c] for c in a.upgrades]
        return out
    if isinstance(a, Acquire):
        return {"kind": "acquire", "row_index": a.row_index,
                "payment": [LETTER[c] for c in a.payment]}
    if isinstance(a, Claim):
        return {"kind": "claim", "row_index": a.row_index}
    if isinstance(a, Rest):
        return {"kind": "rest"}
    return {"kind": "discard", "counts": list(a.counts)}

"""Interactive tutorial: a recorded game, replayed with text at every step.

Reached only through main.ws_room's `?tutorial=true` check. Ordinary,
practice and guided rooms never touch this module and never carry a
`tutorial` field (CONTRACT.md §1e).

The flow is the "Interactive tutorial" design doc, as a flat list of STEPS.
The player takes over three times:

- the upgrade exercise (scene 4), checked against a throwaway SANDBOX game
  holding the exercise caravan, so the engine still judges every answer;
- the paid purchase (scene 6), which must be exactly the recording's own
  first move, payment colours included, because those crystals stay on the
  board for the rest of the recorded game;
- the end of the game (scene 11): the recording fast-forwards to its
  hand-off point, then the player plays freely against an Easy bot.

The recording (tutorial_recording.json, written by make_tutorial_recording.py)
is a seed plus every move as a client message, replayed through
actions.build_action and Game.apply_action — there is no second copy of the
rules here, only a script of moves the engine checks like any other.

Sessions live in their own table, keyed by room code AND name, like guided
rooms, so a refresh resumes at the same step.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Callable, Optional

from fastapi import WebSocket, WebSocketDisconnect

import engine_path  # noqa: F401  (sys.path + compendium, must run first)
import century_cards as cards
from century_engine import Acquire, Claim, Game, IllegalAction, PlayCrystal, PlayTrade, PlayUpgrade, Rest

from actions import MalformedAction, build_action
from bot_policy import pick_action
from rooms import Room
from serialize import game_to_state, merchant_card_to_dict

RECORDING_PATH = Path(__file__).resolve().parent / "tutorial_recording.json"

# Scene 11's opponent, once the player has taken over (design doc build notes).
OPPONENT_DIFFICULTY = "easy"
# Long enough to see the opponent's recorded reply land after the scene 6
# purchase; the fast-forward is quick but still visibly moves; bot turns in
# free play match practice mode's pacing (main.BOT_MOVE_DELAY_SECONDS).
REPLY_DELAY_SECONDS = 0.9
FAST_FORWARD_DELAY_SECONDS = 0.06
BOT_MOVE_DELAY_SECONDS = 0.45

LETTER = "YGBM"
WORD = {"Y": "yellow", "G": "green", "B": "blue", "M": "magenta"}
ORDINAL = ("1st", "2nd", "3rd", "4th", "5th", "6th")

SHOWCASE_CARAVAN = {"Y": 3, "G": 2, "B": 2, "M": 1}       # scenes 2-4: an assortment, room to spare

# Scene 4, played on that same caravan. It resets to UPGRADE_START before
# each try, and an answer is right when it leaves the caravan matching the
# target counts [Y, G, B, M] of any objective not yet done — they can be done
# in any order. Comparing results rather than clicks means two ways to the
# same caravan (green twice, or green then the blue) both count — the result
# is the same, which is the thing being taught.
UPGRADE_START = tuple(SHOWCASE_CARAVAN[c] for c in LETTER)
OBJECTIVES = (
    ("Turn 2 yellows into 2 greens.", (1, 4, 2, 1)),
    ("Turn 1 green into blue, and 1 blue into magenta.", (3, 1, 2, 2)),
    ("Turn 1 yellow into blue.", (2, 2, 3, 1)),
)
DOUBLE_UPGRADE = next(c for c in cards.STARTING_CARDS if getattr(c, "steps", None) == 2)
SHOWCASE_CARDS = ("+2G", "3Y->1M", "Triple upgrade")       # scene 8

# One entry per step. Text is the design doc's wording. `wait` says what ends
# the step (CONTRACT.md §1e); "action" steps take the recording's next move.
STEPS: tuple[dict, ...] = (
    {"id": "welcome", "scene": 1, "title": "Welcome", "stage": "title", "wait": "next",
     "paragraphs": [
         "Century is about using the cards on the board to build an efficient engine "
         "that makes the crystals you need to claim golems. A more detailed explanation "
         "of the game and its rules is here."]},
    {"id": "caravan", "scene": 2, "title": "The caravan", "stage": "caravan", "wait": "next",
     "paragraphs": [
         "The currency of Century is gems. Your caravan, seen below, is where you keep "
         "your gems. Note that you only have 10 spaces."]},
    # "continues": shown in the same box as that step, its words kept above
    # this step's (stage_data.earlier), so the box reads as one page that
    # moves on a step at a time.
    {"id": "order", "scene": 3, "title": "Gem order", "stage": "order", "wait": "next",
     "continues": "caravan",
     "paragraphs": [
         "Gems are split into 4 types: Yellow, Green, Blue and Magenta (in that order). "
         "What do we mean by \"order\"? Well, that brings us to our first card: "
         "the Double Upgrade."]},
    {"id": "upgrade", "scene": 4, "title": "Try it: upgrade", "stage": "upgrade", "wait": "upgrade",
     "continues": "order",
     "paragraphs": ["Click the Double Upgrade, then complete each objective, in any order:"]},
    {"id": "upgrade_recap", "scene": 4, "title": "Well done", "stage": "upgrade", "wait": "next",
     "continues": "upgrade",
     "paragraphs": [
         "A Double Upgrade lifts two gems one level each, or one gem two levels. "
         "Magenta is the top. The Triple Upgrade works the same way, with three steps."]},
    {"id": "turn", "scene": 5, "title": "One thing per turn", "stage": "turn", "wait": "next",
     "continues": "upgrade_recap",
     "paragraphs": [
         "Each turn you do exactly one thing: pick up a merchant card, play a card, "
         "reset, or claim a golem. Let's look at the board."]},
    # Board steps. `anchor` is the part of the board the box is placed
    # against; it stays the same across steps that share a box, so the box
    # holds still while `highlight` moves within it.
    {"id": "merchants", "scene": 6, "title": "Merchant cards", "wait": "next",
     "highlight": "merchant_row", "anchor": "merchant_row",
     "paragraphs": [
         "These are the cards you can pick up. The leftmost is free, and taking a "
         "card ends your turn."]},
    {"id": "pay", "scene": 6, "title": "Skipping ahead", "wait": "action",
     "highlight": "merchant_card", "anchor": "merchant_row", "continues": "merchants",
     "paragraphs": [
         "To take a card further along, put one gem on each card you skip. Any gems "
         "already on the card you take are yours."]},
    {"id": "play_space", "scene": 7, "title": "Your play space", "wait": "next",
     "highlight": "me_mat", "anchor": "mat",
     "paragraphs": [
         "Your caravan is on the left. Playable, in the middle, holds the cards you can "
         "use: everyone starts with +2Y and a Double Upgrade, and your new card is "
         "there too."]},
    {"id": "card_types", "scene": 8, "title": "Three types of cards", "stage": "cards", "wait": "next",
     "paragraphs": []},
    {"id": "played", "scene": 9, "title": "Played cards", "wait": "next",
     "highlight": "played", "anchor": "mat",
     "paragraphs": [
         "Playing a card uses your turn and moves it to Played, where it can't be "
         "used again."]},
    {"id": "reset", "scene": 9, "title": "Reset", "wait": "next",
     "highlight": "reset", "anchor": "mat", "continues": "played",
     "paragraphs": [
         "Reset brings every played card back to Playable. It uses a turn too, so "
         "reset as rarely as you can.",
         "Tip: mix cards that make gems with cards that convert them. Build that "
         "engine early, then claim golems fast."]},
    {"id": "golems", "scene": 10, "title": "Golems and scoring", "wait": "next",
     "highlight": "golem_row", "anchor": "golem_row",
     "paragraphs": [
         "Claim a golem by paying the gems shown at the bottom of its card. The game "
         "ends once someone has 6 golems (5 with 4–5 players), after that round "
         "is finished.",
         "The two leftmost golems also earn a coin: copper is worth 3, silver 1. "
         "Coins run out.",
         "Score: golem points, plus coins, plus 1 for every gem that isn't yellow. "
         "Ties go to the player later in turn order."]},
    {"id": "finish", "scene": 11, "title": "Your turn to finish", "wait": "free_play",
     "paragraphs": [
         "Let's skip ahead to near the end. You're in control now. Can you win?"]},
)
STEP_INDEX = {s["id"]: i for i, s in enumerate(STEPS)}

SHOWCASE_TEXT = (
    ("Crystal", "Adds the gems shown to your caravan."),
    ("Conversion", "Pay the gems it asks for, get the gems it gives, as many times as "
                   "you can afford in one turn. Most of the deck is these. Over 10 gems, "
                   "the extras are thrown away, cheapest first."),
    ("Upgrade", "Like the Double Upgrade, with two or three steps."),
)


def load_recording(path: Path = RECORDING_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TutorialError(Exception):
    """A move the current step doesn't allow. Sent as error code `tutorial`."""


def _bundle(counts) -> dict:
    return {LETTER[i]: n for i, n in enumerate(counts)}


class TutorialSession:
    """One player's tutorial: the step they're on, the recorded game, and
    the upgrade sandbox. Synchronous on purpose — the delays and pushes live
    in the async functions below — so the tests can drive it directly."""

    def __init__(self, room_id: str, name: str, avatar: Optional[str], recording: Optional[dict] = None):
        self.recording = recording or load_recording()
        self.moves = [build_action(m) for m in self.recording["moves"]]
        self.handoff = self.recording["handoff"]
        names = [name.strip() or "You", "Bot"]
        self.room = Room(room_id=room_id, names=names, avatars=[avatar, None], solo=True, human_seat=0)
        self.room.game = Game(names, seed=self.recording["seed"], log=True)
        self.room.started = True
        self.room.turn_clock_started = time.monotonic()
        self.applied = 0          # recorded moves applied so far
        self.step = 0
        self.busy = False         # replaying recorded moves; nothing else may happen
        self.feedback: Optional[dict] = None
        self.done = [False] * len(OBJECTIVES)
        self.attempt = 0
        self.sandbox = self._new_sandbox()

    @property
    def game(self) -> Game:
        return self.room.game

    @property
    def step_def(self) -> dict:
        return STEPS[self.step]

    # -- what the client sees -------------------------------------------------

    def state(self) -> dict:
        state = game_to_state(self.room, 0)
        state["tutorial"] = self.view()
        return state

    def view(self) -> dict:
        s = self.step_def
        target = None
        if s["wait"] == "action" and not self.busy:
            target = _action_for_client(self.moves[self.applied])
        return {
            "id": s["id"],
            "step": self.step + 1,
            "total": len(STEPS),
            "scene": s["scene"],
            "title": s["title"],
            "paragraphs": list(s["paragraphs"]),
            "instruction": self._section(s)["instruction"],
            "refusal": self._section(s)["refusal"],
            "earlier": self._earlier(),
            "later": self._later(),
            "stage": s.get("stage"),
            "stage_data": self._stage_data(s.get("stage")),
            "highlight": s.get("highlight"),
            "highlight_slot": target["row_index"] if target and s.get("highlight") == "merchant_card" else None,
            "anchor": s.get("anchor"),
            "wait": "busy" if self.busy else s["wait"],
            "target": target,
            "feedback": self.feedback,
        }

    def _section(self, s: dict) -> dict:
        """One step's words as a block of a box. A step that wants a move also
        says exactly how to make it (the design doc: "the bubble names the
        colours to drag") — while that move is still to come."""
        instruction = refusal = None
        if s["wait"] == "action" and self.applied < len(self.moves) and STEP_INDEX[s["id"]] >= self.step:
            instruction = f"Try it: {self._instruction()}"
            refusal = self._refusal()
        # `refusal` is what a wrong move gets told; sent ahead so the client
        # can hold room for whichever of the two lines is longer.
        return {"id": s["id"], "title": s["title"], "paragraphs": list(s["paragraphs"]),
                "instruction": instruction, "refusal": refusal}

    def _earlier(self) -> list[dict]:
        """The words of the step this one continues — one step back only, so
        the box holds two steps' words at most and the oldest drops off as
        the page moves on. Sent with every state rather than remembered by
        the client, so a refresh mid-page still shows the whole page."""
        previous = self.step_def.get("continues")
        if not previous:
            return []
        return [self._section(STEPS[STEP_INDEX[previous]])]

    def _later(self) -> list[dict]:
        """The words of the step that will continue this one in the same box,
        so the client can size the box for both from the start and nothing
        moves when they arrive. Never shown."""
        if self.step + 1 >= len(STEPS):
            return []
        nxt = STEPS[self.step + 1]
        return [self._section(nxt)] if nxt.get("continues") == self.step_def["id"] else []

    def _stage_data(self, stage: Optional[str]) -> Optional[dict]:
        room_id = self.room.room_id
        if stage in ("caravan", "turn"):
            return {"caravan": dict(SHOWCASE_CARAVAN)}
        if stage == "order":
            return {"caravan": dict(SHOWCASE_CARAVAN),
                    "card": merchant_card_to_dict(DOUBLE_UPGRADE, room_id=room_id)}
        if stage == "upgrade":
            return {
                "caravan": _bundle(self.sandbox.players[0].caravan),
                "card": merchant_card_to_dict(DOUBLE_UPGRADE, room_id=room_id),
                "objectives": [{"text": text, "done": self.done[i]}
                               for i, (text, _) in enumerate(OBJECTIVES)],
                "attempt": self.attempt,
            }
        if stage == "cards":
            by_name = {c.name: c for c in cards.MERCHANT_CARDS}
            return {"cards": [
                {"card": merchant_card_to_dict(by_name[n], room_id=room_id), "heading": h, "text": t}
                for n, (h, t) in zip(SHOWCASE_CARDS, SHOWCASE_TEXT)]}
        return None

    # -- what the player does -------------------------------------------------

    def next(self) -> Optional[str]:
        """The Next button. Returns a follow-up for the async layer to run
        ("fast_forward" when scene 11 starts), or None."""
        if self.busy or self.step_def["wait"] != "next":
            raise TutorialError(self._what_to_do())
        self._advance()
        return "fast_forward" if self.step_def["id"] == "finish" else None

    def act(self, msg: dict) -> Optional[str]:
        """A game action from the client. Returns a follow-up for the async
        layer ("reply" after the scene 6 purchase, "bots" in free play)."""
        wait = self.step_def["wait"]
        if self.busy:
            raise TutorialError("One moment — the game is still moving.")
        if wait == "upgrade":
            self._try_upgrade(msg)
            return None
        if wait == "action":
            expected = self.moves[self.applied]
            try:
                action = build_action(msg)
            except MalformedAction:
                action = None
            if action != expected:
                raise TutorialError(self._what_to_do())
            self.game.apply_action(action)
            self.applied += 1
            self._advance()
            self.busy = True      # until the opponent's recorded reply lands
            return "reply"
        if wait == "free_play":
            if self.game.game_over:
                raise TutorialError("The game is over.")
            if self.game.current != 0:
                raise TutorialError("The other player is still taking their turn.")
            # build_action / apply_action raise MalformedAction / IllegalAction,
            # which the async layer reports with their usual codes.
            self.game.apply_action(build_action(msg))
            return "bots"
        raise TutorialError(self._what_to_do())

    def _instruction(self) -> str:
        """The recorded purchase, as the gestures that make it."""
        target = _action_for_client(self.moves[self.applied])
        pay, card = target["payment"], ORDINAL[target["row_index"]]
        if not pay:
            return f"click the {card} card."
        if len(set(pay)) == 1:
            each = "the 1st card" if len(pay) == 1 else f"each of the first {len(pay)} cards"
            return f"drag a {WORD[pay[0]]} gem onto {each}, then click the {card}."
        drops = ", ".join(f"{WORD[c]} onto the {ORDINAL[k]}" for k, c in enumerate(pay))
        return f"drag {drops}, then click the {card} card."

    def _refusal(self) -> str:
        text = self._instruction()
        return f"Not that one. {text[0].upper()}{text[1:]}"

    def _what_to_do(self) -> str:
        wait = self.step_def["wait"]
        if wait == "action":
            return self._refusal()
        if wait == "upgrade":
            return "Click the Double Upgrade, then click gems in the caravan."
        return "Click Next to continue."

    def _advance(self) -> None:
        self.feedback = None
        self.step = min(self.step + 1, len(STEPS) - 1)

    # -- the upgrade exercise -------------------------------------------------

    def _new_sandbox(self) -> Game:
        """A one-player game whose only purpose is to judge one Double Upgrade:
        the exercise caravan, and the starting Double Upgrade as its whole hand."""
        g = Game(["You"], seed=0)
        p = g.players[0]
        p.caravan = list(UPGRADE_START)
        p.hand = [DOUBLE_UPGRADE]
        p.played = []
        return g

    def _try_upgrade(self, msg: dict) -> None:
        try:
            action = build_action(msg)
        except MalformedAction:
            action = None
        if not isinstance(action, PlayUpgrade) or action.hand_index != 0:
            raise TutorialError(self._what_to_do())
        # The house rule the client enforces (every step used) — checked here
        # too, so the exercise teaches the rule the real game plays by.
        if len(action.upgrades) != DOUBLE_UPGRADE.steps:
            raise TutorialError("Use both steps of the Double Upgrade, then Confirm.")
        try:
            self.sandbox.apply_action(action)
            result = tuple(self.sandbox.players[0].caravan)
        except IllegalAction:
            result = None
        self.attempt += 1
        self.sandbox = self._new_sandbox()
        matched = [i for i, (_, target) in enumerate(OBJECTIVES) if result == target]
        if not matched:
            self.feedback = {"ok": False, "text": "Not quite. The caravan has been reset, so try again."}
            return
        if all(self.done[i] for i in matched):
            self.feedback = {"ok": False, "text": "You've already done that one. Try another."}
            return
        for i in matched:
            self.done[i] = True
        if all(self.done):
            self._advance()
            self.feedback = {"ok": True, "text": "All three done."}
        else:
            self.feedback = {"ok": True, "text": "That's it. On to the next one."}

    # -- replaying the recording ---------------------------------------------

    def replay_one(self) -> None:
        """Apply the recording's next move."""
        self.game.apply_action(self.moves[self.applied])
        self.applied += 1

    def at_handoff(self) -> bool:
        return self.applied >= self.handoff


def _action_for_client(a) -> dict:
    """A recorded move in state.guide.action's shape, which the board already
    knows how to outline (Board.jsx's guide-target classes)."""
    if isinstance(a, (PlayCrystal, PlayUpgrade, PlayTrade)):
        return {"kind": "play", "hand_index": a.hand_index}
    if isinstance(a, Acquire):
        return {"kind": "acquire", "row_index": a.row_index, "payment": [LETTER[c] for c in a.payment]}
    if isinstance(a, Claim):
        return {"kind": "claim", "row_index": a.row_index}
    if isinstance(a, Rest):
        return {"kind": "rest"}
    raise TypeError(f"no outline for {a!r}")


# ---------------------------------------------------------------------------
# The websocket side
# ---------------------------------------------------------------------------

TUTORIALS: dict[str, TutorialSession] = {}       # "CODE|name" -> session
_TASKS: dict[str, asyncio.Task] = {}             # a running replay per session


async def run(websocket: WebSocket, room_id: str, name: str, avatar: str,
              credit_turn: Callable[[Room, int], None]) -> None:
    code = room_id.strip().upper()
    key = f"{code}|{name}"
    session = TUTORIALS.get(key)
    if session is None:
        session = TutorialSession(code, name, avatar)
        TUTORIALS[key] = session

    session.room.sockets[0] = websocket
    await _push(session)

    try:
        while True:
            msg = await websocket.receive_json()
            await _handle(key, session, msg, credit_turn)
    except WebSocketDisconnect:
        pass
    finally:
        # Kept in TUTORIALS, like a practice room: a refresh just reattaches.
        if session.room.sockets.get(0) is websocket:
            session.room.sockets.pop(0, None)


async def _push(session: TutorialSession) -> None:
    ws = session.room.sockets.get(0)
    if ws is None:
        return
    try:
        await ws.send_json(session.state())
    except Exception:
        if session.room.sockets.get(0) is ws:
            session.room.sockets.pop(0, None)


async def _error(session: TutorialSession, code: str, message: str, echo=None) -> None:
    try:
        await session.room.send_to(0, {"type": "error", "code": code, "message": message, "echo": echo})
    except Exception:
        pass


async def _handle(key: str, session: TutorialSession, msg, credit_turn) -> None:
    if not isinstance(msg, dict) or "type" not in msg:
        await _error(session, "malformed", "message must be an object with a 'type' field", msg)
        return
    if msg["type"] == "ping":
        await session.room.send_to(0, {"type": "pong"})
        return
    if msg["type"] == "start":
        return
    try:
        if msg["type"] == "tutorial_next":
            follow_up = session.next()
        else:
            acting = session.game.current
            follow_up = session.act(msg)
            if follow_up in ("reply", "bots"):
                credit_turn(session.room, acting)
    except TutorialError as e:
        await _error(session, "tutorial", str(e), msg)
        return
    except MalformedAction as e:
        await _error(session, "malformed", str(e), msg)
        return
    except IllegalAction as e:
        await _error(session, "illegal_action", str(e), msg)
        return

    await _push(session)
    if follow_up is not None:
        _start(key, session, follow_up, credit_turn)


def _start(key: str, session: TutorialSession, follow_up: str, credit_turn) -> None:
    """Runs the follow-up as its own task, so it finishes even if the socket
    drops halfway (a refresh then picks up wherever it got to)."""
    running = _TASKS.get(key)
    if running is not None and not running.done():
        return
    job = {"reply": _reply, "fast_forward": _fast_forward, "bots": _bots}[follow_up]
    _TASKS[key] = asyncio.get_running_loop().create_task(job(session, credit_turn))


async def _reply(session: TutorialSession, credit_turn) -> None:
    """The opponent's recorded answer to the scene 6 purchase."""
    await asyncio.sleep(REPLY_DELAY_SECONDS)
    acting = session.game.current
    session.replay_one()
    credit_turn(session.room, acting)
    session.busy = False
    await _push(session)


async def _fast_forward(session: TutorialSession, credit_turn) -> None:
    """Scene 11: replay the recording up to its hand-off point, visibly."""
    session.busy = True
    await _push(session)
    while not session.at_handoff():
        session.replay_one()
        await _push(session)
        await asyncio.sleep(FAST_FORWARD_DELAY_SECONDS)
    # Fast-forwarded turns aren't real thinking time; restart the clock.
    session.room.turn_clock_started = time.monotonic()
    session.busy = False
    await _push(session)


async def _bots(session: TutorialSession, credit_turn) -> None:
    """Scene 11: the opponent, now an Easy bot, takes its turns."""
    game = session.game
    while not game.game_over and game.current != 0:
        await asyncio.sleep(BOT_MOVE_DELAY_SECONDS)
        acting = game.current
        action = pick_action(game, OPPONENT_DIFFICULTY)
        if action is None:
            break
        game.apply_action(action)
        credit_turn(session.room, acting)
        await _push(session)

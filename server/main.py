"""
FastAPI + WebSocket server for Century: Golem Edition.

One Game per room, held server-side (rooms.ROOMS). No auth: a room is
created empty by its first connection (just a `name` + `avatar`, no roster
needed upfront) and fills up one seat at a time as people join — see
`_attach`/`_broadcast_lobby`. The host (seat 0, the first to join) starts
the game once 2-5 people are in (`type: "start"`); from that point on every
action from a client is reconstructed into an engine Action and validated
by Game.apply_action — the client never computes game state.
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.staticfiles import StaticFiles

import engine_path  # noqa: F401  (sys.path + compendium plug-in, must run first)
from century_engine import Game, IllegalAction
import card_art

from rooms import Room, ROOMS, get_or_create_room, MAX_SEATS
from serialize import game_to_state
from actions import build_action, MalformedAction
from simulate import play_to_end
from bot_policy import DEFAULT_DIFFICULTY, normalise as normalise_difficulty, pick_action
import guided
import tutorial as tutorial_mode  # `tutorial` is also ws_room's query param

# Pacing for solo mode's auto-played bot seats (see _play_bots) — long enough
# to actually watch a card land before the next one does, short enough that
# a 4-bot turn doesn't feel like a wait.
BOT_MOVE_DELAY_SECONDS = 0.45

app = FastAPI()

HOST_SEAT = 0  # whoever joins first — the only seat allowed to send "start"
DEFAULT_AVATAR = "gem"  # avatars.js's AVATARS[0] — used only if a client ever omits ?avatar=

# Card art (CARD_ART_HANDOVER.md §5): serve the rendered PNGs straight out of
# the engine's own output folders rather than duplicating them under web/ —
# card_art.py already knows where they live, so this stays correct if they move.
app.mount("/static/golems", StaticFiles(directory=str(card_art.GOLEM_DIR)), name="golem-art")
# Painted set for rooms with 5+ character codes (card_art_index.uses_gol_art). check_dir off
# so a checkout that hasn't run make_cards.py / make_merchants.py --set gol
# still starts.
app.mount("/static/golems-gol", StaticFiles(directory=str(card_art.GOL_GOLEM_DIR), check_dir=False), name="golem-art-gol")
app.mount("/static/merchants-gol", StaticFiles(directory=str(card_art.GOL_MERCH_DIR), check_dir=False), name="merchant-art-gol")
app.mount("/static/merchants", StaticFiles(directory=str(card_art.MERCH_DIR)), name="merchant-art")
# Same 4 crystal icons make_cards.py/make_merchants.py stamp onto the card
# art itself (CARD_ART_HANDOVER.md §1) — reused as-is for the caravan/cost
# dots so they're pixel-identical to what's printed on the cards.
app.mount("/static/crystals", StaticFiles(directory=str(card_art.ROOT / "crystals")), name="crystal-icons")


@app.get("/")
def health() -> dict:
    return {"status": "ok", "rooms": len(ROOMS)}


@app.post("/debug/simulate/{room_id}")
async def debug_simulate(room_id: str, max_actions: int = 5000) -> dict:
    """Dev-only: fast-forward a room's game by auto-playing legal_actions()
    (see simulate.py) — to game_over by default, or to a specific point via
    ?max_actions=N (e.g. to land on a mid-game state with a few golems
    claimed without hand-playing dozens of turns) — then push the resulting
    state to every connected client, same broadcast every real action
    triggers.
    """
    room = ROOMS.get(room_id)
    if room is None or room.game is None:
        return {"error": f"room {room_id!r} not found or game not started"}

    actions_taken = play_to_end(room.game, max_actions=max_actions)
    # Fast-forwarded turns aren't individually timed (they're not real
    # play), but the clock reference still has to move up to "now" — left
    # stale, the next *real* action would get credited with however long
    # passed since before this whole burst, wildly inflating one seat's total.
    room.turn_clock_started = time.monotonic()

    await _push_state(room)

    return {
        "status": "ok",
        "actions_taken": actions_taken,
        "game_over": room.game.game_over,
        "winner": room.game.winner(),
        "scores": room.game.scores(),
    }


@app.post("/debug/reset/{room_id}")
async def debug_reset(room_id: str) -> dict:
    """Dev-only: restart a room's game from turn zero with the same seats,
    then push the fresh state to every connected client — lets you replay a
    room from the beginning without reconnecting with a new room id.
    """
    room = ROOMS.get(room_id)
    if room is None:
        return {"error": f"room {room_id!r} not found"}
    if len(room.names) < 2:
        return {"error": f"room {room_id!r} needs at least 2 players to (re)start"}

    room.game = Game(room.names, seed=None, log=True)
    room.started = True
    room.accumulated_seconds = {}
    room.turn_clock_started = time.monotonic()

    await _push_state(room)

    return {"status": "ok", "room_id": room_id, "current": room.game.current}


async def _push_state(room: Room) -> None:
    """Send every connected seat its own view of the game. One dead socket
    (a dropped tunnel connection raises on send) must never stop the others
    from getting the update — otherwise everyone else is left showing a stale
    "Waiting for other players" until they refresh."""
    for s, sock in list(room.sockets.items()):
        try:
            await sock.send_json(game_to_state(room, s))
        except Exception:
            if room.sockets.get(s) is sock:
                room.sockets.pop(s, None)


async def _error(websocket: WebSocket, code: str, message: str, echo: Optional[dict] = None) -> None:
    await websocket.send_json({"type": "error", "code": code, "message": message, "echo": echo})


async def _attach(room_id: str, name: str, avatar: str, websocket: WebSocket) -> tuple[Optional[Room], Optional[int]]:
    """Validate + attach this socket to a seat. Returns (room, seat), or
    (None, None) after having already sent an error and closed the socket.

    A room is created empty on first connection — no upfront roster. `name`
    either reclaims a seat it already holds (reconnect — rejected as
    `name_taken` if that seat currently has a live socket, i.e. someone
    else is actively using it right now, in which case `avatar` is ignored —
    it was already fixed at first join) or, if the room can still take a
    new player, claims the next open seat with this `avatar`."""
    if not name or not name.strip():
        await _error(websocket, "malformed", "name must not be empty")
        await websocket.close()
        return None, None

    room = get_or_create_room(room_id)

    seat = room.find_seat(name)
    if seat is not None:
        old = room.sockets.get(seat)
        if old is not None:
            if not room.started:
                await _error(websocket, "name_taken", f"{name!r} is already connected in room {room_id!r}")
                await websocket.close()
                return None, None
            # Mid-game, a socket still registered for this name is almost
            # always a dead one the server hasn't noticed yet (tunnel drops
            # leave half-open connections) — rejecting the reconnect would
            # lock the player out until it times out, so the newest wins.
            try:
                await old.close()
            except Exception:
                pass
    elif room.started:
        await _error(websocket, "already_started", f"room {room_id!r} has already started")
        await websocket.close()
        return None, None
    elif not room.can_join():
        await _error(websocket, "room_full", f"room {room_id!r} is full")
        await websocket.close()
        return None, None
    else:
        seat = room.add_player(name, avatar or DEFAULT_AVATAR)

    room.sockets[seat] = websocket
    return room, seat


async def _broadcast_lobby(room: Room) -> None:
    seats = [
        {"seat": i, "name": n, "avatar": room.avatars[i], "connected": i in room.sockets}
        for i, n in enumerate(room.names)
    ]
    for s, sock in list(room.sockets.items()):
        try:
            await sock.send_json({
                "type": "lobby",
                "room": room.room_id,
                "you": s,
                "seats": seats,
                "host": HOST_SEAT,
                "started": room.started,
            })
        except Exception:
            if room.sockets.get(s) is sock:
                room.sockets.pop(s, None)


def _credit_turn_time(room: Room, acting_seat: int) -> None:
    """Call right after an action is accepted, with the seat that just
    acted (game.current *before* apply_action moved it on) — folds however
    long they'd been up into their running total, then starts the clock
    fresh for whoever's up next. time.monotonic() is process-local (never
    meaningful to a client, and wrong across a server restart), which is
    exactly why serialize.py only ever sends the *difference* it produces,
    never this raw timestamp."""
    now = time.monotonic()
    if room.turn_clock_started is not None:
        elapsed = now - room.turn_clock_started
        room.accumulated_seconds[acting_seat] = room.accumulated_seconds.get(acting_seat, 0.0) + elapsed
    room.turn_clock_started = now


@app.websocket("/ws/{room_id}")
async def ws_room(
    websocket: WebSocket,
    room_id: str,
    name: str = Query(...),
    avatar: str = Query(DEFAULT_AVATAR),
    solo: bool = Query(False),
    players: int = Query(4),
    difficulty: str = Query(DEFAULT_DIFFICULTY),
    tutorial: bool = Query(False),
) -> None:
    await websocket.accept()

    # ?tutorial=true: the interactive tutorial (tutorial.py), a recorded game
    # with text at every step. Nothing below this changes for any other room.
    if tutorial:
        await tutorial_mode.run(websocket, room_id, name, avatar, _credit_turn_time)
        return

    # Room code TEST / TEST<n>, joined by code (not practice mode): a guided
    # solo game of seed n with the solver's best plan shown (guided.py).
    # Nothing below this line changes for any other room.
    guided_seed = None if solo else guided.seed_for(room_id)
    if guided_seed is not None:
        await guided.run(websocket, room_id, name, avatar, guided_seed, _credit_turn_time)
        return

    if solo:
        await _run_solo(websocket, room_id, name, avatar, players, difficulty)
        return

    room, seat = await _attach(room_id, name, avatar, websocket)
    if room is None:
        return

    if room.game is not None:
        # Fresh game just started, or this is a seat reclaiming its spot
        # after a disconnect (§4: "on reconnect, resend current state").
        await _push_state(room)
    else:
        await _broadcast_lobby(room)

    try:
        while True:
            msg = await websocket.receive_json()
            await _handle_message(room, seat, msg)
    except WebSocketDisconnect:
        pass
    finally:
        # Only release the seat if it's still this socket's — a reconnect may
        # already have taken it over (see _attach).
        if room.sockets.get(seat) is websocket:
            room.sockets.pop(seat, None)
        if not room.sockets and room.game is None:
            ROOMS.pop(room_id, None)
        elif not room.started:
            await _broadcast_lobby(room)


async def _run_solo(websocket: WebSocket, room_id: str, name: str, avatar: str,
                    players: int, difficulty: str = DEFAULT_DIFFICULTY) -> None:
    """Practice mode: you play one seat, every other seat plays itself
    (bot_policy.pick_action at the chosen difficulty — `hard` is the tuned
    bot from results/REPORT.md, `easy` the original claim-or-random policy)
    so a whole game runs without needing other people. Which seat is yours is shuffled at room creation (see
    room.human_seat below) rather than always being 0 — nothing else here
    or in Board.jsx assumes a fixed seat, since real multiplayer already
    requires everything to key off state.you/game.current instead.
    """
    players = max(2, min(MAX_SEATS, players))
    difficulty = normalise_difficulty(difficulty)

    room = ROOMS.get(room_id)
    if room is None:
        roster = [name.strip() or "You"] + [f"Bot {i}" for i in range(2, players + 1)]
        order = list(range(players))
        random.shuffle(order)
        names = [roster[i] for i in order]
        human_seat = order.index(0)
        avatars: list[Optional[str]] = [None] * players
        avatars[human_seat] = avatar
        room = Room(room_id=room_id, names=names, avatars=avatars, solo=True,
                    human_seat=human_seat, difficulty=difficulty)
        room.game = Game(names, seed=None, log=True)
        room.started = True
        room.turn_clock_started = time.monotonic()
        ROOMS[room_id] = room

    room.sockets[room.human_seat] = websocket
    await websocket.send_json(game_to_state(room, room.human_seat))
    await _play_bots(room)  # only ever does anything on a mid-game reconnect

    try:
        while True:
            msg = await websocket.receive_json()
            await _handle_solo_message(room, msg)
    except WebSocketDisconnect:
        pass
    finally:
        # Deliberately not deleted from ROOMS here, even though this was the
        # only socket: a solo room is "started" (room.game set) the instant
        # it's created, so it follows the same rule real multiplayer rooms
        # already do post-start (see ws_room's own finally) — a refresh (or
        # any drop) just closes this socket, not the game. Reconnecting with
        # the same room_id (App.jsx persists it — see connection.js/App.jsx)
        # finds this same room still here and picks up right where it left
        # off, bot turns included.
        room.sockets.pop(room.human_seat, None)


async def _play_bots(room: Room) -> None:
    """Auto-plays every seat but room.human_seat until it's the human's turn
    again (or the game ends), pushing one state update per move so it reads
    as the bots actually taking their turn rather than the game jumping
    straight past them. `game.current == room.human_seat` always holds when
    this returns, unless the game is over."""
    game = room.game
    while not game.game_over and game.current != room.human_seat:
        acting_seat = game.current
        action = pick_action(game, room.difficulty)
        if action is None:
            break
        game.apply_action(action)
        _credit_turn_time(room, acting_seat)
        sock = room.sockets.get(room.human_seat)
        if sock is None:
            return  # human disconnected mid bot-turn — nothing to push to
        await sock.send_json(game_to_state(room, room.human_seat))
        await asyncio.sleep(BOT_MOVE_DELAY_SECONDS)


async def _handle_solo_message(room: Room, msg: dict) -> None:
    seat = room.human_seat

    if not isinstance(msg, dict) or "type" not in msg:
        await room.send_to(seat, {"type": "error", "code": "malformed",
                                   "message": "message must be an object with a 'type' field", "echo": msg})
        return

    if msg["type"] == "ping":
        await room.send_to(seat, {"type": "pong"})
        return

    if msg["type"] == "start":
        return  # already started the moment the socket connected — a no-op here

    game = room.game
    if game.game_over:
        await room.send_to(seat, {"type": "error", "code": "game_over",
                                   "message": "game is over", "echo": msg})
        return

    if game.current != seat:
        await room.send_to(seat, {"type": "error", "code": "not_your_turn",
                                   "message": "the bots are still taking their turn", "echo": msg})
        return

    try:
        action = build_action(msg)
    except MalformedAction as e:
        await room.send_to(seat, {"type": "error", "code": "malformed", "message": str(e), "echo": msg})
        return

    try:
        game.apply_action(action)
    except IllegalAction as e:
        await room.send_to(seat, {"type": "error", "code": "illegal_action", "message": str(e), "echo": msg})
        return

    _credit_turn_time(room, seat)

    await room.sockets[seat].send_json(game_to_state(room, seat))
    await _play_bots(room)


async def _handle_message(room: Room, seat: int, msg: dict) -> None:
    if not isinstance(msg, dict) or "type" not in msg:
        await room.send_to(seat, {"type": "error", "code": "malformed",
                                   "message": "message must be an object with a 'type' field", "echo": msg})
        return

    if msg["type"] == "ping":
        # Client keepalive — tunnels drop idle websockets (a long think is
        # enough), so the client pings and this just answers.
        await room.send_to(seat, {"type": "pong"})
        return

    if msg["type"] == "start":
        await _handle_start(room, seat)
        return

    game = room.game
    if game is None:
        await room.send_to(seat, {"type": "error", "code": "malformed",
                                   "message": "game has not started - waiting for players", "echo": msg})
        return

    if game.game_over:
        await room.send_to(seat, {"type": "error", "code": "game_over",
                                   "message": "game is over", "echo": msg})
        return

    try:
        action = build_action(msg)
    except MalformedAction as e:
        await room.send_to(seat, {"type": "error", "code": "malformed", "message": str(e), "echo": msg})
        return

    if seat != game.current:
        await room.send_to(seat, {"type": "error", "code": "not_your_turn",
                                   "message": f"it is seat {game.current}'s turn, not seat {seat}'s", "echo": msg})
        return

    try:
        game.apply_action(action)
    except IllegalAction as e:
        await room.send_to(seat, {"type": "error", "code": "illegal_action", "message": str(e), "echo": msg})
        return

    _credit_turn_time(room, seat)

    await _push_state(room)


async def _handle_start(room: Room, seat: int) -> None:
    if room.game is not None:
        await room.send_to(seat, {"type": "error", "code": "already_started", "message": "game already started"})
        return
    if seat != HOST_SEAT:
        await room.send_to(seat, {"type": "error", "code": "not_host", "message": "only the host (seat 0) can start the game"})
        return
    if not (2 <= len(room.names) <= 5):
        await room.send_to(seat, {"type": "error", "code": "not_enough_players",
                                   "message": f"need 2-5 players to start (have {len(room.names)})"})
        return

    room.game = Game(room.names, seed=None, log=True)
    room.started = True
    room.accumulated_seconds = {}
    room.turn_clock_started = time.monotonic()

    await _push_state(room)

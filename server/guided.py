"""Guided TEST rooms: play a seed solo, with the solver's best plan shown.

Joining with room code TEST plays seed 0, TEST42 seed 42, and so on (0-499
have saved best plans). Every state sent to the client carries an extra
`guide` field (solver/guide.py's Guide.hint): the plan's next move, which the
web client outlines in red, plus the turn count and any notes. Leave the plan
and it is recalculated from where you are.

Everything here is reached only through main.ws_room's TEST-code check, and
only for rooms joined by code, not practice mode. Normal rooms never touch
this module, never import the solver, and never get a `guide` field.

Guided rooms live in their own table, keyed by code AND name, so two people
typing TEST get a game each rather than sharing one. A refresh reattaches to
the same game; joining again after it has finished starts a fresh one.

Re-plans run in a worker PROCESS, never in the server's own: the solver's
beam search temporarily swaps bots.features.terminal_value for a solo
version, and inside this process that could reach a practice-mode bot
choosing a move at the same moment.
"""

from __future__ import annotations

import asyncio
import re
import time
from concurrent.futures import ProcessPoolExecutor
from typing import Callable, Optional

from fastapi import WebSocket, WebSocketDisconnect

from actions import MalformedAction, build_action
from century_engine import IllegalAction
from rooms import Room
from serialize import game_to_state

_CODE = re.compile(r"^TEST(\d{0,6})$")

GUIDED: dict[str, tuple[Room, object]] = {}      # "CODE|name" -> (room, Guide)
_TASKS: dict[str, asyncio.Task] = {}             # a running re-plan per room
_POOL: Optional[ProcessPoolExecutor] = None


def seed_for(room_id: str) -> Optional[int]:
    """TEST -> 0, TEST42 -> 42; None for every other code. Cheap, and
    imports nothing, so ordinary rooms pay nothing for this check."""
    m = _CODE.match((room_id or "").strip().upper())
    if m is None:
        return None
    return int(m.group(1)) if m.group(1) else 0


def _pool() -> ProcessPoolExecutor:
    global _POOL
    if _POOL is None:
        _POOL = ProcessPoolExecutor(max_workers=2)
    return _POOL


async def run(websocket: WebSocket, room_id: str, name: str, avatar: str,
              seed: int, credit_turn: Callable[[Room, int], None]) -> None:
    from solver.guide import Guide, new_guided_game   # only TEST rooms load the solver

    code = room_id.strip().upper()
    key = f"{code}|{name}"
    entry = GUIDED.get(key)
    if entry is None or entry[0].game.game_over:
        game = new_guided_game(seed, name.strip() or "You")
        room = Room(room_id=code, names=[game.players[0].name], avatars=[avatar],
                    solo=True, human_seat=0)
        room.game = game
        room.started = True
        room.turn_clock_started = time.monotonic()
        GUIDED[key] = (room, Guide.start(seed, game))
    room, guide = GUIDED[key]

    room.sockets[0] = websocket
    await _push(room, guide)
    if guide.replanning:
        _start_replan(key, room, guide)

    try:
        while True:
            msg = await websocket.receive_json()
            await _handle(key, room, guide, msg, credit_turn)
    except WebSocketDisconnect:
        pass
    finally:
        # Kept in GUIDED, like a practice room: a refresh just reattaches.
        if room.sockets.get(0) is websocket:
            room.sockets.pop(0, None)


async def _push(room: Room, guide) -> None:
    ws = room.sockets.get(0)
    if ws is None:
        return
    state = game_to_state(room, 0)
    state["guide"] = guide.hint(room.game)
    await ws.send_json(state)


async def _error(room: Room, code: str, message: str, echo=None) -> None:
    await room.send_to(0, {"type": "error", "code": code, "message": message, "echo": echo})


async def _handle(key: str, room: Room, guide, msg, credit_turn) -> None:
    from solver.fastclone import fast_clone

    if not isinstance(msg, dict) or "type" not in msg:
        await _error(room, "malformed", "message must be an object with a 'type' field", msg)
        return
    if msg["type"] == "ping":
        await room.send_to(0, {"type": "pong"})
        return
    if msg["type"] == "start":
        return
    game = room.game
    if game.game_over:
        await _error(room, "game_over", "game is over", msg)
        return
    if guide.replanning:
        await _error(room, "recalculating", "the best path is still being recalculated", msg)
        return
    try:
        action = build_action(msg)
    except MalformedAction as e:
        await _error(room, "malformed", str(e), msg)
        return

    before = fast_clone(game)
    try:
        game.apply_action(action)
    except IllegalAction as e:
        await _error(room, "illegal_action", str(e), msg)
        return
    credit_turn(room, 0)
    guide.observe(before, action, game)
    guide.resolve_discards(game)

    await _push(room, guide)
    if guide.replanning:
        _start_replan(key, room, guide)


def _start_replan(key: str, room: Room, guide) -> None:
    running = _TASKS.get(key)
    if running is not None and not running.done():
        return
    _TASKS[key] = asyncio.get_running_loop().create_task(_replan(room, guide))


async def _replan(room: Room, guide) -> None:
    from solver.guide import replan_worker
    from solver.plans import action_to_json

    history = [action_to_json(a) for a in guide.history]
    loop = asyncio.get_running_loop()
    plan = await loop.run_in_executor(
        _pool(), replan_worker, guide.seed, room.game.players[0].name, history)
    guide.adopt(plan)
    if not plan:
        guide.note = "No path to a win was found from here."
    await _push(room, guide)

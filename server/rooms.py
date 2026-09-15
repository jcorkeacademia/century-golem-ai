"""In-memory room registry. One Game per room, held server-side."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from fastapi import WebSocket

import engine_path  # noqa: F401  (sets up sys.path + compendium plug-in)
from century_engine import Game

MAX_SEATS = 5  # century_engine.Game's own ceiling (2-5 players)


@dataclass
class Room:
    room_id: str
    names: list[str] = field(default_factory=list)                # join order; index == seat; seat 0 is host
    avatars: list[str] = field(default_factory=list)               # parallel to names — chosen once, at join
    sockets: dict[int, WebSocket] = field(default_factory=dict)    # seat -> socket
    game: Optional[Game] = None
    started: bool = False
    # Solo/practice room (main.py's _run_solo): every seat but `human_seat`
    # is auto-played server-side (_play_bots) — so there's no lobby, and
    # `sockets` only ever has the one entry, at key `human_seat`.
    solo: bool = False
    # Which seat the one real player landed at after _run_solo shuffles the
    # table (so "whoever's name you typed" doesn't always play first) —
    # meaningless outside a solo room, where every seat is a real person.
    human_seat: int = 0

    # Per-seat turn clock (main.py's _credit_turn_time): accumulated_seconds
    # holds every *completed* turn's duration, seat -> total seconds;
    # turn_clock_started is when the seat currently up (game.current) began
    # thinking, in time.monotonic() units (process-local — never sent to a
    # client as-is, only the elapsed difference is, see serialize.py). None
    # before a game exists.
    accumulated_seconds: dict[int, float] = field(default_factory=dict)
    turn_clock_started: Optional[float] = None

    def find_seat(self, name: str) -> Optional[int]:
        """Existing seat for `name`, if they've already joined (lobby or mid-game)."""
        try:
            return self.names.index(name)
        except ValueError:
            return None

    def can_join(self) -> bool:
        """Room for one more brand-new name — only before the game starts."""
        return not self.started and len(self.names) < MAX_SEATS

    def add_player(self, name: str, avatar: str) -> int:
        """Appends `name`/`avatar` as a new seat; caller must have checked can_join()."""
        seat = len(self.names)
        self.names.append(name)
        self.avatars.append(avatar)
        return seat

    async def broadcast(self, message: dict) -> None:
        for ws in list(self.sockets.values()):
            await ws.send_json(message)

    async def send_to(self, seat: int, message: dict) -> None:
        ws = self.sockets.get(seat)
        if ws is not None:
            await ws.send_json(message)


ROOMS: dict[str, Room] = {}


def get_or_create_room(room_id: str) -> Room:
    room = ROOMS.get(room_id)
    if room is None:
        room = Room(room_id=room_id)
        ROOMS[room_id] = room
    return room

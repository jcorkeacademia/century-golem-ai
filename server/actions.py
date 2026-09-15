"""Inbound client message -> engine Action, per CONTRACT.md 2/3."""

from __future__ import annotations

from century_engine import (
    Crystal,
    PlayCrystal,
    PlayUpgrade,
    PlayTrade,
    Acquire,
    Rest,
    Claim,
)

COLOR_FROM_KEY = {
    "Y": Crystal.YELLOW,
    "G": Crystal.GREEN,
    "B": Crystal.TURQUOISE,
    "M": Crystal.MAGENTA,
}


class MalformedAction(Exception):
    pass


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise MalformedAction(msg)


def _int_field(msg: dict, key: str):
    val = msg.get(key)
    _require(isinstance(val, int) and not isinstance(val, bool), f"'{key}' must be an int")
    return val


def _colors_field(msg: dict, key: str) -> tuple[Crystal, ...]:
    val = msg.get(key)
    _require(isinstance(val, list), f"'{key}' must be a list")
    _require(all(isinstance(c, str) and c in COLOR_FROM_KEY for c in val),
              f"'{key}' entries must be one of Y/G/B/M")
    return tuple(COLOR_FROM_KEY[c] for c in val)


def build_action(msg: dict):
    msg_type = msg.get("type")

    if msg_type == "play_crystal":
        return PlayCrystal(_int_field(msg, "hand_index"))

    if msg_type == "play_upgrade":
        hand_index = _int_field(msg, "hand_index")
        upgrades = _colors_field(msg, "upgrades")
        return PlayUpgrade(hand_index, upgrades)

    if msg_type == "play_trade":
        hand_index = _int_field(msg, "hand_index")
        times = _int_field(msg, "times")
        _require(times >= 1, "'times' must be >= 1")
        return PlayTrade(hand_index, times)

    if msg_type == "acquire":
        row_index = _int_field(msg, "row_index")
        payment = _colors_field(msg, "payment")
        _require(len(payment) == row_index, "'payment' length must equal row_index")
        return Acquire(row_index, payment)

    if msg_type == "rest":
        return Rest()

    if msg_type == "claim":
        return Claim(_int_field(msg, "row_index"))

    raise MalformedAction(f"unknown action type {msg_type!r}")

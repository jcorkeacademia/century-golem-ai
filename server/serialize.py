"""Game -> outbound `state` message, per CONTRACT.md 1a."""

from __future__ import annotations

import time
from collections import Counter
from typing import Iterable

from century_engine import (
    Crystal,
    CrystalCard,
    UpgradeCard,
    TradeCard,
    PointCard,
    Token,
    Game,
)

from rooms import Room
from card_art_index import art_url_for

COLOR_KEY = {
    Crystal.YELLOW: "Y",
    Crystal.GREEN: "G",
    Crystal.TURQUOISE: "B",
    Crystal.MAGENTA: "M",
}


def _bundle(pairs: Iterable[tuple[Crystal, int]]) -> dict:
    out = {"Y": 0, "G": 0, "B": 0, "M": 0}
    for color, n in pairs:
        out[COLOR_KEY[color]] = n
    return out


def _counter_bundle(counter: Counter) -> dict:
    out = {"Y": 0, "G": 0, "B": 0, "M": 0}
    for color, n in counter.items():
        out[COLOR_KEY[color]] = n
    return out


def _caravan_bundle(caravan: list[int]) -> dict:
    return {COLOR_KEY[Crystal(i)]: n for i, n in enumerate(caravan)}


def merchant_card_to_dict(
    card, *, slot: int | None = None, crystals_on_card: Counter | None = None, times_played: int | None = None
) -> dict:
    if isinstance(card, CrystalCard):
        d = {
            "kind": "crystal",
            "name": card.name,
            "gain": _bundle(card.gain),
            "steps": None,
            "cost": None,
            "trade_gain": None,
        }
    elif isinstance(card, UpgradeCard):
        d = {
            "kind": "upgrade",
            "name": card.name,
            "gain": None,
            "steps": card.steps,
            "cost": None,
            "trade_gain": None,
        }
    elif isinstance(card, TradeCard):
        d = {
            "kind": "trade",
            "name": card.name,
            "gain": None,
            "steps": None,
            "cost": _bundle(card.cost),
            "trade_gain": _bundle(card.gain),
        }
    else:
        raise TypeError(f"unknown merchant card type {card!r}")

    d["art"] = art_url_for(card)
    if slot is not None:
        d = {"slot": slot, **d}
    if crystals_on_card is not None:
        d["crystals_on_card"] = _counter_bundle(crystals_on_card)
    # Only ever set once the game is over (see game_to_state) — never
    # threaded through live snapshots, both because it isn't meaningful yet
    # (a card mid-hand could still be replayed after another Rest) and
    # because computing it is a real event_log scan, not a cheap field.
    if times_played is not None:
        d["times_played"] = times_played
    return d


def hand_card_to_dict(card, hand_index: int, *, times_played: int | None = None) -> dict:
    d = merchant_card_to_dict(card, times_played=times_played)
    return {"hand_index": hand_index, **d}


def golem_card_to_dict(card: PointCard, slot: int | None = None) -> dict:
    d = {
        "name": card.name,
        "points": card.points,
        "cost": _bundle(card.cost),
        "art": art_url_for(card),
    }
    if slot is not None:
        d = {"slot": slot, **d}
    return d


def game_to_state(room: Room, viewer_seat: int | None) -> dict:
    game: Game = room.game
    assert game is not None

    golem_row = [
        golem_card_to_dict(pc, slot)
        for slot, pc in enumerate(game.point_row)
        if pc is not None
    ]

    merchant_row = [
        merchant_card_to_dict(card, slot=slot, crystals_on_card=game.row_crystals[slot])
        for slot, card in enumerate(game.merchant_row)
        if card is not None
    ]

    # Scan the two pile slots for which token kind currently lives where
    # (silver slides up to slot 0 once copper empties — see _reflow_tokens).
    tokens = {
        "copper": {"slot": 0, "count": 0, "value": int(Token.COPPER)},
        "silver": {"slot": 1, "count": 0, "value": int(Token.SILVER)},
    }
    for slot, pile in enumerate(game.point_tokens):
        if not pile:
            continue
        kind = pile[0]
        key = "copper" if kind == Token.COPPER else "silver"
        tokens[key] = {"slot": slot, "count": len(pile), "value": int(kind)}

    # Only computed once the game is over, and only ever shown on demand
    # (PlayerDetailOverlay, not the live board — see MerchantCard.jsx's
    # showTimesPlayed) — game.times_played() walks the whole event_log per
    # card, cheap for one end-of-game snapshot, wasteful to redo on every
    # live broadcast.
    def _times_played(card):
        return game.times_played(card) if game.game_over else None

    # Per-seat accumulated turn-clock (main.py's _credit_turn_time) — only
    # *completed* turns are folded in here; the seat currently up
    # (game.current) has its still-ticking turn reported separately, below,
    # as a snapshot-time elapsed figure (never a raw time.monotonic() value,
    # which means nothing to a client and nothing across a server restart).
    # The client adds its own wall-clock delta since receiving this message
    # on top, for a live-ticking display (see web/src/components/TurnClock.jsx).
    current_turn_elapsed_seconds = (
        time.monotonic() - room.turn_clock_started if room.turn_clock_started is not None else 0.0
    )

    players = []
    for seat, p in enumerate(game.players):
        players.append({
            "seat": seat,
            "name": p.name,
            "avatar": room.avatars[seat] if seat < len(room.avatars) else None,
            "caravan": _caravan_bundle(p.caravan),
            "caravan_total": p.total_crystals(),
            "hand": [hand_card_to_dict(c, i, times_played=_times_played(c)) for i, c in enumerate(p.hand)],
            "played": [merchant_card_to_dict(c, times_played=_times_played(c)) for c in p.played],
            "golems": [golem_card_to_dict(pc) for pc in p.point_cards],
            "golem_count": len(p.point_cards),
            "golem_points": sum(pc.points for pc in p.point_cards),
            "tokens": {
                "copper": sum(1 for t in p.tokens if t == Token.COPPER),
                "silver": sum(1 for t in p.tokens if t == Token.SILVER),
            },
            "score": p.score(),
            "turn_seconds": room.accumulated_seconds.get(seat, 0.0),
        })

    return {
        "type": "state",
        "room": room.room_id,
        "you": viewer_seat,
        "current": game.current,
        "first_player": 0,
        "win_target": game.win_target,
        "game_over": game.game_over,
        "winner": game.winner(),
        "current_turn_elapsed_seconds": current_turn_elapsed_seconds,
        "shared": {
            "golem_row": golem_row,
            "golem_deck_count": len(game.point_deck),
            "merchant_row": merchant_row,
            "merchant_deck_count": len(game.merchant_deck),
            "tokens": tokens,
        },
        "players": players,
        # No server-side partial-action state exists yet: acquire/upgrade
        # answers ride on the same action that opens them (see CONTRACT.md
        # 1b/2), and caravan_discard needs an engine change we're not making.
        # So this is always null for now.
        "pending_decision": None,
    }

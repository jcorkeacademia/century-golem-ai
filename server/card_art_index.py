"""
Card art -> URL index, built once at import time (see CARD_ART_HANDOVER.md §5).

card_art.art_for() is a filesystem lookup; calling it per-request would touch
disk on every state broadcast. Instead we resolve every card in the compendium
to a URL exactly once here, keyed by card_art.card_signature() (content-based,
order-independent — see card_art.py's module docstring for why).
"""

from __future__ import annotations

from pathlib import Path

import engine_path  # noqa: F401  (sys.path + compendium plug-in, must run first)
import card_art
import century_cards as cards

_ALL_CARDS = cards.POINT_CARDS + cards.MERCHANT_CARDS + cards.STARTING_CARDS


def _url_for(path: Path | None) -> str | None:
    if path is None:
        return None
    if path.parent == card_art.GOLEM_DIR:
        return f"/static/golems/{path.name}"
    if path.parent == card_art.MERCH_DIR:
        return f"/static/merchants/{path.name}"
    return None


ART_URL: dict[tuple, str | None] = {
    card_art.card_signature(c): _url_for(card_art.art_for(c)) for c in _ALL_CARDS
}


def art_url_for(card) -> str | None:
    """URL for an engine card's art, or None if unmatched/unrendered."""
    return ART_URL.get(card_art.card_signature(card))

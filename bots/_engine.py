"""The one place that knows how to import the engine.

`engine/century_cards.py` imports the engine flat (`from century_engine
import ...`) and there is no `engine/__init__.py`, so `import
engine.century_cards` fails from the repo root. Rather than renaming engine
modules or rewriting their imports — CLAUDE.md warns against the first and
the Step 1 brief doesn't sanction the second — this module does the same
`sys.path` insert `server/engine_path.py` has always done, once, in one file.

Every bot module imports from here:

    from bots._engine import Game, Crystal, Claim, IllegalAction, ...

Decks: the engine now defaults to the full compendium, so there is nothing to
swap in. MERCHANT_CARDS / POINT_CARDS are re-exported for code that needs to
reason about deck *composition* (which is public information); reading the
*order* of a live game's decks is cheating — see BOT_IMPLEMENTATION_PROMPT §0.2.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

from century_engine import (  # noqa: E402
    CARAVAN_LIMIT,
    Acquire,
    Action,
    Claim,
    Crystal,
    CrystalCard,
    Game,
    IllegalAction,
    MerchantCard,
    PlayCrystal,
    PlayTrade,
    PlayUpgrade,
    Player,
    PointCard,
    Rest,
    SAMPLE_MERCHANT_DECK,
    SAMPLE_POINT_DECK,
    Token,
    TradeCard,
    UpgradeCard,
    crystal_endgame_value,
)
from century_cards import MERCHANT_CARDS, POINT_CARDS, STARTING_CARDS  # noqa: E402

__all__ = [
    "CARAVAN_LIMIT", "Acquire", "Action", "Claim", "Crystal", "CrystalCard",
    "Game", "IllegalAction", "MERCHANT_CARDS", "MerchantCard", "POINT_CARDS",
    "PlayCrystal", "PlayTrade", "PlayUpgrade", "Player", "PointCard", "Rest",
    "SAMPLE_MERCHANT_DECK", "SAMPLE_POINT_DECK", "STARTING_CARDS", "Token",
    "TradeCard", "UpgradeCard", "crystal_endgame_value",
]

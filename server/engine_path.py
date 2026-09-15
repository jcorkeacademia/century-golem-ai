"""
Wires this server up to the engine folder without touching anything under
engine/. Import this module first (main.py does) before importing
century_engine anywhere else.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

import century_engine as engine  # noqa: E402
import century_cards as cards  # noqa: E402

# The engine ships with a tiny built-in sample deck. Swap in the full
# transcribed compendium so real games use the real cards. This mutates the
# engine module's data at runtime only — engine/*.py itself is untouched.
engine.MERCHANT_DECK = cards.MERCHANT_CARDS
engine.POINT_DECK = cards.POINT_CARDS

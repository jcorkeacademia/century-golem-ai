"""
Wires this server up to the engine folder without touching anything under
engine/. Import this module first (main.py does) before importing
century_engine anywhere else.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_ENGINE_DIR = _ROOT / "engine"
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))
# The repo root too, so `bots` (the tuned practice-mode opponent) can be
# imported. Both this and bots/_engine.py add engine/ the same way and
# import `century_engine` under the same name, so there is exactly one
# engine module in the process and isinstance checks across the two still
# hold.
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import century_engine as engine  # noqa: E402
import century_cards as cards  # noqa: E402

# The engine ships with a tiny built-in sample deck. Swap in the full
# transcribed compendium so real games use the real cards. This mutates the
# engine module's data at runtime only — engine/*.py itself is untouched.
engine.MERCHANT_DECK = cards.MERCHANT_CARDS
engine.POINT_DECK = cards.POINT_CARDS

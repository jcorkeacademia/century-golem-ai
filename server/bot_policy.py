"""Which bot plays the computer seats in practice mode.

Three difficulties, measured against each other rather than guessed at
(see `results/REPORT.md` and `bots/API_NOTES.md`):

    easy    claim a golem if you can, otherwise move at random. This is the
            policy practice mode shipped with. It loses ~100% of games to
            `medium`.
    medium  GreedyBot — fixed rules, no search. Beats `easy` essentially
            always, and loses ~98% to `hard`.
    hard    the tuned bot: scores every legal move as a weighted sum of
            twelve features, with separate early- and late-game weights
            found by evolutionary search over ~49,000 self-play games.

`hard` is the default because it is the one the project was built to
produce. It is genuinely strong — it beats the hand-tuned bot 81.8% and the
rule-based one 97.9% — so `medium` exists for a reasonable game and `easy`
for a gentle one.

FAILING SAFE. Practice mode must keep working even if the bots package or
its weight files are missing or broken — a server that will not start a
solo game because a JSON file moved is worse than one that plays a weaker
bot. Every level falls back to `easy`, once, with a warning on the log.
"""

from __future__ import annotations

import logging
import random
from typing import Callable, Optional

import engine_path  # noqa: F401  (sys.path + compendium, must run first)
from century_engine import Action, Claim, Game

log = logging.getLogger("century.bots")

EASY, MEDIUM, HARD = "easy", "medium", "hard"
DIFFICULTIES = (EASY, MEDIUM, HARD)
DEFAULT_DIFFICULTY = HARD

# Which weights `hard` plays. tuned_split is the Step 6b bot: 22 phase-split
# parameters, beats the single-weight version 54.7% over 10,000 games.
HARD_WEIGHTS = "tuned_split"

_loaded: dict[str, object] = {}      # difficulty -> a factory, or None if unavailable
_warned: set[str] = set()


def _naive(game: Game) -> Optional[Action]:
    """The original practice-mode policy: claim if you can, else anything.

    Kept verbatim as `easy` rather than replaced, so nobody who liked the
    old practice game loses it — and so there is always something to fall
    back to that depends on nothing but the engine.
    """
    acts = game.legal_actions()
    if not acts:
        return None
    claim = next((a for a in acts if isinstance(a, Claim)), None)
    return claim or game.rng.choice(acts)


def _build_factory(difficulty: str) -> Optional[Callable[[Game], object]]:
    """Import the bots package lazily and return a bot-maker, or None.

    Lazy because importing `bots` pulls in numpy and the whole feature set;
    a server that only ever hosts human games should not pay for that at
    startup.
    """
    try:
        # The bots package lives at the repo root, which engine_path puts on
        # sys.path alongside engine/.
        from bots.bots import GreedyBot, WeightedBot
        from bots.features import Scales, Weights
    except Exception as exc:                     # pragma: no cover - env dependent
        log.warning("bot difficulty %r unavailable (%s: %s); using easy",
                    difficulty, type(exc).__name__, exc)
        return None

    if difficulty == MEDIUM:
        return lambda game: GreedyBot(rng=game.rng, name="medium")

    try:
        weights = Weights.load(HARD_WEIGHTS)
        scales = Scales.load()
        if not scales.values:
            raise FileNotFoundError("feature_scales.json is empty")
    except Exception as exc:                     # pragma: no cover - env dependent
        log.warning("hard bot weights %r unavailable (%s: %s); using easy",
                    HARD_WEIGHTS, type(exc).__name__, exc)
        return None

    # Weights and scales are immutable and shared; the bot itself is built
    # per call because it carries RNG state, and reusing one would make a
    # move depend on what was played before it.
    return lambda game: WeightedBot(weights, scales, rng=game.rng, name="hard")


def _factory(difficulty: str) -> Optional[Callable[[Game], object]]:
    if difficulty not in _loaded:
        _loaded[difficulty] = _build_factory(difficulty)
    return _loaded[difficulty]


def normalise(difficulty: Optional[str]) -> str:
    """Accept whatever the client sent; fall back to the default quietly."""
    d = (difficulty or "").strip().lower()
    return d if d in DIFFICULTIES else DEFAULT_DIFFICULTY


def pick_action(game: Game, difficulty: str = DEFAULT_DIFFICULTY) -> Optional[Action]:
    """One bot turn. Returns None only when there is no legal move at all.

    The returned action still goes through `Game.apply_action`, exactly like
    a move typed by a human — the bot chooses, the engine decides whether
    it was allowed.
    """
    difficulty = normalise(difficulty)
    if difficulty == EASY:
        return _naive(game)

    make = _factory(difficulty)
    if make is None:
        if difficulty not in _warned:
            _warned.add(difficulty)
            log.warning("falling back to the easy bot for difficulty %r", difficulty)
        return _naive(game)

    try:
        action = make(game).choose(game)
    except Exception as exc:                     # pragma: no cover - defensive
        # A crashing bot must not take the game down with it. One warning
        # per difficulty, then quietly play on at easy.
        if difficulty not in _warned:
            _warned.add(difficulty)
            log.warning("bot %r raised (%s: %s); using easy from here",
                        difficulty, type(exc).__name__, exc, exc_info=True)
        _loaded[difficulty] = None
        return _naive(game)

    return action if action is not None else _naive(game)

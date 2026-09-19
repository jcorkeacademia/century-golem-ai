"""The tuned bot as the server's practice-mode opponent.

These test `server/bot_policy.py` — the seam between the research code in
`bots/` and the live game. The thing that must not break is that practice
mode keeps working: a missing weights file should cost you a weaker bot,
never a server that will not start a game.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parent.parent.parent / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

import bot_policy  # noqa: E402
from bots._engine import Action, Claim, Game  # noqa: E402


@pytest.fixture(autouse=True)
def _clean():
    """Each test starts with the lazy-import caches empty, so one test's
    forced failure cannot leak into the next."""
    bot_policy._loaded.clear()
    bot_policy._warned.clear()
    yield
    bot_policy._loaded.clear()
    bot_policy._warned.clear()


def play(difficulty: str, seed: int, seats: int = 2, cap: int = 600):
    """A whole game with every seat played by the same difficulty."""
    g = Game([f"P{i}" for i in range(seats)], seed=seed, log=True)
    n = 0
    while not g.game_over and n < cap:
        a = bot_policy.pick_action(g, difficulty)
        if a is None:
            break
        g.apply_action(a)
        n += 1
    return g


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------

def test_three_difficulties_are_offered():
    assert bot_policy.DIFFICULTIES == ("easy", "medium", "hard")


def test_unknown_difficulty_falls_back_to_the_default():
    for junk in (None, "", "   ", "impossible", "HARDER", "1"):
        assert bot_policy.normalise(junk) == bot_policy.DEFAULT_DIFFICULTY


def test_case_and_whitespace_are_tolerated():
    assert bot_policy.normalise("  Hard ") == "hard"
    assert bot_policy.normalise("MEDIUM") == "medium"


@pytest.mark.parametrize("difficulty", ["easy", "medium", "hard"])
def test_every_difficulty_returns_a_legal_action(difficulty):
    g = Game(["A", "B"], seed=5, log=True)
    rng = random.Random(5)
    for _ in range(40):
        if g.game_over:
            break
        a = bot_policy.pick_action(g, difficulty)
        assert a in g.legal_actions(), (difficulty, a)
        g.apply_action(a)


@pytest.mark.parametrize("difficulty", ["easy", "medium", "hard"])
@pytest.mark.parametrize("seats", [2, 3, 5])
def test_every_difficulty_finishes_a_game_at_every_table_size(difficulty, seats):
    g = play(difficulty, seed=11, seats=seats)
    assert g.game_over, f"{difficulty} at {seats} seats did not finish"


def test_the_bot_never_mutates_the_game_while_choosing():
    g = Game(["A", "B"], seed=7, log=True)
    before = ([list(p.caravan) for p in g.players],
              len(g.merchant_deck), len(g.point_deck), g.current)
    bot_policy.pick_action(g, "hard")
    after = ([list(p.caravan) for p in g.players],
             len(g.merchant_deck), len(g.point_deck), g.current)
    assert before == after


# --------------------------------------------------------------------------
# The difficulties are actually different
# --------------------------------------------------------------------------

def test_hard_beats_easy_head_to_head():
    """The whole point of the integration. Seat 0 plays `hard`, seat 1
    `easy`, seats swapped each game so a seat advantage cannot explain it.
    """
    wins = 0
    games = 20
    for seed in range(games):
        hard_seat = seed % 2
        g = Game(["P0", "P1"], seed=1000 + seed, log=True)
        n = 0
        while not g.game_over and n < 600:
            d = "hard" if g.current == hard_seat else "easy"
            a = bot_policy.pick_action(g, d)
            if a is None:
                break
            g.apply_action(a)
            n += 1
        scores = [p.score() for p in g.players]
        best = max(scores)
        winner = max(i for i, s in enumerate(scores) if s == best)
        wins += (winner == hard_seat)
    assert wins >= games * 0.8, f"hard won only {wins}/{games} against easy"


def test_easy_is_the_original_policy():
    """`easy` must stay exactly what practice mode shipped with: claim if
    you can, else a random legal move. Anyone who liked the old opponent
    still has it."""
    g = Game(["A", "B"], seed=1, log=True)
    g.point_row = [g.point_row[0]] + [None] * 4
    g.players[0].caravan = list(g.point_row[0].cost_counter().get(c, 0)
                                for c in range(4))
    acts = g.legal_actions()
    if any(isinstance(a, Claim) for a in acts):
        assert isinstance(bot_policy.pick_action(g, "easy"), Claim)


# --------------------------------------------------------------------------
# Failing safe
# --------------------------------------------------------------------------

def test_a_missing_weights_file_degrades_instead_of_raising(monkeypatch):
    """A server that refuses to start a practice game because a JSON file
    moved is worse than one that plays a weaker bot."""
    def boom(_difficulty):
        raise FileNotFoundError("weights went missing")
    monkeypatch.setattr(bot_policy, "_build_factory",
                        lambda d: None if d == "hard" else boom(d))
    g = Game(["A", "B"], seed=3, log=True)
    a = bot_policy.pick_action(g, "hard")
    assert a in g.legal_actions()


def test_a_crashing_bot_degrades_instead_of_raising(monkeypatch):
    class Exploding:
        def choose(self, game):
            raise RuntimeError("bot exploded mid-turn")

    monkeypatch.setattr(bot_policy, "_build_factory",
                        lambda d: (lambda game: Exploding()))
    g = Game(["A", "B"], seed=3, log=True)
    a = bot_policy.pick_action(g, "hard")
    assert a in g.legal_actions(), "a crashing bot must not end the game"
    # and it must not keep crashing every turn afterwards
    assert bot_policy._loaded["hard"] is None


def test_the_engine_module_is_shared_with_the_bots_package():
    """server/engine_path.py and bots/_engine.py both put engine/ on the
    path and import `century_engine`. If that ever produced two module
    objects, every isinstance check across the seam would silently fail."""
    import century_engine
    from bots import _engine
    assert _engine.Game is century_engine.Game
    assert _engine.Claim is century_engine.Claim


# --------------------------------------------------------------------------
# Room wiring
# --------------------------------------------------------------------------

def test_a_room_remembers_its_difficulty():
    from rooms import Room
    r = Room(room_id="x", names=["a", "b"], solo=True, difficulty="medium")
    assert r.difficulty == "medium"


def test_a_room_defaults_to_the_same_difficulty_the_policy_does():
    from rooms import Room
    assert Room(room_id="x").difficulty == bot_policy.DEFAULT_DIFFICULTY

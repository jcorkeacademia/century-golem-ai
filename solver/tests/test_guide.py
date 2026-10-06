"""Guided TEST rooms: the logic behind the red outline.

The server side (server/guided.py) was also driven over a real websocket;
these pin the parts that decide what gets outlined.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from bots._engine import Discard, Rest
from solver.fastclone import fast_clone
from solver.guide import Guide, guided_seed, new_guided_game, replan_worker
from solver.plans import action_to_json
from solver.solo import turns_in

SERVER = Path(__file__).resolve().parent.parent.parent / "server"


def _guided(seed):
    """A guided game and its guide, with a plan in hand: the saved one, or —
    when there is none that follows the rules — a quick one, as the server
    would compute. Keeps these tests independent of the results files."""
    game = new_guided_game(seed, "You")
    guide = Guide.start(seed, game)
    if guide.replanning:
        guide.adopt(replan_worker(seed, "You", [], width=20))
    return game, guide


def _step(game, guide, action):
    before = fast_clone(game)
    game.apply_action(action)
    guide.observe(before, action, game)
    guide.resolve_discards(game)


@pytest.mark.parametrize("code,seed", [("TEST", 0), ("test42", 42), ("TEST499", 499),
                                       ("TESTX", None), ("ABCD", None), ("XTEST", None),
                                       ("", None)])
def test_room_codes(code, seed):
    assert guided_seed(code) == seed


def test_the_server_reads_room_codes_the_same_way():
    if str(SERVER) not in sys.path:
        sys.path.insert(0, str(SERVER))
    import engine_path  # noqa: F401
    import guided
    for code in ("TEST", "test42", "TEST499", "TESTX", "ABCD", "XTEST", ""):
        assert guided.seed_for(code) == guided_seed(code)


def test_following_every_hint_wins_in_the_planned_turns():
    game, guide = _guided(0)
    planned = guide.hint(game)["planned_total"]
    while not game.game_over:
        _step(game, guide, guide.next_action())
    assert guide.turns_taken == planned
    assert guide.replans == 0
    assert guide.hint(game)["status"] == "finished"


def test_a_planned_discard_is_applied_for_the_player():
    """The client has no discard prompt, so when a planned move overflows the
    caravan the guide must settle it with the plan's own choice."""
    for seed in range(40):
        game, guide = _guided(seed)
        discards_planned = sum(isinstance(a, Discard) for a in guide.plan)
        if discards_planned:
            break
    else:
        pytest.skip("no plan among the first 40 seeds overflows the caravan")
    while not game.game_over:
        _step(game, guide, guide.next_action())
    assert sum(isinstance(a, Discard) for a in guide.history) == discards_planned


def test_leaving_the_plan_asks_for_a_replan_and_a_new_plan_finishes():
    game = new_guided_game(3, "You")
    guide = Guide.start(3, game)
    # follow the plan until resting is legal and is NOT the planned move
    while not (game.players[0].played and not isinstance(guide.next_action(), Rest)):
        _step(game, guide, guide.next_action())
        assert not guide.replanning
    _step(game, guide, Rest())                     # not what the plan says
    hint = guide.hint(game)
    assert guide.replanning and hint["status"] == "replanning"
    assert hint["action"] is None and "recalculated" in hint["note"]

    guide.adopt(replan_worker(3, "You", [action_to_json(a) for a in guide.history], width=10))
    assert guide.replans == 1 and not guide.replanning
    while not game.game_over:
        _step(game, guide, guide.next_action())
    assert guide.replans == 1                      # the new plan was followed


def test_hints_name_the_element_to_outline():
    game, guide = _guided(0)
    kinds = set()
    while not game.game_over:
        hint = guide.hint(game)
        act = hint["action"]
        kinds.add(act["kind"])
        if act["kind"] == "play":
            assert 0 <= act["hand_index"] < len(game.players[0].hand)
        if act["kind"] in ("acquire", "claim"):
            assert 0 <= act["row_index"] < 6
        if act["kind"] == "acquire":
            assert len(act["payment"]) == act["row_index"]
        assert hint["text"] and "**" not in hint["text"]
        _step(game, guide, guide.next_action())
    assert {"play", "acquire", "claim", "rest"} <= kinds


def test_a_seed_without_a_saved_plan_starts_by_planning():
    game = new_guided_game(900_000, "You")
    guide = Guide.start(900_000, game)
    assert guide.replanning and guide.plan == ()
    plan = replan_worker(900_000, "You", [], width=5)
    guide.adopt(plan)
    assert guide.replans == 0                      # the first plan is not a re-plan
    assert turns_in(guide.plan) > 0


# ---------------------------------------------------------------------------
# The full-upgrade house rule: the web client only confirms an upgrade that
# uses every step, so no plan may do less
# ---------------------------------------------------------------------------

from bots._engine import Crystal, PlayUpgrade  # noqa: E402
from solver.improve import beam  # noqa: E402
from solver.plans import partial_upgrades  # noqa: E402
from solver.search import playable_moves, uses_every_step  # noqa: E402

Y = Crystal.YELLOW


def test_an_upgrade_must_use_every_step():
    game = new_guided_game(0, "You")            # hand: Create 2, Upgrade 2
    up = next(i for i, c in enumerate(game.player.hand) if c.name == "Upgrade 2")
    assert not uses_every_step(game, PlayUpgrade(up, (Y,)))
    assert uses_every_step(game, PlayUpgrade(up, (Y, Y)))
    assert uses_every_step(game, Rest())


def test_playable_moves_offer_only_full_upgrades():
    game = new_guided_game(0, "You")
    upgrades = [a for a in playable_moves(game) if isinstance(a, PlayUpgrade)]
    assert upgrades and all(len(a.upgrades) == 2 for a in upgrades)
    assert any(isinstance(a, PlayUpgrade) and len(a.upgrades) == 1
               for a in game.legal_actions()), "the engine itself still allows fewer"


def test_new_plans_follow_the_rule():
    plan = beam(15, width=20)
    assert partial_upgrades(new_guided_game(15, "You"), plan.actions) == []


def test_a_saved_plan_breaking_the_rule_is_not_used(monkeypatch):
    import solver.guide as guide_mod
    game = new_guided_game(0, "You")
    up = next(i for i, c in enumerate(game.player.hand) if c.name == "Upgrade 2")
    fake = (PlayUpgrade(up, (Y,)),)             # a one-step upgrade
    assert partial_upgrades(game, fake) == [1]
    monkeypatch.setattr(guide_mod, "best_saved", lambda seed: (fake, "test"))
    monkeypatch.setattr(guide_mod, "_replays", lambda game, actions: True)
    guide = Guide.start(0, game)
    assert guide.replanning and "full-upgrade" in guide.source

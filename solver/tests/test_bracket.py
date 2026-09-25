"""The bracket's saved plans must round-trip and replay, and a bad one must
be rejected — the upper bound is only as good as its replay."""

from __future__ import annotations

import pytest

from solver.bracket import action_from_json, action_to_json, replay_saved
from solver.greedy import upper_bound


def test_every_action_kind_round_trips():
    plan = upper_bound(0)
    kinds = {type(a).__name__ for a in plan.actions}
    assert {"PlayCrystal", "Acquire", "Rest", "Claim"} <= kinds
    assert tuple(action_from_json(action_to_json(a)) for a in plan.actions) == plan.actions


def test_discards_round_trip():
    from bots._engine import Discard
    d = Discard((1, 0, 2, 0))
    assert action_from_json(action_to_json(d)) == d


def test_a_saved_plan_replays_to_its_turns():
    plan = upper_bound(3)
    assert replay_saved(3, [action_to_json(a) for a in plan.actions]) == plan.turns


def test_a_truncated_plan_is_rejected():
    plan = upper_bound(3)
    with pytest.raises(AssertionError):
        replay_saved(3, [action_to_json(a) for a in plan.actions[:-1]])

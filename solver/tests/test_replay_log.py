"""The plan log must show every turn exactly once, from a replayed plan."""

from __future__ import annotations

from solver.greedy import upper_bound
from solver.replay_log import log


def test_one_section_per_turn_and_a_win_at_the_end():
    plan = upper_bound(0)
    text = log(0, plan, "test")
    assert text.count("\n## Turn ") == plan.turns
    assert text.count("- **Move:** ") == plan.turns
    assert f"Golems claimed (6/6)" in text
    assert "## At a glance" in text


def test_discards_are_shown_as_part_of_their_turn():
    plan = upper_bound(0)
    discards = sum(1 for a in plan.actions if type(a).__name__ == "Discard")
    text = log(0, plan, "test")
    # once in the turn-by-turn section, once in the at-a-glance list
    assert text.count("*same turn:* Discard") == 2 * discards

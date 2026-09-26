"""describe() must account for every move of the plan it describes."""

from __future__ import annotations

from solver.greedy import upper_bound
from solver.study import describe


def test_the_record_accounts_for_the_whole_plan():
    plan = upper_bound(2)
    rec = describe(2, plan)
    assert rec["turns"] == plan.turns
    assert len(rec["claims"]) == 6
    assert [c["turn"] for c in rec["claims"]] == sorted(c["turn"] for c in rec["claims"])
    assert rec["claims"][-1]["turn"] == plan.turns          # the last claim wins
    assert len(rec["bought"]) == rec["mix"].get("Acquire", 0)
    plays = sum(rec["mix"].get(k, 0) for k in ("PlayCrystal", "PlayUpgrade", "PlayTrade"))
    assert sum(rec["played"].values()) == plays
    assert sum(rec["mix"].values()) == len(plan.actions)


def test_every_bought_card_was_offered():
    rec = describe(4, upper_bound(4))
    assert {b["card"] for b in rec["bought"]} <= set(rec["offered"])

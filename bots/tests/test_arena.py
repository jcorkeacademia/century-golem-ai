"""Step 5: the arena.

Everything downstream is a claim about a win rate, so these tests are mostly
about the two devices that make a win rate trustworthy — paired seeds and seat
rotation — plus the plumbing that makes multiprocessing work on a spawn-only
platform.
"""
from __future__ import annotations

import json

import pytest

from bots.arena import (
    ArenaResult,
    build_bot,
    parse_spec,
    run_arena,
    save,
    spec_label,
    wilson,
)
from bots.bots import GreedyBot, RandomBot, WeightedBot, play_game


# --------------------------------------------------------------------------
# Specs
# --------------------------------------------------------------------------

def test_parse_spec_bare():
    assert parse_spec("greedy") == ("greedy", {})


def test_parse_spec_with_options():
    assert parse_spec("greedy:build_until=3") == ("greedy", {"build_until": 3})
    head, opts = parse_spec("handset_v1:samples=3")
    assert head == "handset_v1" and opts == {"samples": 3}


def test_parse_spec_multiple_options():
    _, opts = parse_spec("greedy:build_until=3,name=x")
    assert opts == {"build_until": 3, "name": "x"}


def test_build_bot_types():
    assert isinstance(build_bot("random", 0), RandomBot)
    assert isinstance(build_bot("greedy", 0), GreedyBot)
    assert isinstance(build_bot("handset_v1", 0), WeightedBot)


def test_build_bot_applies_options():
    assert build_bot("greedy:build_until=9", 1).build_until == 9


def test_build_bot_returns_a_fresh_bot_every_time():
    """Bots carry RNG state, so caching them would make a game's outcome
    depend on what ran before it in that worker. Only the weights file is
    cached."""
    a, b = build_bot("greedy", 5), build_bot("greedy", 5)
    assert a is not b
    from bots.arena import _WEIGHTS_CACHE
    _WEIGHTS_CACHE.clear()
    w1 = build_bot("handset_v1", 1)
    w2 = build_bot("handset_v1", 1)
    assert w1 is not w2
    assert w1.weights is w2.weights        # the expensive part is shared


def test_spec_label_shows_options():
    assert spec_label("greedy") == "greedy"
    assert spec_label("greedy:build_until=3") == "greedy[build_until=3]"


def test_specs_must_be_picklable():
    """The whole reason bots are described by strings: this platform has no
    fork, so anything crossing into a worker has to pickle."""
    import pickle
    task = (["greedy", "random"], 2, 7, 0, 1000)
    assert pickle.loads(pickle.dumps(task)) == task


# --------------------------------------------------------------------------
# Wilson interval
# --------------------------------------------------------------------------

def test_wilson_brackets_the_rate():
    lo, hi = wilson(50, 100)
    assert lo < 0.5 < hi


def test_wilson_stays_inside_zero_and_one():
    assert wilson(0, 10)[0] == 0.0
    assert wilson(10, 10)[1] <= 1.0
    assert wilson(0, 3)[1] <= 1.0


def test_wilson_narrows_with_sample_size():
    small = wilson(5, 10)
    large = wilson(500, 1000)
    assert (large[1] - large[0]) < (small[1] - small[0])


def test_wilson_of_no_games_is_maximally_uncertain():
    assert wilson(0, 0) == (0.0, 1.0)


# --------------------------------------------------------------------------
# Seat rotation and pairing
# --------------------------------------------------------------------------

@pytest.mark.parametrize("n_players", [2, 3, 4, 5])
def test_every_bot_plays_every_seat_equally_often(n_players):
    specs = ["greedy"] + ["random"] * (n_players - 1)
    res = run_arena(specs, n_players, range(4), workers=1)
    assert res.games == 4 * n_players
    for st in res.stats:
        assert sorted(st.games_by_seat) == list(range(n_players))
        assert len(set(st.games_by_seat.values())) == 1, st.games_by_seat


def test_no_rotation_pins_every_bot_to_one_seat():
    res = run_arena(["greedy", "random"], 2, range(5), rotate_seats=False, workers=1)
    assert res.games == 5
    for st in res.stats:
        assert len(st.games_by_seat) == 1


def test_seat_rotation_cancels_the_seat_advantage():
    """Identical bots in every seat should come out near even.

    Seat 0 starts with 3 yellow, seats 1-2 with 4, and the engine breaks score
    ties toward the highest seat — so without rotation this is not close.
    """
    res = run_arena(["greedy", "greedy"], 2, range(60), workers=1)
    lo, hi = res.stats[0].ci
    assert lo < 0.5 < hi, res.summary()


def test_paired_seeds_mean_both_bots_see_the_same_decks():
    res = run_arena(["greedy", "random"], 2, range(6), workers=1)
    assert sorted(res.seeds) == list(range(6))
    assert res.games == 12       # 6 seeds x 2 rotations


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------

def test_win_counts_sum_to_one_winner_per_game():
    res = run_arena(["greedy", "random"], 2, range(8), workers=1)
    assert sum(st.wins for st in res.stats) == res.games


def test_greedy_beats_random_in_the_arena():
    res = run_arena(["greedy", "random"], 2, range(10), workers=1)
    assert res.stats[0].win_rate > 0.9
    assert res.stats[0].ci[0] > 0.5


def test_duplicate_specs_get_distinct_labels():
    res = run_arena(["greedy", "greedy"], 2, range(3), workers=1)
    assert res.labels == ["greedy#1", "greedy#2"]
    assert len({st.label for st in res.stats}) == 2


def test_points_per_golem_is_total_over_total():
    res = run_arena(["greedy", "random"], 2, range(6), workers=1)
    st = res.stats[0]
    assert st.points_per_golem == pytest.approx(
        sum(st.golem_points) / sum(st.golems))


def test_points_per_golem_survives_a_bot_that_claims_nothing():
    res = run_arena(["greedy", "random"], 2, range(4), workers=1)
    for st in res.stats:
        assert st.points_per_golem >= 0.0      # no ZeroDivisionError


def test_ended_share_is_tracked():
    """The engine records that the end was triggered, not by whom."""
    res = run_arena(["greedy", "random"], 2, range(8), workers=1)
    total = sum(st.ended for st in res.stats)
    assert total == sum(1 for _ in range(res.games))   # every game had an ender
    assert res.stats[0].ended > res.stats[1].ended


def test_margin_is_against_the_best_opponent():
    res = run_arena(["greedy", "random"], 2, range(5), workers=1)
    a, b = res.stats
    assert all(x == -y for x, y in zip(a.margins, b.margins))


def test_bot_count_must_match_player_count():
    with pytest.raises(ValueError):
        run_arena(["greedy", "random"], 3, range(2), workers=1)


# --------------------------------------------------------------------------
# Turn cap
# --------------------------------------------------------------------------

def test_turn_cap_is_recorded_and_the_game_still_scores():
    res = run_arena(["random", "random"], 2, range(4), cap=25, workers=1)
    assert res.capped == res.games
    assert res.unfinished == res.games
    assert sum(st.wins for st in res.stats) == res.games


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------

def test_arena_is_reproducible():
    def run():
        r = run_arena(["greedy", "random"], 2, range(8), workers=1)
        return [(st.label, st.wins, st.scores) for st in r.stats]
    assert run() == run()


def test_worker_count_does_not_change_the_result():
    """Parallelism must not perturb outcomes — seeds are a pure function of
    the task, not of which process picked it up."""
    one = run_arena(["greedy", "random"], 2, range(10), workers=1)
    many = run_arena(["greedy", "random"], 2, range(10), workers=4)
    assert one.games == many.games
    for a, b in zip(one.stats, many.stats):
        assert a.wins == b.wins
        assert sorted(a.scores) == sorted(b.scores)


def test_different_seed_bases_are_different_games():
    a = run_arena(["greedy", "random"], 2, range(6), workers=1)
    b = run_arena(["greedy", "random"], 2, range(1000, 1006), workers=1)
    assert sorted(a.stats[0].scores) != sorted(b.stats[0].scores)


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def test_summary_mentions_every_bot_and_the_seat_table():
    res = run_arena(["greedy", "random"], 2, range(4), workers=1)
    out = res.summary()
    for lab in res.labels:
        assert lab in out
    assert "win rate by seat" in out


def test_result_json_round_trips(tmp_path):
    res = run_arena(["greedy", "random"], 2, range(4), workers=1)
    out = save(res, root=tmp_path)
    blob = json.loads((out / "result.json").read_text())
    assert blob["games"] == res.games
    assert len(blob["bots"]) == 2
    assert blob["bots"][0]["label"] == res.labels[0]
    assert (out / "summary.txt").read_text().strip()


def test_result_records_the_code_version(tmp_path):
    """Brief §5.8: a run must be reproducible from (seed, weights, code)."""
    res = run_arena(["greedy", "random"], 2, range(2), workers=1)
    assert "git_commit" in res.meta
    assert res.meta["cap"] and res.meta["workers"]


# --------------------------------------------------------------------------
# Multi-player
# --------------------------------------------------------------------------

@pytest.mark.parametrize("n_players", [3, 4, 5])
def test_multiplayer_games_run_and_score(n_players):
    specs = ["greedy"] + ["random"] * (n_players - 1)
    res = run_arena(specs, n_players, range(3), workers=1)
    assert res.games == 3 * n_players
    assert sum(st.wins for st in res.stats) == res.games
    assert res.stats[0].win_rate > res.stats[1].win_rate

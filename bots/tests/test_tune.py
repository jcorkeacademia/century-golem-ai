"""Step 6: CMA-ES tuning.

Mostly about the parameter mapping and the fitness bookkeeping — the parts
that would silently produce a nonsense search rather than an error.
"""
from __future__ import annotations

import json

import pytest

from bots.features import CORE_FEATURES, Scales, Weights
from bots.make_handset import ANCHOR, LAMBDA, VALUE
from bots.tune import (
    FIXED_LAMBDA,
    LAMBDA_MAX,
    LAMBDA_STD,
    PARAM_KEYS,
    PARAM_STDS,
    POOL_SHARES,
    Fitness,
    TuneConfig,
    allocate,
    build_pool,
    generation_tasks,
    param_stds,
    score_generation,
    write_candidate,
    x0_from,
    x_to_values,
)


# --------------------------------------------------------------------------
# Parameter vector
# --------------------------------------------------------------------------

def test_anchor_is_excluded_from_the_search():
    """golem_points stays at 1.0: scaling every value at once would rescale V
    without changing a single decision, so it is a wasted dimension."""
    assert ANCHOR not in PARAM_KEYS
    assert set(PARAM_KEYS) | {ANCHOR} == set(CORE_FEATURES)


def test_x0_is_the_handset_intent():
    x0 = x0_from()
    assert len(x0) == len(PARAM_KEYS)
    assert x0 == [VALUE[k] for k in PARAM_KEYS]


def test_lambda_is_no_longer_searched():
    """Three runs gave -0.01, 0.89 and 1.32 - no convergence - and removing
    it at the averaged optimum cost nothing: 50.2% CI [47.1, 53.3]. Century
    has no blocking, so racing beats watching."""
    assert FIXED_LAMBDA == 0.0
    assert len(x0_from()) == len(PARAM_KEYS)      # no lambda coordinate


def test_phase_split_doubles_the_vector():
    assert len(x0_from(split=True)) == 2 * len(PARAM_KEYS)
    assert len(param_stds(split=True)) == 2 * len(PARAM_KEYS)


def test_phase_split_starts_with_early_equal_to_late():
    """6b must start where 6a ended, or the comparison measures the restart."""
    early, late = x_to_values(x0_from(split=True))
    assert early == late


def test_x0_can_be_seeded_from_a_weights_file():
    x = x0_from("tuned_v1")
    assert len(x) == len(PARAM_KEYS)
    assert x[PARAM_KEYS.index("throughput")] > 2.0      # the tuned value


def test_every_parameter_has_a_step():
    """PARAM_STDS must cover every searched key, and may hold more.

    Step 9 adds steps for shaped_target and golem_count, which only appear
    in archetype runs, so a strict equality here would fail for a feature
    set that is legitimately larger than the core twelve.
    """
    assert set(PARAM_KEYS) <= set(PARAM_STDS)
    stds = param_stds()
    assert len(stds) == len(PARAM_KEYS)
    assert all(s > 0 for s in stds)


def test_archetype_keys_all_have_steps():
    from bots.tune import ARCHETYPE_FEATURES, ARCHETYPES, param_keys
    for name, spec in ARCHETYPES.items():
        for k in param_keys(ARCHETYPE_FEATURES, spec["fixed"]):
            assert k in PARAM_STDS, (name, k)


def test_archetypes_swap_rather_than_add_the_shaped_target():
    """Adding shaped_target alongside best_target screened at 23.4% - two
    copies of points-over-distance double the promise term. Swapping is
    lossless because they are the same quantity at alpha=beta=1."""
    from bots.tune import ARCHETYPE_FEATURES
    assert "shaped_target" in ARCHETYPE_FEATURES
    assert "best_target" not in ARCHETYPE_FEATURES


def test_archetypes_are_actually_distinct():
    from bots.tune import ARCHETYPES
    assert ARCHETYPES["rush"]["beta"] >= 2.0
    assert ARCHETYPES["rush"]["fixed"]["golem_count"] > 0
    assert ARCHETYPES["bigcard"]["alpha"] >= 1.5
    assert ARCHETYPES["bigcard"]["fixed"]["golem_count"] == 0.0
    assert ARCHETYPES["balanced"]["fixed"] == {}


def test_steps_are_per_coordinate_not_uniform():
    """A single sigma is wrong here: cry_y is 0.05 and dead_hand is -2.0.

    A flat step large enough to move dead_hand obliterates best_target, which
    is exactly the regime where the bot stops claiming golems.
    """
    stds = param_stds()
    assert max(stds) / min(stds) > 3


def test_best_target_gets_a_tight_step():
    """Above ~1.0 a promise outprices the points it promises — the bug that
    lost 120 games in a row. The search should not wander there casually."""
    assert PARAM_STDS["best_target"] <= 0.2
    assert VALUE["best_target"] + 2 * PARAM_STDS["best_target"] < 1.0


def test_x_to_values_pins_the_anchor():
    early, late = x_to_values([0.1] * len(PARAM_KEYS))
    assert early[ANCHOR] == 1.0 and late[ANCHOR] == 1.0
    assert set(early) == set(CORE_FEATURES)


def test_x_to_values_splits_early_and_late():
    n = len(PARAM_KEYS)
    early, late = x_to_values([0.1] * n + [0.9] * n)
    assert early["cry_y"] == 0.1 and late["cry_y"] == 0.9
    assert early[ANCHOR] == late[ANCHOR] == 1.0


# --------------------------------------------------------------------------
# Candidate files
# --------------------------------------------------------------------------

def test_split_candidate_writes_different_early_and_late_weights(tmp_path):
    n = len(PARAM_KEYS)
    p = write_candidate([0.1] * n + [0.9] * n, Scales.load(),
                        tmp_path / "s.json", name="s", depth=2)
    w = Weights.load(p)
    assert w.w_early != w.w_late
    assert w.effective(0.0) == w.w_early
    assert w.effective(1.0) == w.w_late


def test_write_candidate_round_trips(tmp_path):
    scales = Scales.load()
    p = write_candidate(x0_from(), scales, tmp_path / "c.json",
                        name="c", depth=2)
    w = Weights.load(p)
    assert w.features == list(CORE_FEATURES)
    assert w.ttc_depth == 2
    assert w.w_early == w.w_late


def test_write_candidate_reproduces_the_handset_weights(tmp_path):
    """x0 is the handset intent, so its weights must match handset_v1's."""
    scales = Scales.load()
    p = write_candidate(x0_from(), scales, tmp_path / "c.json",
                        name="c", depth=3)
    got = Weights.load(p)
    want = Weights.load("handset_v1")
    for k in CORE_FEATURES:
        assert got.w_early[k] == pytest.approx(want.w_early[k], abs=1e-4), k


def test_write_candidate_records_readable_intent(tmp_path):
    """The point of tuning in points-space: the output is legible."""
    p = write_candidate(x0_from(), Scales.load(), tmp_path / "c.json",
                        name="c", depth=2)
    blob = json.loads(p.read_text())
    assert blob["meta"]["value_in_points"]["cry_m"] == VALUE["cry_m"]


def test_lambda_is_clamped(tmp_path):
    scales = Scales.load()
    lo = write_candidate([0.1] * len(PARAM_KEYS), scales,
                         tmp_path / "lo.json", name="lo", depth=2, lam=-5.0)
    hi = write_candidate([0.1] * len(PARAM_KEYS), scales,
                         tmp_path / "hi.json", name="hi", depth=2, lam=9.0)
    assert Weights.load(lo).lam == 0.0          # never help the leader
    assert Weights.load(hi).lam == LAMBDA_MAX


def test_lambda_ceiling_is_not_binding_at_the_tuned_value():
    """Run 01 converged to 1.25 against a ceiling of 1.5 and was still
    climbing, so the ceiling was shaping the answer rather than excluding an
    absurd one. It must stay well clear of where the search settles."""
    assert LAMBDA_MAX >= 2.5


# --------------------------------------------------------------------------
# Opponent pool
# --------------------------------------------------------------------------

def test_pool_shares_sum_to_one():
    assert sum(POOL_SHARES.values()) == pytest.approx(1.0)
    for hof in ([], ["a"], ["a", "b", "c"]):
        pool = build_pool("handset_v1", hof)
        assert sum(share for _, share in pool) == pytest.approx(1.0)


def test_pool_without_a_hall_of_fame_redistributes_its_share():
    pool = dict(build_pool("handset_v1", []))
    assert "hof" not in pool
    assert pool["greedy"] > POOL_SHARES["greedy"]


def test_hall_of_fame_members_split_one_share():
    pool = build_pool("handset_v1", ["a", "b"])
    hof_share = sum(s for spec, s in pool if spec in ("a", "b"))
    assert hof_share == pytest.approx(POOL_SHARES["hof"])


def test_random_stays_a_small_share():
    """RandomBot is there to punish forgetting how to play, not to be farmed."""
    assert POOL_SHARES["random"] <= 0.15


# --------------------------------------------------------------------------
# Seed allocation — common random numbers
# --------------------------------------------------------------------------

def test_allocate_covers_every_seed_exactly_once():
    seeds = list(range(100))
    alloc = allocate(seeds, build_pool("handset_v1", ["a"]))
    got = [s for _, xs in alloc for s in xs]
    assert sorted(got) == seeds


def test_allocate_respects_shares_roughly():
    seeds = list(range(1000))
    alloc = dict((spec, len(xs)) for spec, xs in
                 allocate(seeds, build_pool("handset_v1", [])))
    assert alloc["random"] == pytest.approx(100, abs=20)


def test_allocate_gives_every_opponent_at_least_one_seed():
    alloc = allocate(list(range(8)), build_pool("handset_v1", ["a", "b"]))
    assert all(xs for _, xs in alloc)


# --------------------------------------------------------------------------
# Tasks and scoring
# --------------------------------------------------------------------------

def test_generation_tasks_cover_candidates_seatings_and_opponents():
    alloc = [("greedy", [1, 2]), ("random", [3])]
    tasks = generation_tasks(["c0", "c1"], alloc, cap=1000)
    assert len(tasks) == 2 * 3 * 2          # candidates x seeds x rotations
    assert {t[0] for t in tasks} == {0, 1}
    assert {t[1][3] for t in tasks} == {0, 1}


def test_candidate_always_sits_at_index_zero():
    """score_generation reads bots[0], so the candidate must be first."""
    tasks = generation_tasks(["cand"], [("greedy", [7])], cap=1000)
    for _, (specs, *_rest) in tasks:
        assert specs[0] == "cand"


def test_score_generation_counts_wins_and_margins():
    def fake(ci, won, margin):
        return (ci, {"bots": [{"won": won, "margin": margin}]})
    res = [fake(0, True, 10), fake(0, False, -4), fake(1, True, 2)]
    fits = score_generation(res, 2)
    assert fits[0].win_rate == 0.5
    assert fits[0].mean_margin == pytest.approx(3.0)
    assert fits[1].win_rate == 1.0
    assert fits[0].games == 2 and fits[1].games == 1


def test_score_generation_handles_a_candidate_with_no_games():
    fits = score_generation([(0, {"bots": [{"won": True, "margin": 1}]})], 2)
    assert fits[1].win_rate == 0.0 and fits[1].games == 0


# --------------------------------------------------------------------------
# Fitness
# --------------------------------------------------------------------------

def test_win_rate_dominates_margin():
    """Margin breaks ties; it must never outweigh actually winning."""
    winner = Fitness(win_rate=0.55, mean_margin=0.0, games=100)
    loser = Fitness(win_rate=0.50, mean_margin=+4.0, games=100)
    assert winner.score > loser.score


def test_margin_separates_equal_win_rates():
    a = Fitness(win_rate=0.5, mean_margin=+10.0, games=100)
    b = Fitness(win_rate=0.5, mean_margin=-10.0, games=100)
    assert a.score > b.score


def test_loss_is_negated_score():
    f = Fitness(win_rate=0.6, mean_margin=5.0, games=10)
    assert f.loss == -f.score
    assert f.score == pytest.approx(0.6 + 0.05)


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def test_config_round_trips():
    cfg = TuneConfig(generations=7, games=40)
    assert TuneConfig(**cfg.as_dict()).as_dict() == cfg.as_dict()


def test_default_depth_is_the_swept_value():
    """Depths 2, 3 and 4 were indistinguishable and depth 2 is 2.3x faster,
    so tuning and shipping both happen at 2 — see API_NOTES §13."""
    assert TuneConfig().depth == 2
    # the pool opponent must run at the candidates' depth, not deeper
    assert TuneConfig().pool_handset == "depth2"
    assert TuneConfig().validate_handset == "handset_v1"


# --------------------------------------------------------------------------
# End to end
# --------------------------------------------------------------------------

@pytest.mark.slow
def test_a_tiny_run_produces_checkpoints_and_resumes(tmp_path):
    from bots.tune import run
    cfg = TuneConfig(generations=2, games=4, popsize=4, workers=2,
                     validate_every=99, hof_every=99, depth=1)
    run(cfg, tmp_path / "r")
    d = tmp_path / "r"
    assert (d / "config.json").exists()
    assert (d / "gen_000.json").exists() and (d / "gen_001.json").exists()
    assert (d / "best.json").exists()
    assert (d / "state.pkl").exists()

    rec = json.loads((d / "gen_001.json").read_text())
    assert "best_values" in rec and rec["best_values"][ANCHOR] == 1.0
    assert "best_values_late" in rec
    assert rec["generation"] == 1

    # resuming must continue rather than restart
    cfg2 = TuneConfig(**{**cfg.as_dict(), "generations": 3})
    run(cfg2, d, resume=True)
    assert (d / "gen_002.json").exists()


def test_a_run_writes_both_the_mean_and_the_best_sample(tmp_path):
    """The distribution centre is the estimate; the best sample is one draw.

    Validating the sample instead of the centre made two equivalent runs look
    23 points apart (79.0% against 55.6% vs handset_v1) when their means are
    indistinguishable (78.2% against 75.2%, overlapping intervals).
    """
    from bots.tune import run
    cfg = TuneConfig(generations=1, games=4, popsize=4, workers=2,
                     validate_every=99, hof_every=99, depth=1)
    d = tmp_path / "r"
    run(cfg, d)
    assert (d / "mean.json").exists(), "the estimate of the optimum must be written"
    assert (d / "best.json").exists(), "the best sample is kept for comparison"
    mean = json.loads((d / "mean.json").read_text())
    best = json.loads((d / "best.json").read_text())
    assert mean["w_early"] != best["w_early"], "mean and best should not be identical"


def test_shaped_seed_factor_is_one_at_unit_exponents():
    from bots.tune import shaped_seed_factor
    assert shaped_seed_factor(1.0, 1.0) == pytest.approx(1.0)


def test_shaped_seed_factor_shrinks_for_high_alpha():
    """alpha > 1 inflates points^alpha, so the seeded value must come down.

    Measured: bigcard at alpha 1.6 without this correction scored 17-23%
    against a pool the balanced bot beats ~80% of the time, with sigma still
    at 0.93 by generation 5. Raising a typical 12-point golem to the 1.6th
    power makes the feature read ~4.4x larger, which starts the search in the
    regime where the promise term outprices the points it promises.
    """
    from bots.tune import shaped_seed_factor
    assert shaped_seed_factor(1.6, 1.0) < 0.3


def test_shaped_seed_factor_ignores_beta():
    """Beta must NOT be corrected for, and this is the expensive lesson.

    Beta only bites at TTC > 0; at TTC = 0 the divisor is 1 whatever beta is.
    The reading that governs the hoarding failure is a golem claimable right
    now, which beta leaves untouched. A first version compensated for the
    *typical* reading by multiplying rush's seed 5.2x, and rush went from
    88.5% at generation 1 to 9.0% at generation 0.
    """
    from bots.tune import shaped_seed_factor
    assert shaped_seed_factor(1.0, 2.5) == pytest.approx(1.0)
    assert shaped_seed_factor(1.0, 0.4) == pytest.approx(1.0)


def test_archetype_seeds_are_corrected():
    from bots.tune import (ARCHETYPES, ARCHETYPE_FEATURES, param_keys, x0_from)
    seeded = {}
    for name, a in ARCHETYPES.items():
        keys = param_keys(ARCHETYPE_FEATURES, a["fixed"])
        x = x0_from("tuned_split", keys=keys, alpha=a["alpha"], beta=a["beta"])
        seeded[name] = x[keys.index("shaped_target")]
    # each archetype starts from a different, deliberately corrected value
    # bigcard is scaled down for alpha; rush is untouched because beta does
    # not change the value of a golem you can claim right now.
    assert seeded["bigcard"] < seeded["balanced"]
    assert seeded["rush"] == pytest.approx(seeded["balanced"])

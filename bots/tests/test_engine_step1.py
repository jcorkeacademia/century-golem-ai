"""Step 1 engine changes.

The load-bearing test here is `test_pruned_is_a_subset_of_legal` — pruning is
only safe if every move it offers is one the unpruned enumeration would have
offered too. Everything else guards a specific change.
"""
from __future__ import annotations

import random
import time

import pytest

from bots._engine import (
    Acquire,
    Claim,
    Crystal,
    Game,
    IllegalAction,
    MERCHANT_CARDS,
    POINT_CARDS,
    PlayTrade,
    PlayUpgrade,
    Rest,
    SAMPLE_MERCHANT_DECK,
    SAMPLE_POINT_DECK,
)
import century_engine as E

Y, G, B, M = Crystal.YELLOW, Crystal.GREEN, Crystal.TURQUOISE, Crystal.MAGENTA


def state_sig(g: Game) -> tuple:
    """Everything observable, for equality comparisons."""
    return (
        g.current, g.game_over, g._end_triggered, g.win_target,
        tuple(c.name if c else None for c in g.point_row),
        tuple(c.name if c else None for c in g.merchant_row),
        tuple(tuple(sorted(rc.items())) for rc in g.row_crystals),
        tuple(len(t) for t in g.point_tokens),
        len(g.point_deck), len(g.merchant_deck),
        tuple((p.name, tuple(p.caravan), tuple(c.name for c in p.hand),
               tuple(c.name for c in p.played), tuple(c.name for c in p.point_cards),
               tuple(int(t) for t in p.tokens)) for p in g.players),
    )


def walk(g: Game, rng: random.Random, n: int, pruned: bool = False) -> int:
    """Play up to n random actions. Returns how many were taken."""
    for i in range(n):
        if g.game_over:
            return i
        acts = g.legal_actions(pruned=pruned)
        if not acts:
            return i
        g.apply_action(rng.choice(acts))
    return n


# --------------------------------------------------------------------------
# 1. Compendium by default
# --------------------------------------------------------------------------

def test_default_decks_are_the_compendium():
    g = Game(["A", "B"], seed=1)
    assert len(g.merchant_deck) + Game.MERCHANT_ROW == len(MERCHANT_CARDS) == 43
    assert len(g.point_deck) + Game.POINT_ROW == len(POINT_CARDS) == 36


def test_custom_decks_still_accepted():
    g = Game(["A", "B"], seed=1,
             merchant_deck=SAMPLE_MERCHANT_DECK, point_deck=SAMPLE_POINT_DECK)
    assert len(g.merchant_deck) + Game.MERCHANT_ROW == len(SAMPLE_MERCHANT_DECK)
    assert len(g.point_deck) + Game.POINT_ROW == len(SAMPLE_POINT_DECK)


def test_module_level_override_still_wins():
    """server/engine_path.py sets these globals; that must keep working."""
    old_m, old_p = E.MERCHANT_DECK, E.POINT_DECK
    try:
        E.MERCHANT_DECK, E.POINT_DECK = SAMPLE_MERCHANT_DECK, SAMPLE_POINT_DECK
        g = Game(["A", "B"], seed=1)
        assert len(g.merchant_deck) + Game.MERCHANT_ROW == len(SAMPLE_MERCHANT_DECK)
    finally:
        E.MERCHANT_DECK, E.POINT_DECK = old_m, old_p
    # explicit argument beats the global
    try:
        E.MERCHANT_DECK = SAMPLE_MERCHANT_DECK
        g = Game(["A", "B"], seed=1, merchant_deck=MERCHANT_CARDS)
        assert len(g.merchant_deck) + Game.MERCHANT_ROW == 43
    finally:
        E.MERCHANT_DECK = old_m


# --------------------------------------------------------------------------
# 2. clone()
# --------------------------------------------------------------------------

def test_clone_is_equal_but_independent():
    g = Game(["A", "B"], seed=4)
    walk(g, random.Random(4), 40)
    c = g.clone()
    assert state_sig(c) == state_sig(g)

    before = state_sig(g)
    walk(c, random.Random(99), 30)
    assert state_sig(g) == before, "mutating the clone changed the original"
    assert state_sig(c) != before, "clone did not actually advance"


def test_clone_containers_are_not_shared():
    g = Game(["A", "B"], seed=4)
    walk(g, random.Random(4), 40)
    c = g.clone()

    c.players[0].caravan[0] += 5
    c.players[0].hand.clear()
    c.players[0].point_cards.append(POINT_CARDS[0])
    c.players[0].tokens.append(E.Token.COPPER)
    c.players[0].played.clear()
    c.row_crystals[2][Y] += 3
    c.point_tokens[0].clear()
    c.merchant_row[0] = None
    c.point_row[0] = None
    c.merchant_deck.clear()
    c.point_deck.clear()
    c.last_discard[0] += 1

    assert g.players[0].caravan != c.players[0].caravan
    assert g.players[0].hand and g.players[0].point_cards == []
    assert g.players[0].tokens == []
    assert g.row_crystals[2][Y] == 0
    assert g.point_tokens[0] and g.merchant_row[0] is not None
    assert g.point_row[0] is not None and g.merchant_deck and g.point_deck
    assert g.last_discard == [0, 0, 0, 0]


def test_clone_shares_immutable_cards():
    g = Game(["A", "B"], seed=4)
    c = g.clone()
    assert c.players[0].hand[0] is g.players[0].hand[0]


def test_clone_is_fast():
    g = Game(["A", "B"], seed=4)
    walk(g, random.Random(4), 60)
    t0 = time.perf_counter()
    for _ in range(500):
        g.clone()
    per_ms = (time.perf_counter() - t0) / 500 * 1000
    assert per_ms < 1.0, f"clone took {per_ms:.3f} ms, target < 1 ms"


# --------------------------------------------------------------------------
# 3. shuffle_hidden()
# --------------------------------------------------------------------------

def test_shuffle_hidden_preserves_composition():
    g = Game(["A", "B"], seed=4)
    walk(g, random.Random(4), 40)
    c = g.clone()
    before_m, before_p = list(c.merchant_deck), list(c.point_deck)
    c.shuffle_hidden(random.Random(0))
    assert sorted(map(id, c.merchant_deck)) == sorted(map(id, before_m))
    assert sorted(map(id, c.point_deck)) == sorted(map(id, before_p))


def test_shuffle_hidden_actually_reorders_and_leaves_parent_alone():
    g = Game(["A", "B"], seed=4)
    parent_m = list(g.merchant_deck)
    c = g.clone()
    c.shuffle_hidden(random.Random(7))
    assert [x.name for x in c.merchant_deck] != [x.name for x in parent_m]
    assert list(g.merchant_deck) == parent_m


def test_shuffle_hidden_is_deterministic_given_rng():
    g = Game(["A", "B"], seed=4)
    a, b = g.clone(), g.clone()
    a.shuffle_hidden(random.Random(11))
    b.shuffle_hidden(random.Random(11))
    assert [x.name for x in a.merchant_deck] == [x.name for x in b.merchant_deck]


# --------------------------------------------------------------------------
# 4. last_discard
# --------------------------------------------------------------------------

def test_last_discard_records_the_overflow():
    g = Game(["A", "B"], seed=1)
    p = g.players[0]
    p.caravan = [9, 0, 0, 0]          # 9 yellow; +2 yellow overflows by 1
    p.hand = [E.CrystalCard(((Y, 2),), "Create 2")]
    g.apply_action(E.PlayCrystal(0))
    assert p.total_crystals() == 10
    assert g.last_discard == [1, 0, 0, 0]


def test_last_discard_drops_cheapest_first():
    g = Game(["A", "B"], seed=1)
    p = g.players[0]
    p.caravan = [2, 8, 0, 0]          # +2 yellow -> over by 2, both yellow go
    p.hand = [E.CrystalCard(((Y, 2),), "Create 2")]
    g.apply_action(E.PlayCrystal(0))
    assert g.last_discard == [2, 0, 0, 0]
    assert p.caravan == [2, 8, 0, 0]


def test_last_discard_resets_each_action():
    g = Game(["A", "B"], seed=1)
    p = g.players[0]
    p.caravan = [9, 0, 0, 0]
    p.hand = [E.CrystalCard(((Y, 2),), "Create 2"), E.UpgradeCard(1, "up")]
    g.apply_action(E.PlayCrystal(0))
    assert g.last_discard == [1, 0, 0, 0]
    g.apply_action(E.PlayCrystal(0))    # seat 1, well under the limit
    assert g.last_discard == [0, 0, 0, 0]


def test_last_discard_is_zero_when_nothing_dropped():
    g = Game(["A", "B"], seed=1)
    g.apply_action(g.legal_actions()[0])
    assert g.last_discard == [0, 0, 0, 0]


# --------------------------------------------------------------------------
# 5. legal_actions(pruned=True)
# --------------------------------------------------------------------------

def test_unpruned_default_is_unchanged():
    """The server calls legal_actions() with no arguments."""
    g = Game(["A", "B"], seed=4)
    walk(g, random.Random(4), 30)
    assert g.legal_actions() == g.legal_actions(pruned=False)


@pytest.mark.parametrize("n_players", [2, 3, 5])
def test_pruned_is_a_subset_of_legal(n_players):
    """Every pruned option must be one the full enumeration offers."""
    rng = random.Random(0)
    for seed in range(6):
        g = Game([f"P{i}" for i in range(n_players)], seed=seed)
        for _ in range(120):
            if g.game_over:
                break
            full = g.legal_actions()
            if not full:
                break
            pruned = g.legal_actions(pruned=True)
            assert pruned, "pruning emptied a non-empty action list"
            missing = set(pruned) - set(full)
            assert not missing, f"pruned offered illegal actions: {missing}"
            g.apply_action(rng.choice(pruned))


@pytest.mark.parametrize("n_players", [2, 4])
def test_pruned_keeps_every_action_kind_available(n_players):
    """Pruning narrows options within a kind; it must not remove a kind."""
    rng = random.Random(1)
    for seed in range(6):
        g = Game([f"P{i}" for i in range(n_players)], seed=seed)
        for _ in range(120):
            if g.game_over:
                break
            full = g.legal_actions()
            if not full:
                break
            kinds_full = {type(a) for a in full}
            kinds_pruned = {type(a) for a in g.legal_actions(pruned=True)}
            assert kinds_full == kinds_pruned
            g.apply_action(rng.choice(full))


def test_pruned_upgrades_are_unique_by_resulting_caravan():
    g = Game(["A", "B"], seed=1)
    p = g.players[0]
    p.caravan = [4, 3, 3, 0]
    p.hand = [E.UpgradeCard(3, "Triple upgrade")]
    opts = [a.upgrades for a in g.legal_actions(pruned=True) if isinstance(a, PlayUpgrade)]
    caravans = set()
    for seq in opts:
        car = p.caravan[:]
        for c in seq:
            car[c] -= 1
            car[c + 1] += 1
        caravans.add(tuple(car))
    assert len(caravans) == len(opts), "two options produce the same caravan"
    full = [a.upgrades for a in g.legal_actions() if isinstance(a, PlayUpgrade)]
    assert len(opts) < len(full)


def test_pruned_keeps_the_do_nothing_upgrade():
    """() is the only way to bank an upgrade card without breaking a cost."""
    g = Game(["A", "B"], seed=1)
    p = g.players[0]
    p.caravan = [2, 0, 0, 0]
    p.hand = [E.UpgradeCard(2, "Double upgrade")]
    opts = [a.upgrades for a in g.legal_actions(pruned=True) if isinstance(a, PlayUpgrade)]
    assert () in opts


def test_pruned_acquire_offers_at_most_three_payments_per_slot():
    g = Game(["A", "B"], seed=1)
    g.players[0].caravan = [3, 3, 2, 2]
    by_slot: dict[int, int] = {}
    for a in g.legal_actions(pruned=True):
        if isinstance(a, Acquire):
            by_slot[a.row_index] = by_slot.get(a.row_index, 0) + 1
    assert by_slot, "no acquires offered"
    assert max(by_slot.values()) <= 3, by_slot
    assert by_slot.get(0) == 1, "the free slot should have exactly one option"


def test_pruned_payments_are_affordable_and_right_sized():
    g = Game(["A", "B"], seed=1)
    for caravan in ([3, 3, 2, 2], [10, 0, 0, 0], [0, 0, 5, 5], [1, 1, 1, 2], [5, 0, 0, 0]):
        g.players[0].caravan = caravan[:]
        for a in g.legal_actions(pruned=True):
            if not isinstance(a, Acquire):
                continue
            assert len(a.payment) == a.row_index
            need = [0, 0, 0, 0]
            for c in a.payment:
                need[c] += 1
            assert all(need[i] <= caravan[i] for i in range(4)), (caravan, a)


def test_pruning_shrinks_the_action_list():
    """Pruning cuts Acquire hard and Upgrade moderately; Trade, Crystal, Rest
    and Claim are already minimal, and in real positions Trade options are
    roughly half the list. So the overall cut is modest by construction —
    ~20% — and the per-kind numbers are what's worth pinning.
    """
    rng = random.Random(3)
    full_total = pruned_total = 0
    acq_full = acq_pruned = 0
    up_full = up_pruned = 0
    for seed in range(10):
        g = Game(["A", "B"], seed=seed)
        for _ in range(150):
            if g.game_over:
                break
            full = g.legal_actions()
            if not full:
                break
            pruned = g.legal_actions(pruned=True)
            full_total += len(full)
            pruned_total += len(pruned)
            acq_full += sum(isinstance(a, Acquire) for a in full)
            acq_pruned += sum(isinstance(a, Acquire) for a in pruned)
            up_full += sum(isinstance(a, PlayUpgrade) for a in full)
            up_pruned += sum(isinstance(a, PlayUpgrade) for a in pruned)
            g.apply_action(rng.choice(full))

    assert pruned_total < full_total, (pruned_total, full_total)
    assert acq_pruned < acq_full * 0.60, (acq_pruned, acq_full)
    assert up_pruned < up_full * 0.85, (up_pruned, up_full)


# --------------------------------------------------------------------------
# 6. apply_action(validate=False)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("n_players", [2, 3, 4, 5])
def test_validate_false_matches_validate_true(n_players):
    names = [f"P{i}" for i in range(n_players)]
    for seed in range(5):
        a = Game(names, seed=seed)
        b = Game(names, seed=seed)
        rng_a, rng_b = random.Random(seed), random.Random(seed)
        for _ in range(200):
            if a.game_over:
                break
            acts_a = a.legal_actions()
            acts_b = b.legal_actions()
            assert acts_a == acts_b
            i = rng_a.randrange(len(acts_a))
            rng_b.randrange(len(acts_b))
            a.apply_action(acts_a[i])
            b.apply_action(acts_b[i], validate=False)
            assert state_sig(a) == state_sig(b)
        assert a.scores() == b.scores()


def test_validation_still_rejects_illegal_moves():
    g = Game(["A", "B"], seed=1)
    g.players[0].caravan = [0, 0, 0, 0]
    with pytest.raises(IllegalAction):
        g.apply_action(Rest())                       # nothing played yet
    with pytest.raises(IllegalAction):
        g.apply_action(Acquire(3, (Y, Y, Y)))        # can't afford
    with pytest.raises(IllegalAction):
        g.apply_action(PlayUpgrade(1, (Y,)))         # no yellow to upgrade
    with pytest.raises(IllegalAction):
        g.apply_action(Claim(0))                     # can't pay
    with pytest.raises(IllegalAction):
        g.apply_action(PlayTrade(0, 1))              # hand[0] is not a trade card


def test_game_over_still_rejects_actions():
    g = Game(["A", "B"], seed=1)
    g.game_over = True
    with pytest.raises(IllegalAction):
        g.apply_action(Rest())
    assert g.legal_actions() == [] and g.legal_actions(pruned=True) == []


# --------------------------------------------------------------------------
# 7. end_triggered accessor
# --------------------------------------------------------------------------

def test_end_triggered_property_tracks_the_private_flag():
    g = Game(["A", "B"], seed=1)
    assert g.end_triggered is False
    g._end_triggered = True
    assert g.end_triggered is True


def test_end_triggered_matches_the_derived_form():
    rng = random.Random(5)
    for seed in range(8):
        g = Game(["A", "B"], seed=seed)
        for _ in range(400):
            if g.game_over:
                break
            acts = g.legal_actions()
            if not acts:
                break
            g.apply_action(rng.choice(acts))
            derived = any(len(p.point_cards) >= g.win_target for p in g.players)
            assert g.end_triggered == derived


# --------------------------------------------------------------------------
# 8. whole-game regression
# --------------------------------------------------------------------------

@pytest.mark.parametrize("n_players", [2, 3, 4, 5])
def test_seeded_game_is_reproducible(n_players):
    names = [f"P{i}" for i in range(n_players)]

    def play(seed):
        g = Game(names, seed=seed)
        rng = random.Random(seed)
        trace = []
        while not g.game_over and len(trace) < 500:
            acts = g.legal_actions()
            if not acts:
                break
            a = rng.choice(acts)
            trace.append(repr(a))
            g.apply_action(a)
        return trace, [p.score() for p in g.players], g.winner()

    for seed in range(3):
        assert play(seed) == play(seed)


def test_a_full_game_finishes_and_scores():
    g = Game(["A", "B"], seed=11)
    rng = random.Random(11)
    steps = 0
    while not g.game_over and steps < 2000:
        acts = g.legal_actions(pruned=True)
        if not acts:
            break
        claim = next((a for a in acts if isinstance(a, Claim)), None)
        g.apply_action(claim or rng.choice(acts))
        steps += 1
    assert g.game_over
    assert g.winner() in {"A", "B"}
    assert max(len(p.point_cards) for p in g.players) >= g.win_target

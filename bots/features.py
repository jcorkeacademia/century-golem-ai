"""Named features, the value function they feed, and `explain()`.

The bot scores a position as a weighted sum of features, V = sum(w_i * f_i),
and plays the move with the highest V. Everything here exists so that sum can
be read back afterwards: each feature has a name, a description, and a
contribution you can print.

Two things shape the design:

* **TTC is expensive.** Step 2 measured it at ~0.2 ms a call and it dominates
  a decision. So it is computed once per evaluated state, in `Ctx`, and shared
  by every feature that wants it — never called inside a feature.
* **Features live on wildly different scales.** Golem points run 0-100;
  `dead_hand` is 0 or 1. Each is divided by its own spread (measured by
  `calibrate.py`) so that weights are comparable to each other, which is what
  makes the final "what matters in Century" answer readable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence

from bots._engine import (
    CARAVAN_LIMIT,
    Crystal,
    CrystalCard,
    Game,
    Player,
    TradeCard,
    UpgradeCard,
)
from bots import sim
from bots.sim import YE, nominal_output, throughput as _throughput, ye_of

WEIGHTS_DIR = Path(__file__).resolve().parent / "weights"
SCALES_PATH = WEIGHTS_DIR / "feature_scales.json"

DEFAULT_TTC_DEPTH = 3


# --------------------------------------------------------------------------
# Ctx — per-state shared cache
# --------------------------------------------------------------------------

class Ctx:
    """Everything expensive, computed once per evaluated state.

    Build one per state you are scoring, not one per feature and not one per
    player. `ttc_row(pid)` is the hot path: it costs a TTC search per golem on
    the row the first time and nothing thereafter.
    """

    __slots__ = ("game", "depth", "alpha", "beta",
                 "_ttc", "_tp", "_best_target", "_opp_row_min")

    def __init__(self, game: Game, depth: int = DEFAULT_TTC_DEPTH,
                 alpha: float = 1.0, beta: float = 1.0):
        self.game = game
        self.depth = depth
        # Exponents for `shaped_target` (brief feature #29). At 1.0/1.0 it is
        # exactly best_target; they exist so the shape of the points-versus-
        # distance trade-off can be tuned rather than assumed.
        self.alpha = alpha
        self.beta = beta
        self._ttc: dict[int, list[Optional[float]]] = {}
        self._tp: dict[int, float] = {}
        self._best_target: dict[int, float] = {}
        self._opp_row_min: dict[int, list[Optional[float]]] = {}

    def best_opponent_ttc_row(self, me: int) -> list[Optional[float]]:
        """Per slot, the *fastest* any opponent could claim it.

        The expensive one: it runs a TTC search per opponent per slot. Cached
        per (state, me) because every contested-* feature wants the same
        numbers. Note the opponent family is on probation — dropping the
        opponent term entirely cost nothing (API_NOTES §13), so these features
        have to earn the cycles they spend.
        """
        got = self._opp_row_min.get(me)
        if got is None:
            n = len(self.game.point_row)
            got = [None] * n
            for pid in range(self.game.n):
                if pid == me:
                    continue
                row = self.ttc_row(pid)
                for s in range(n):
                    if row[s] is None:
                        continue
                    if got[s] is None or row[s] < got[s]:
                        got[s] = row[s]
            self._opp_row_min[me] = got
        return got

    def ttc_row(self, pid: int) -> list[Optional[float]]:
        """TTC for every point-row slot, from `pid`'s point of view."""
        got = self._ttc.get(pid)
        if got is None:
            got = sim.ttc_row(self.game.players[pid], self.game.point_row, self.depth)
            self._ttc[pid] = got
        return got

    def throughput(self, pid: int) -> float:
        got = self._tp.get(pid)
        if got is None:
            got = _throughput(self.game.players[pid])
            self._tp[pid] = got
        return got

    def best_target(self, pid: int) -> float:
        """max over the row of points / (1 + TTC) — feature 7, cached because
        opponent selection needs it as a tie-break."""
        got = self._best_target.get(pid)
        if got is None:
            row = self.ttc_row(pid)
            best = 0.0
            for slot, pc in enumerate(self.game.point_row):
                if pc is None:
                    continue
                v = pc.points / (1.0 + row[slot])
                if v > best:
                    best = v
            got = best
            self._best_target[pid] = got
        return got


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

FeatureFn = Callable[[Game, Game, int, Ctx], float]


@dataclass(frozen=True)
class FeatureSpec:
    key: str
    fn: FeatureFn
    group: str
    symmetric: bool
    description: str


FEATURES: dict[str, FeatureSpec] = {}


def feature(key: str, group: str, symmetric: bool, description: str):
    """Register a feature.

    `symmetric` means the feature is meaningful for an opponent too, so it
    joins the -lambda * opponent term in V. Your golem points matter and so do
    theirs. Your leftover yellow crystals are not worth tracking on their side,
    so the crystal counts are not symmetric.
    """
    def deco(fn: FeatureFn) -> FeatureFn:
        if key in FEATURES:
            raise ValueError(f"duplicate feature key {key!r}")
        FEATURES[key] = FeatureSpec(key, fn, group, symmetric, description)
        return fn
    return deco


# --------------------------------------------------------------------------
# Core features (the brief's Step 3 set: 1, 2, 3-6, 7, 9, 11, 16, 17, 18)
# --------------------------------------------------------------------------

@feature("golem_points", "score", True, "Points on claimed golem cards.")
def f_golem_points(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    return float(sum(pc.points for pc in after.players[pid].point_cards))


@feature("token_points", "score", True, "Points from copper (3) and silver (1) tokens.")
def f_token_points(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    return float(sum(int(t) for t in after.players[pid].tokens))


@feature("cry_y", "caravan", False, "Yellow crystals held.")
def f_cry_y(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    return float(after.players[pid].caravan[Crystal.YELLOW])


@feature("cry_g", "caravan", False, "Green crystals held.")
def f_cry_g(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    return float(after.players[pid].caravan[Crystal.GREEN])


@feature("cry_b", "caravan", False, "Blue (turquoise) crystals held.")
def f_cry_b(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    return float(after.players[pid].caravan[Crystal.TURQUOISE])


@feature("cry_m", "caravan", False, "Magenta crystals held.")
def f_cry_m(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    return float(after.players[pid].caravan[Crystal.MAGENTA])


@feature("best_target", "targets", True,
         "Best golem on the row, as points / (1 + turns to claim it).")
def f_best_target(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    return ctx.best_target(pid)


@feature("token_race", "targets", False,
         "Reach of the copper/silver bonuses: token value / (1 + TTC) over "
         "the two token slots.")
def f_token_race(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    row = ctx.ttc_row(pid)
    total = 0.0
    for slot in (0, 1):
        pile = after.point_tokens[slot]
        if not pile or after.point_row[slot] is None:
            continue
        # Reading the pile's own token handles the reflow rule for free: when
        # copper runs out the engine slides the silver pile into slot 0, so
        # whatever sits here is what you would actually be handed.
        total += int(pile[-1]) / (1.0 + row[slot])
    return total


@feature("throughput", "engine", True,
         "Mean yellow-equivalent produced per turn across owned cards, "
         "counting the Rest turn.")
def f_throughput(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    return ctx.throughput(pid)


def _upgrade_capacity(caravan: Sequence[int]) -> int:
    """How many upgrade steps this caravan could absorb.

    A yellow can climb three levels, a green two, a blue one; magenta is
    stuck. Chaining one crystal repeatedly is legal, so this is the total.
    """
    return caravan[0] * 3 + caravan[1] * 2 + caravan[2]


@feature("playable_now", "hand", False,
         "Usable output sitting in hand right now: crystal gains, upgrade "
         "steps the caravan can absorb, and affordable profitable trades.")
def f_playable_now(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    p = after.players[pid]
    caravan = p.caravan
    total = 0.0
    for card in p.hand:
        if isinstance(card, CrystalCard):
            total += ye_of(sim._counts(card.gain))
        elif isinstance(card, UpgradeCard):
            total += min(card.steps, _upgrade_capacity(caravan))
        elif isinstance(card, TradeCard):
            net = nominal_output(card)
            if net <= 0:
                continue
            cost = sim._counts(card.cost)
            times = -1
            for i in range(4):
                if cost[i]:
                    v = caravan[i] // cost[i]
                    if times < 0 or v < times:
                        times = v
            if times > 0:
                total += net * min(times, 3)
    return total


@feature("exhausted", "hand", False,
         "Nominal output locked in the played pile — value a Rest would "
         "return.")
def f_exhausted(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    return float(sum(nominal_output(c) for c in after.players[pid].played))


@feature("dead_hand", "hand", False, "1 when the hand can produce nothing.")
def f_dead_hand(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    return 1.0 if f_playable_now(before, after, pid, ctx) == 0.0 else 0.0


CORE_FEATURES: tuple[str, ...] = tuple(FEATURES)


# --------------------------------------------------------------------------
# Scales
# --------------------------------------------------------------------------

@dataclass
class Scales:
    """Per-feature divisors, so weights are comparable across features."""
    values: dict[str, float] = field(default_factory=dict)
    diagnostics: dict[str, dict] = field(default_factory=dict)

    def get(self, key: str) -> float:
        return self.values.get(key, 1.0)

    @classmethod
    def load(cls, path: Path = SCALES_PATH) -> "Scales":
        if not path.exists():
            return cls()
        blob = json.loads(path.read_text())
        return cls(values=blob.get("scales", {}), diagnostics=blob.get("diagnostics", {}))

    @classmethod
    def unit(cls) -> "Scales":
        return cls(values={k: 1.0 for k in FEATURES})


# --------------------------------------------------------------------------
# Weights
# --------------------------------------------------------------------------

@dataclass
class Weights:
    """A weight file (BOT_IMPLEMENTATION_PROMPT §2.8)."""
    name: str
    features: list[str]
    w_early: dict[str, float]
    w_late: dict[str, float]
    lam: float = 0.5
    params: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path_or_name) -> "Weights":
        path = Path(path_or_name)
        if not path.exists():
            path = WEIGHTS_DIR / f"{path_or_name}.json"
        blob = json.loads(path.read_text())
        return cls(
            name=blob.get("name", path.stem),
            features=blob["features"],
            w_early=blob["w_early"],
            w_late=blob.get("w_late") or blob["w_early"],
            lam=blob.get("lambda", 0.5),
            params=blob.get("params", {}),
            meta=blob.get("meta", {}),
        )

    def save(self, path: Path) -> None:
        path.write_text(json.dumps({
            "name": self.name,
            "features": self.features,
            "w_early": self.w_early,
            "w_late": self.w_late,
            "lambda": self.lam,
            "params": self.params,
            "meta": self.meta,
        }, indent=2))

    @property
    def ttc_depth(self) -> int:
        return int(self.params.get("ttc_depth", DEFAULT_TTC_DEPTH))

    def effective(self, phase: float) -> dict[str, float]:
        """Blend early and late weights by game phase (§2.6)."""
        if self.w_early is self.w_late or self.w_early == self.w_late:
            return self.w_early
        return {k: (1.0 - phase) * self.w_early.get(k, 0.0) + phase * self.w_late.get(k, 0.0)
                for k in self.features}


def phase_of(game: Game) -> float:
    """How far into the game we are: the leader's progress toward the target."""
    if game.win_target <= 0:
        return 0.0
    best = max(len(p.point_cards) for p in game.players)
    return min(1.0, max(0.0, best / game.win_target))


# --------------------------------------------------------------------------
# The value function (§2.7)
# --------------------------------------------------------------------------

WIN_VALUE = 1000.0


def compute_features(before: Game, after: Game, pid: int, ctx: Ctx,
                     keys: Sequence[str]) -> dict[str, float]:
    return {k: FEATURES[k].fn(before, after, pid, ctx) for k in keys}


def _leading_opponent(game: Game, me: int, ctx: Ctx) -> Optional[int]:
    """The opponent to measure yourself against: highest score, ties broken by
    the better best_target."""
    others = [i for i in range(game.n) if i != me]
    if not others:
        return None
    best_score = max(game.players[i].score() for i in others)
    tied = [i for i in others if game.players[i].score() == best_score]
    if len(tied) == 1:
        return tied[0]
    return max(tied, key=lambda i: ctx.best_target(i))


def _has_turn_left_this_round(game: Game, me: int) -> bool:
    """Play ends when the seat pointer wraps to 0, so everyone from `current`
    to the last seat still acts."""
    return me >= game.current


def terminal_value(game: Game, me: int) -> Optional[float]:
    """Endgame override, or None if the game is still open (§2.7).

    Not a feature: winning is not something you trade off against crystals.
    """
    scores = [p.score() for p in game.players]
    mine = scores[me]
    best_other = max(s for i, s in enumerate(scores) if i != me)
    if game.game_over:
        margin = mine - best_other
        # By seat, never by name: Game.winner() returns a name, and two bots
        # in one match can share one (see API_NOTES §4.1).
        won = game._winner_index() == me
        return (WIN_VALUE if won else -WIN_VALUE) + margin
    if game.end_triggered and not _has_turn_left_this_round(game, me):
        return 10.0 * (mine - best_other)
    return None


def evaluate(before: Game, after: Game, me: int, weights: Weights,
             scales: Scales, ctx: Optional[Ctx] = None) -> tuple[float, dict[str, float]]:
    """Score `after` from `me`'s point of view.

    Returns (V, contributions), where contributions maps a label to
    w_i * norm_i(f_i) so `explain` can print exactly what produced V. Opponent
    terms are keyed `-opp:<feature>`.
    """
    term = terminal_value(after, me)
    if term is not None:
        return term, {"terminal": term}

    if ctx is None:
        ctx = Ctx(after, weights.ttc_depth,
                  alpha=float(weights.params.get("alpha", 1.0)),
                  beta=float(weights.params.get("beta", 1.0)))
    w = weights.effective(phase_of(after))
    keys = weights.features

    contributions: dict[str, float] = {}
    total = 0.0
    for k in keys:
        wi = w.get(k, 0.0)
        if wi == 0.0:
            continue
        c = wi * (FEATURES[k].fn(before, after, me, ctx) / scales.get(k))
        contributions[k] = c
        total += c

    if weights.lam:
        opp = _leading_opponent(after, me, ctx)
        if opp is not None:
            for k in keys:
                spec = FEATURES[k]
                if not spec.symmetric:
                    continue
                wi = w.get(k, 0.0)
                if wi == 0.0:
                    continue
                c = -weights.lam * wi * (spec.fn(before, after, opp, ctx) / scales.get(k))
                contributions[f"-opp:{k}"] = c
                total += c

    return total, contributions


# --------------------------------------------------------------------------
# explain()
# --------------------------------------------------------------------------

def score_actions(game: Game, me: int, weights: Weights, scales: Scales,
                  rng=None, samples: int = 1, pruned: bool = True) -> list[tuple]:
    """Score every legal action. Returns (V, action, contributions), best first.

    Acquire and Claim refill the row from a deck, so the clone is reshuffled
    first (`shuffle_hidden`) — otherwise the bot would see the true next card.
    """
    import random as _random
    from bots._engine import Acquire, Claim

    if rng is None:
        rng = _random.Random(0)
    out = []
    for action in game.legal_actions(pruned=pruned):
        reveals = isinstance(action, (Acquire, Claim))
        n = samples if reveals else 1
        total = 0.0
        contrib: dict[str, float] = {}
        for _ in range(n):
            c = game.clone()
            if reveals:
                c.shuffle_hidden(rng)
            c.apply_action(action, validate=False)
            v, parts = evaluate(game, c, me, weights, scales)
            total += v
            for k, val in parts.items():
                contrib[k] = contrib.get(k, 0.0) + val / n
        out.append((total / n, action, contrib))
    out.sort(key=lambda t: -t[0])
    return out


def describe_action(action) -> str:
    from bots._engine import Acquire, Claim, PlayCrystal, PlayTrade, PlayUpgrade, Rest
    if isinstance(action, Rest):
        return "Rest"
    if isinstance(action, Claim):
        return f"Claim(row {action.row_index})"
    if isinstance(action, Acquire):
        pay = "".join("YGBM"[int(c)] for c in action.payment) or "free"
        return f"Acquire(row {action.row_index}, pay {pay})"
    if isinstance(action, PlayCrystal):
        return f"PlayCrystal(hand {action.hand_index})"
    if isinstance(action, PlayUpgrade):
        ups = "".join("YGBM"[int(c)] for c in action.upgrades) or "none"
        return f"PlayUpgrade(hand {action.hand_index}, {ups})"
    if isinstance(action, PlayTrade):
        return f"PlayTrade(hand {action.hand_index}, x{action.times})"
    return repr(action)


def explain(game: Game, me: int, weights: Weights, scales: Optional[Scales] = None,
            top_k: int = 3, rng=None) -> str:
    """The point of the whole project: why the bot would play what it plays."""
    if scales is None:
        scales = Scales.load()
    ranked = score_actions(game, me, weights, scales, rng=rng)
    lines = [
        f"seat {me} ({game.players[me].name})  "
        f"caravan {list(game.players[me].caravan)}  "
        f"phase {phase_of(game):.2f}  "
        f"{len(ranked)} legal moves"
    ]
    for rank, (v, action, contrib) in enumerate(ranked[:top_k], 1):
        lines.append(f"#{rank} {describe_action(action):<34} V={v:+.2f}")
        parts = sorted(contrib.items(), key=lambda kv: -abs(kv[1]))
        row = "   " + "   ".join(f"{k} {c:+.2f}" for k, c in parts[:6] if abs(c) > 1e-9)
        if row.strip():
            lines.append(row)
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Step 7 candidates
# --------------------------------------------------------------------------
# Registered but NOT in CORE_FEATURES — each is admitted only if it wins its
# ablation gate. Grouped by what they cost to compute, because the cheap
# solitaire ones are screened first: Step 6 showed that ignoring opponents
# entirely costs nothing (API_NOTES §13), which makes the opponent-modelling
# family the least likely to pay for itself.

# ---- engine shape: cheap, no TTC -----------------------------------------

@feature("card_count", "engine", False, "Merchant cards owned.")
def f_card_count(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    p = after.players[pid]
    return float(len(p.hand) + len(p.played))


@feature("upgrade_steps", "engine", False,
         "Total upgrade steps across owned upgrade cards.")
def f_upgrade_steps(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    p = after.players[pid]
    return float(sum(c.steps for c in list(p.hand) + list(p.played)
                     if isinstance(c, UpgradeCard)))


@feature("feedable_trades", "engine", False,
         "Profitable trades you can actually afford, weighted by repeats.")
def f_feedable_trades(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    p = after.players[pid]
    caravan = p.caravan
    total = 0.0
    for card in list(p.hand) + list(p.played):
        if not isinstance(card, TradeCard):
            continue
        net = nominal_output(card)
        if net <= 0:
            continue
        cost = sim._counts(card.cost)
        times = -1
        for i in range(4):
            if cost[i]:
                v = caravan[i] // cost[i]
                if times < 0 or v < times:
                    times = v
        if times > 0:
            total += net * min(times, 3)
    return total


@feature("color_coverage", "engine", False,
         "How many of green/blue/magenta you can actually produce.")
def f_color_coverage(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    p = after.players[pid]
    owned = list(p.hand) + list(p.played)
    produced = set()
    best_upgrade = 0
    for card in owned:
        if isinstance(card, CrystalCard):
            produced.update(c for c, n in card.gain if n)
        elif isinstance(card, TradeCard):
            produced.update(c for c, n in card.gain if n)
        elif isinstance(card, UpgradeCard):
            best_upgrade = max(best_upgrade, card.steps)
    count = 0
    for c in (Crystal.GREEN, Crystal.TURQUOISE, Crystal.MAGENTA):
        # A colour counts if something gains it outright, or your biggest
        # single upgrade card can climb that far in one play.
        if c in produced or best_upgrade >= int(c):
            count += 1
    return float(count)


@feature("free_space", "caravan", False, "Room left under the 10-crystal cap.")
def f_free_space(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    return float(CARAVAN_LIMIT - after.players[pid].total_crystals())


@feature("overflow_waste", "caravan", False,
         "Yellow-equivalent the caravan cap threw away on this move.")
def f_overflow_waste(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    # last_discard is per-action and belongs to whoever just acted, so it only
    # means anything for the seat that moved.
    if before.current != pid:
        return 0.0
    return float(ye_of(after.last_discard))


@feature("golem_count", "score", True,
         "Golems claimed, independent of their points.")
def f_golem_count(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    return float(len(after.players[pid].point_cards))


@feature("race_lead", "race", False,
         "Your golem count minus the best opponent's.")
def f_race_lead(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    mine = len(after.players[pid].point_cards)
    best = max((len(p.point_cards) for i, p in enumerate(after.players) if i != pid),
               default=0)
    return float(mine - best)


@feature("row_bounty", "row", False,
         "Best merchant deal left on the row for whoever moves next.")
def f_row_bounty(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    best = 0.0
    for j, card in enumerate(after.merchant_row):
        if card is None:
            continue
        sitting = after.row_crystals[j]
        piled = ye_of([sitting.get(Crystal(i), 0) for i in range(4)])
        v = nominal_output(card) + piled - j
        if v > best:
            best = v
    return best


# ---- target shaping: uses my own TTC, already cached ----------------------

@feature("option_breadth", "targets", False,
         "How many golems are within reach, not just the best one.")
def f_option_breadth(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    row = ctx.ttc_row(pid)
    total = 0.0
    for slot, pc in enumerate(after.point_row):
        if pc is None:
            continue
        d = 1.0 + row[slot]
        total += pc.points / (d * d)
    return total


@feature("shaped_target", "targets", False,
         "best_target with tunable exponents: points^alpha / (1 + TTC)^beta.")
def f_shaped_target(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    # alpha/beta ride on the weights file; 1.0/1.0 reproduces best_target.
    a, b = ctx.alpha, ctx.beta
    row = ctx.ttc_row(pid)
    best = 0.0
    for slot, pc in enumerate(after.point_row):
        if pc is None:
            continue
        v = (pc.points ** a) / ((1.0 + row[slot]) ** b)
        if v > best:
            best = v
    return best


@feature("clock_lead", "race", False,
         "Score lead divided by how long the game has left to run.")
def f_clock_lead(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    scores = [p.score() for p in after.players]
    best_other = max(s for i, s in enumerate(scores) if i != pid)
    lead = scores[pid] - best_other
    turns = None
    for i, p in enumerate(after.players):
        row = ctx.ttc_row(i)
        live = [t for t in row if t is not None]
        pace = max(1.0, sum(live) / len(live)) if live else 1.0
        est = max(0, after.win_target - len(p.point_cards)) * pace
        turns = est if turns is None else min(turns, est)
    return lead / (1.0 + (turns or 0.0))


# ---- opponent modelling: each costs a TTC search per opponent -------------

@feature("snipe_risk", "opponent", False,
         "1 when an opponent can reach your best target no slower than you.")
def f_snipe_risk(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    mine = ctx.ttc_row(pid)
    theirs = ctx.best_opponent_ttc_row(pid)
    best_slot, best_v = None, -1.0
    for slot, pc in enumerate(after.point_row):
        if pc is None:
            continue
        v = pc.points / (1.0 + mine[slot])
        if v > best_v:
            best_slot, best_v = slot, v
    if best_slot is None or theirs[best_slot] is None:
        return 0.0
    return 1.0 if theirs[best_slot] <= mine[best_slot] else 0.0


def _contest_factor(my_ttc: float, opp_ttc: Optional[float],
                    me: int, game: Game) -> float:
    """1.0 if you get there first, 0.5 on a tie, 0.2 if they beat you."""
    if opp_ttc is None:
        return 1.0
    if my_ttc < opp_ttc:
        return 1.0
    if my_ttc > opp_ttc:
        return 0.2
    # Dead heat: whoever acts first this round takes it.
    return 1.0 if me >= game.current else 0.5


@feature("contested_target", "opponent", False,
         "best_target discounted by whether an opponent gets there first.")
def f_contested_target(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    mine = ctx.ttc_row(pid)
    theirs = ctx.best_opponent_ttc_row(pid)
    best = 0.0
    for slot, pc in enumerate(after.point_row):
        if pc is None:
            continue
        p = _contest_factor(mine[slot], theirs[slot], pid, after)
        v = pc.points * p / (1.0 + mine[slot])
        if v > best:
            best = v
    return best


@feature("contested_tokens", "opponent", False,
         "token_race counting only slots you would reach first.")
def f_contested_tokens(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    mine = ctx.ttc_row(pid)
    theirs = ctx.best_opponent_ttc_row(pid)
    total = 0.0
    for slot in (0, 1):
        pile = after.point_tokens[slot]
        if not pile or after.point_row[slot] is None:
            continue
        if theirs[slot] is not None and theirs[slot] < mine[slot]:
            continue
        total += int(pile[-1]) / (1.0 + mine[slot])
    return total


@feature("denial", "opponent", False,
         "Points taken off the row that an opponent was about to claim.")
def f_denial(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    if before.current != pid:
        return 0.0
    gone = [pc for pc in before.point_row
            if pc is not None and pc not in after.point_row]
    if not gone:
        return 0.0
    before_ctx = Ctx(before, ctx.depth)
    theirs = before_ctx.best_opponent_ttc_row(pid)
    total = 0.0
    for slot, pc in enumerate(before.point_row):
        if pc is None or pc not in gone:
            continue
        t = theirs[slot]
        if t is not None and t <= 1.0:
            total += pc.points
    return total


@feature("response_threat", "opponent", False,
         "Once the end is triggered, what opponents still to act can still take.")
def f_response_threat(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    if not after.end_triggered:
        return 0.0
    total = 0.0
    for opp in range(after.current, after.n):
        if opp == pid:
            continue
        row = ctx.ttc_row(opp)
        best = 0.0
        for slot, pc in enumerate(after.point_row):
            if pc is None:
                continue
            if row[slot] == 0.0 and pc.points > best:
                best = float(pc.points)
        total += best
    return total


@feature("opp_fit_bounty", "opponent", False,
         "How much the row would help the next player if they took from it.")
def f_opp_fit_bounty(before: Game, after: Game, pid: int, ctx: Ctx) -> float:
    nxt = after.current
    if nxt == pid or after.game_over:
        return 0.0
    them = after.players[nxt]
    base = ctx.best_target(nxt)
    played = sim.card_ids(them.played)
    car = (them.caravan[0], them.caravan[1], them.caravan[2], them.caravan[3])
    tp = ctx.throughput(nxt)
    best = 0.0
    for j, card in enumerate(after.merchant_row):
        if card is None:
            continue
        # What their best target would be worth with this card in hand.
        hand = sim.card_ids(list(them.hand) + [card])
        improved = 0.0
        for pc in after.point_row:
            if pc is None:
                continue
            t = sim.ttc_state(car, hand, played, sim.cost_of(pc), ctx.depth, tp)
            v = pc.points / (1.0 + t)
            if v > improved:
                improved = v
        sitting = after.row_crystals[j]
        piled = ye_of([sitting.get(Crystal(i), 0) for i in range(4)])
        v = (improved - base) + piled - j
        if v > best:
            best = v
    return best


EXTENDED_FEATURES: tuple[str, ...] = tuple(k for k in FEATURES if k not in CORE_FEATURES)

# Screening order: cheapest and most likely to pay first. The opponent family
# is last on purpose — Step 6 measured that ignoring opponents entirely costs
# nothing, so these are the least likely to earn their gate, and they are also
# the most expensive to evaluate.
SCREEN_ORDER: tuple[str, ...] = (
    "card_count", "upgrade_steps", "feedable_trades", "color_coverage",
    "free_space", "overflow_waste", "golem_count", "race_lead", "row_bounty",
    "option_breadth", "shaped_target", "clock_lead",
    "snipe_risk", "contested_target", "contested_tokens", "denial",
    "response_threat", "opp_fit_bounty",
)

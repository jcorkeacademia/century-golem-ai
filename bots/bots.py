"""The three bots.

    RandomBot    picks uniformly at random. The floor.
    GreedyBot    fixed if/then rules, no weights. The benchmark.
    WeightedBot  scores every legal move with V = sum(w_i * f_i). The real one.

All three answer one question: `choose(game) -> Action`. Nothing here mutates
the real game — a bot that wants to know what a move leads to clones the game
first. The caller applies whatever comes back.

---------------------------------------------------------------------------
HOW A TURN FLOWS

    match.py                     bot.choose(game)                engine
    --------                     ----------------                ------
    whose turn is it? ---------> look at the position
                                 what moves are legal? --------> legal_actions()
                                 score / filter them
    apply the chosen move <----- return one Action
                                                    ----------> apply_action()

WeightedBot is the only one that looks ahead, and it does so by *simulation*:
for each candidate move it clones the game, plays the move on the clone, and
measures the resulting position with the feature set. The clone is thrown away.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import random
from typing import Optional, Protocol, Sequence

from bots._engine import (
    Acquire,
    Action,
    Claim,
    CrystalCard,
    Game,
    PlayCrystal,
    PlayTrade,
    PlayUpgrade,
    Rest,
    TradeCard,
    UpgradeCard,
)
from bots.features import (
    Ctx,
    FEATURES,
    Scales,
    Weights,
    describe_action,
    evaluate,
    explain,
)
from bots.sim import cost_of, nominal_output, shortfall, ye_of


class Bot(Protocol):
    """What every bot must provide."""
    name: str

    def choose(self, game: Game) -> Optional[Action]:
        ...


# ==========================================================================
# RandomBot
# ==========================================================================

class RandomBot:
    """Uniform over legal moves. Seeded, so a game is reproducible.

    Uses the *unpruned* action list by default: pruning is a bot-side
    optimisation, and the floor should be measured against the real move set.
    """

    def __init__(self, rng: Optional[random.Random] = None, seed: int = 0,
                 pruned: bool = False, name: str = "random"):
        self.rng = rng if rng is not None else random.Random(seed)
        self.pruned = pruned
        self.name = name

    def choose(self, game: Game) -> Optional[Action]:
        acts = game.legal_actions(pruned=self.pruned)
        return self.rng.choice(acts) if acts else None


# ==========================================================================
# GreedyBot
# ==========================================================================

class GreedyBot:
    """Fixed rules, checked in order. The first one that fires wins.

        1. Claim the best golem you can afford right now.
        2. Build an engine first: acquire while you own very few cards.
        3. Play the trade/upgrade that gets you closest to your best target.
        4. Rest if nothing in hand can do anything.
        5. Play the crystal card with the biggest gain.
        6. Take a cheap merchant card from the left of the row.
        7. Anything legal.

    No weights, no search beyond one-move lookahead inside rule 3. This is the
    benchmark WeightedBot has to beat, and it is also the policy that
    generates positions for calibration — so it needs to play *plausibly*, not
    well. Random play is useless for that: it empties the merchant row and
    almost never claims a golem.

    RULE 2 IS NOT IN THE BRIEF, and without it this bot is degenerate. The
    brief orders acquire *below* "play the crystal card with the best output".
    But `Create 2` returns to hand after every Rest, so the crystal rule fires
    every cycle and the acquire rule is unreachable: measured over 15 games,
    the bot made zero acquisitions and finished every one of them holding its
    two starting cards. `throughput` was then literally constant at
    (2+2)/(2+1) = 1.333 across 21,000 calibration observations — std 0.000,
    which is what flagged it.

    A benchmark that never buys a card is no benchmark, and a calibration
    sampler that never varies its engine poisons the feature scales. So the
    engine-building rule goes above the crystal rule, gated on owning fewer
    than `build_until` cards.
    """

    def __init__(self, rng: Optional[random.Random] = None, seed: int = 0,
                 build_until: int = 5, name: str = "greedy"):
        self.rng = rng if rng is not None else random.Random(seed)
        self.build_until = build_until
        self.name = name

    # ---- the target this bot is working toward -------------------------
    @staticmethod
    def best_target(game: Game, pid: int):
        """The golem worth chasing: most points per unit of distance.

        Distance here is `shortfall` (upgrade steps away), not TTC. GreedyBot
        is meant to be cheap and legible; TTC would cost a search per golem
        per turn and is WeightedBot's job.

        Returns (cost, points) or None when the row is empty.
        """
        caravan = game.players[pid].caravan
        best, best_v = None, -1.0
        for pc in game.point_row:
            if pc is None:
                continue
            cost = cost_of(pc)
            v = pc.points / (1.0 + shortfall(caravan, cost))
            if v > best_v:
                best, best_v = (cost, pc.points), v
        return best

    def choose(self, game: Game) -> Optional[Action]:
        acts = game.legal_actions(pruned=True)
        if not acts:
            return None
        pid = game.current

        # --- 1. claim -------------------------------------------------
        # Slots 0 and 1 also hand over a token (3 points / 1 point), so a tie
        # on card points breaks toward the left of the row.
        claims = [a for a in acts if isinstance(a, Claim)]
        if claims:
            return max(claims, key=lambda a: (
                game.point_row[a.row_index].points + self._token_bonus(game, a.row_index),
                -a.row_index,
            ))

        # --- 2. build the engine before running it --------------------
        # You cannot convert crystals you never produce. While the hand is
        # tiny, taking a card beats playing one — and the leftmost slot is
        # free, so it costs nothing but the turn.
        me = game.players[pid]
        owned = len(me.hand) + len(me.played)
        if owned < self.build_until:
            acqs = [a for a in acts if isinstance(a, Acquire) and a.row_index <= 1]
            if acqs:
                return max(acqs, key=lambda a: self._acquire_value(game, a))

        # --- 3. the play that closes the most distance ----------------
        # Every trade/upgrade is simulated on a clone and scored by how much
        # shortfall to the target it removes. Crystal cards are handled in
        # rule 4 instead: they always "work", so they would otherwise win here
        # by default and starve the shaping plays.
        target = self.best_target(game, pid)
        shaping = [a for a in acts if isinstance(a, (PlayTrade, PlayUpgrade))]
        if target is not None and shaping:
            cost = target[0]
            base = shortfall(game.players[pid].caravan, cost)
            best, best_gain = None, 0
            for a in shaping:
                clone = game.clone()
                clone.apply_action(a, validate=False)
                gain = base - shortfall(clone.players[pid].caravan, cost)
                if gain > best_gain:
                    best, best_gain = a, gain
            if best is not None:
                return best

        # --- 4. rest a dead hand --------------------------------------
        # "Dead" is the feature: nothing in hand produces anything usable.
        rests = [a for a in acts if isinstance(a, Rest)]
        if rests and self._hand_is_dead(game, pid):
            return rests[0]

        # --- 5. best crystal card -------------------------------------
        crystals = [a for a in acts if isinstance(a, PlayCrystal)]
        if crystals:
            return max(crystals,
                       key=lambda a: nominal_output(game.players[pid].hand[a.hand_index]))

        # --- 6. shop, but only cheaply --------------------------------
        # Slots beyond the second cost crystals the bot would rather keep.
        acqs = [a for a in acts if isinstance(a, Acquire) and a.row_index <= 1]
        if acqs:
            return max(acqs, key=lambda a: self._acquire_value(game, a))

        # --- 7. fallback ----------------------------------------------
        if rests:
            return rests[0]
        return self.rng.choice(acts)

    # ---- helpers -------------------------------------------------------
    @staticmethod
    def _token_bonus(game: Game, slot: int) -> int:
        if slot in (0, 1) and game.point_tokens[slot]:
            return int(game.point_tokens[slot][-1])
        return 0

    @staticmethod
    def _hand_is_dead(game: Game, pid: int) -> bool:
        ctx = Ctx(game, 1)          # depth 1: dead_hand never consults TTC
        return FEATURES["dead_hand"].fn(game, game, pid, ctx) == 1.0

    @staticmethod
    def _acquire_value(game: Game, a: Acquire) -> float:
        """What taking this card is worth: the card itself, plus any crystals
        that have piled up on it, minus what the placement costs."""
        card = game.merchant_row[a.row_index]
        sitting = game.row_crystals[a.row_index]
        bonus = sum(ye_of([sitting.get(c, 0) if i == c else 0 for i in range(4)])
                    for c in range(4))
        return nominal_output(card) + bonus - a.row_index


# ==========================================================================
# WeightedBot
# ==========================================================================

class WeightedBot:
    """Scores every legal move and plays the best.

    For each candidate action:

        clone the game            so nothing real is touched
        shuffle the hidden decks  so a refill reveals a *plausible* card,
                                  not the true next one (that would be
                                  reading the deck — see brief §0.2)
        apply the action          validate=False: it came from legal_actions
        evaluate the result       V = sum(w_i * norm_i(f_i)) - lambda * (opp)

    Acquire and Claim are the two actions that refill a row from a deck, so
    their value depends on a card nobody can see. Those are averaged over
    `samples` different reshuffles instead of trusting one draw.

    Ties are broken randomly rather than by list order — otherwise the bot
    inherits whatever order `legal_actions` happens to produce, which is a
    real and invisible bias.
    """

    def __init__(self, weights: Weights, scales: Optional[Scales] = None,
                 rng: Optional[random.Random] = None, seed: int = 0,
                 samples: int = 1, lookahead: int = 0, name: Optional[str] = None):
        self.weights = weights
        self.scales = scales if scales is not None else Scales.load()
        self.rng = rng if rng is not None else random.Random(seed)
        self.samples = samples
        self.lookahead = lookahead          # Step 8; 0 for now
        self.name = name or weights.name

    def choose(self, game: Game) -> Optional[Action]:
        scored = self.score_all(game)
        if not scored:
            return None
        best = scored[0][0]
        # Collect everything within a hair of the best, then pick one at random.
        tied = [a for v, a in scored if v >= best - 1e-9]
        return tied[0] if len(tied) == 1 else self.rng.choice(tied)

    def score_all(self, game: Game) -> list[tuple[float, Action]]:
        """(V, action) for every legal move, best first."""
        me = game.current
        out: list[tuple[float, Action]] = []
        for action in game.legal_actions(pruned=True):
            out.append((self._value_of(game, action, me), action))
        out.sort(key=lambda t: -t[0])
        return out

    def _value_of(self, game: Game, action: Action, me: int) -> float:
        # Only Acquire and Claim slide a row and draw a replacement, so only
        # they need averaging over possible draws.
        reveals = isinstance(action, (Acquire, Claim))
        n = self.samples if reveals else 1
        total = 0.0
        for _ in range(n):
            clone = game.clone()
            if reveals:
                clone.shuffle_hidden(self.rng)
            clone.apply_action(action, validate=False)
            v, _ = evaluate(game, clone, me, self.weights, self.scales)
            total += v
        return total / n

    def explain(self, game: Game, top_k: int = 3) -> str:
        return explain(game, game.current, self.weights, self.scales,
                       top_k=top_k, rng=self.rng)


# ==========================================================================
# Playing a whole game
# ==========================================================================

ACTION_CAP = 1000          # brief §Step 5; see API_NOTES §3.3 for why


def play_game(bots: Sequence[Bot], seed: int, cap: int = ACTION_CAP) -> dict:
    """Run one game. `bots[i]` sits in seat i.

    Seat-tagged names, never bare ones: `Game.scores()` is keyed by player
    name, so two bots of the same type would collapse into one entry and a
    seat's score would vanish (API_NOTES §4.1). Everything here indexes by
    seat instead.
    """
    names = [f"{b.name}@{i}" for i, b in enumerate(bots)]
    game = Game(names, seed=seed)

    actions = 0
    while not game.game_over and actions < cap:
        action = bots[game.current].choose(game)
        if action is None:
            break
        game.apply_action(action)
        actions += 1

    scores = [p.score() for p in game.players]
    best = max(scores)
    # The engine's own tie-break: highest seat among the tied.
    winner = max(i for i, s in enumerate(scores) if s == best)
    return {
        "seed": seed,
        "scores": scores,
        "winner": winner,
        "golems": [len(p.point_cards) for p in game.players],
        "actions": actions,
        "capped": actions >= cap,
        "finished": game.game_over,
    }

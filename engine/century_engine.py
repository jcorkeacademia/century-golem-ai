"""
Century: Golem Edition — rules engine
=====================================

A headless, deterministic game engine. No UI, no networking — just the rules,
encoded so that:
  * a hot-seat / server layer can drive it (apply validated actions), and
  * an AI/solver can enumerate legal actions and search game states.

DESIGN PRINCIPLE: the engine is authoritative. Every mutation goes through
`apply_action`, which rejects illegal moves. The multiplayer server should
NEVER trust a client — it should reconstruct the action and call apply_action.

DECKS: `Game` uses the full transcribed compendium (43 merchant / 36 point
cards, in century_cards.py) by default. The small hand-written decks at the
bottom of this file are kept as SAMPLE_MERCHANT_DECK / SAMPLE_POINT_DECK for
tests that want a short, predictable game; pass them to the constructor.
"""

from __future__ import annotations
from dataclasses import dataclass, field, replace
from enum import IntEnum
from collections import Counter
from typing import Optional, Iterator
import itertools
import json
import random
import sys


# ---------------------------------------------------------------------------
# Crystals
# ---------------------------------------------------------------------------

class Crystal(IntEnum):
    """Colors, ordered by the upgrade chain. Yellow is cheapest."""
    YELLOW = 0
    GREEN = 1
    TURQUOISE = 2   # the blue crystal
    MAGENTA = 3     # the pink crystal

    @property
    def can_upgrade(self) -> bool:
        return self < Crystal.MAGENTA


# End-game value of a leftover crystal: every non-yellow crystal is worth 1.
def crystal_endgame_value(c: Crystal) -> int:
    return 0 if c == Crystal.YELLOW else 1


CARAVAN_LIMIT = 10


# ---------------------------------------------------------------------------
# Merchant cards (3 types)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CrystalCard:
    """Gain a fixed bundle of crystals (e.g. 'Create 2' = 2 yellow)."""
    gain: tuple[tuple[Crystal, int], ...]
    name: str = ""

    def as_counter(self) -> Counter:
        c = Counter()
        for color, n in self.gain:
            c[color] += n
        return c


@dataclass(frozen=True)
class UpgradeCard:
    """Perform up to `steps` single-level upgrades (each optional)."""
    steps: int
    name: str = ""


@dataclass(frozen=True)
class TradeCard:
    """Trade `cost` -> `gain`, repeatable any number of times."""
    cost: tuple[tuple[Crystal, int], ...]
    gain: tuple[tuple[Crystal, int], ...]
    name: str = ""

    def cost_counter(self) -> Counter:
        return Counter({c: n for c, n in self.cost})

    def gain_counter(self) -> Counter:
        return Counter({c: n for c, n in self.gain})


MerchantCard = CrystalCard | UpgradeCard | TradeCard


@dataclass(frozen=True)
class PointCard:
    """Cost of crystals -> victory points."""
    cost: tuple[tuple[Crystal, int], ...]
    points: int
    name: str = ""

    def cost_counter(self) -> Counter:
        return Counter({c: n for c, n in self.cost})


class Token(IntEnum):
    COPPER = 3   # worth 3 points
    SILVER = 1   # worth 1 point


# ---------------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------------

@dataclass
class Player:
    name: str
    caravan: list[int] = field(default_factory=lambda: [0, 0, 0, 0])  # per Crystal
    hand: list[MerchantCard] = field(default_factory=list)      # available to play
    played: list[MerchantCard] = field(default_factory=list)    # played this cycle
    point_cards: list[PointCard] = field(default_factory=list)
    tokens: list[Token] = field(default_factory=list)

    # --- caravan helpers ---
    def total_crystals(self) -> int:
        return sum(self.caravan)

    def add(self, color: Crystal, n: int = 1) -> None:
        self.caravan[color] += n

    def remove(self, color: Crystal, n: int = 1) -> None:
        if self.caravan[color] < n:
            raise ValueError("not enough crystals to remove")
        self.caravan[color] -= n

    def has(self, counter: Counter) -> bool:
        return all(self.caravan[c] >= n for c, n in counter.items())

    def score(self) -> int:
        pts = sum(pc.points for pc in self.point_cards)
        pts += sum(int(t) for t in self.tokens)
        pts += sum(self.caravan[c] * crystal_endgame_value(Crystal(c)) for c in range(4))
        return pts


# ---------------------------------------------------------------------------
# Actions  (immutable descriptions of a move; validated by the engine)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlayCrystal:
    hand_index: int

@dataclass(frozen=True)
class PlayUpgrade:
    hand_index: int
    # each element is the color you choose to upgrade one step, in order.
    # len must be <= card.steps; each color must be upgradable and present.
    upgrades: tuple[Crystal, ...]

@dataclass(frozen=True)
class PlayTrade:
    hand_index: int
    times: int  # how many times to execute the trade (>=1)

@dataclass(frozen=True)
class Acquire:
    row_index: int                 # which merchant card in the row (0-based)
    payment: tuple[Crystal, ...]   # one crystal per card to its left; len == row_index

@dataclass(frozen=True)
class Rest:
    pass

@dataclass(frozen=True)
class Claim:
    row_index: int  # which point card in the row

@dataclass(frozen=True)
class Discard:
    """Crystals thrown away to get back under the caravan limit.

    A sub-decision, not a turn: it resolves the move that overflowed, and the
    turn does not pass until it does. Only ever legal on a game built with
    `discard_choice=True`, and only while one is pending. `counts` is indexed
    by Crystal, like a caravan.
    """
    counts: tuple[int, int, int, int]

Action = PlayCrystal | PlayUpgrade | PlayTrade | Acquire | Rest | Claim | Discard


class IllegalAction(Exception):
    pass


# ---------------------------------------------------------------------------
# Game state
# ---------------------------------------------------------------------------

class Game:
    POINT_ROW = 5           # face-up point cards
    MERCHANT_ROW = 6        # face-up merchant cards

    def __init__(self, player_names: list[str], seed: Optional[int] = None, log: bool = False,
                 merchant_deck: Optional[list[MerchantCard]] = None,
                 point_deck: Optional[list[PointCard]] = None,
                 discard_choice: bool = False):
        # The printed game is 2–5 players. One player is also allowed, for the
        # solo solver (solver handover §Goal): a single seat racing the clock
        # to win_target golems, with no opponent. Nothing else in the engine
        # needs a special case — see _advance_turn for why the final round
        # collapses correctly at n=1.
        if not (1 <= len(player_names) <= 5):
            raise ValueError("Century supports 1 (solo) to 5 players")
        # Deck sources, in precedence order: explicit argument, module-level
        # MERCHANT_DECK/POINT_DECK override, then the real compendium.
        _m, _p = _default_decks()
        self._merchant_source = merchant_deck if merchant_deck is not None else _m
        self._point_source = point_deck if point_deck is not None else _p
        self.seed = seed
        self.rng = random.Random(seed)
        self.players = [Player(n) for n in player_names]
        self.n = len(player_names)
        self.current = 0
        self.game_over = False
        # end trigger: 6th point card in 1–3p, else 5th. Solo deliberately
        # takes the 2–3p target of 6, which is the goal the solver minimises
        # turns to; it is not an accident of the `<= 3` test.
        self.win_target = 6 if self.n <= 3 else 5
        self._end_triggered = False

        # Append-only action log for offline analysis / self-play data
        # collection (see _log_action) — off by default so AI search
        # (MCTS etc., which constructs huge numbers of throwaway Games for
        # rollouts) never pays for it. `event_log`/`to_jsonl()` are the
        # public surface; `_card_ids`/`_instance_ids` (see
        # _build_card_identity) only exist when log=True.
        self.log = log
        self.event_log: list[dict] = []
        self._turn_counter = 0

        # Crystals the caravan limit dropped on the most recent action, as
        # per-color counts (see _enforce_caravan_limit). Reset every action.
        self.last_discard: list[int] = [0, 0, 0, 0]

        # Over-limit discard: by the real rules the player CHOOSES what to
        # throw away, but the engine has always dropped the cheapest first.
        # `discard_choice=True` surfaces the choice as a sub-decision instead
        # (see _enforce_caravan_limit). It is opt-in and defaults to the old
        # behaviour on purpose: the multiplayer server and UI have no way to
        # prompt for the choice yet, so switching the default would break a
        # working game. The solo solver opts in, because "drop the cheapest"
        # throws away the yellow that pays for acquisitions and can make an
        # otherwise-optimal line look slower than it is.
        self.discard_choice = discard_choice
        # When a choice is owed: how many crystals the player must drop.
        # None the rest of the time. The turn does not pass while it is set.
        self.pending_discard: Optional[int] = None

        self._setup()

    # ----- setup -----
    def _setup(self) -> None:
        # Point deck + row (draw 5)
        deck = list(self._point_source)
        self.rng.shuffle(deck)
        self.point_deck = deck
        self.point_row: list[Optional[PointCard]] = [self.point_deck.pop() for _ in range(self.POINT_ROW)]

        # Tokens: coppers above slot 0, silvers above slot 1 (count = players x2)
        self.point_tokens: list[list[Token]] = [[] for _ in range(self.POINT_ROW)]
        self.point_tokens[0] = [Token.COPPER] * (self.n * 2)
        self.point_tokens[1] = [Token.SILVER] * (self.n * 2)

        # Merchant deck + row (draw 6); crystals sitting on row cards
        mdeck = list(self._merchant_source)
        self.rng.shuffle(mdeck)
        self.merchant_deck = mdeck
        self.merchant_row: list[Optional[MerchantCard]] = [self.merchant_deck.pop() for _ in range(self.MERCHANT_ROW)]
        self.row_crystals: list[Counter] = [Counter() for _ in range(self.MERCHANT_ROW)]

        # Starting hands: one Create 2 + one Upgrade 2 each
        for p in self.players:
            p.hand = [CrystalCard(((Crystal.YELLOW, 2),), "Create 2"),
                      UpgradeCard(2, "Upgrade 2")]

        # Starting crystals per player order
        start = {0: [3, 0], 1: [4, 0], 2: [4, 0], 3: [3, 1], 4: [3, 1]}  # [yellow, green]
        for i, p in enumerate(self.players):
            y, g = start[i]
            p.caravan[Crystal.YELLOW] = y
            p.caravan[Crystal.GREEN] = g

        if self.log:
            self._build_card_identity()
            self.event_log.append({
                "type": "game_start",
                "seed": self.seed,
                "players": [p.name for p in self.players],
                "starting_hands": [[self._card_ref(c) for c in p.hand] for p in self.players],
            })

    # ----- convenience -----
    @property
    def player(self) -> Player:
        return self.players[self.current]

    @property
    def end_triggered(self) -> bool:
        """True once someone has reached `win_target` golems. The game itself
        doesn't end until play wraps back to seat 0 — see _advance_turn."""
        return self._end_triggered

    # ----- cloning (for AI search; not used by the server) -----
    def clone(self) -> "Game":
        """A deep-enough copy: everything mutable is copied, card objects are
        shared.

        Cards are frozen dataclasses — nothing can mutate one — so copying
        them (as copy.deepcopy does) is pure waste. What must be copied is
        every *container*: each player's caravan/hand/played/point_cards/
        tokens, both rows, the per-slot crystal Counters, the token piles and
        both decks.

        The clone gets its own `rng`. The engine only draws from `rng` during
        _setup, so a clone's is effectively unused; `shuffle_hidden` takes an
        explicit rng precisely so callers never depend on this one.
        """
        g = Game.__new__(Game)

        g.seed = self.seed
        g.rng = random.Random()
        g.n = self.n
        g.current = self.current
        g.game_over = self.game_over
        g.win_target = self.win_target
        g._end_triggered = self._end_triggered
        g._merchant_source = self._merchant_source
        g._point_source = self._point_source
        g.last_discard = self.last_discard[:]
        g.discard_choice = self.discard_choice
        g.pending_discard = self.pending_discard

        players = []
        for p in self.players:
            q = Player.__new__(Player)
            q.name = p.name
            q.caravan = p.caravan[:]
            q.hand = p.hand[:]
            q.played = p.played[:]
            q.point_cards = p.point_cards[:]
            q.tokens = p.tokens[:]
            players.append(q)
        g.players = players

        g.point_deck = self.point_deck[:]
        g.point_row = self.point_row[:]
        g.point_tokens = [t[:] for t in self.point_tokens]
        g.merchant_deck = self.merchant_deck[:]
        g.merchant_row = self.merchant_row[:]
        g.row_crystals = [rc.copy() for rc in self.row_crystals]

        g.log = self.log
        g.event_log = self.event_log[:] if self.log else []
        g._turn_counter = self._turn_counter
        if self.log:
            # Keyed by id() of shared card objects, and never mutated after
            # _build_card_identity — safe to share.
            g._card_ids = self._card_ids
            g._instance_ids = self._instance_ids
        return g

    def shuffle_hidden(self, rng: random.Random) -> None:
        """Reshuffle both undrawn decks in place.

        Call this on a *clone* before simulating an Acquire or Claim. Those
        actions refill the row from the top of a deck; without a reshuffle a
        bot would see the true next card — information no opponent has. Never
        call it on a real game.
        """
        rng.shuffle(self.merchant_deck)
        rng.shuffle(self.point_deck)

    # =====================================================================
    #  Legal-action enumeration  (used by AI; also handy for UI validation)
    # =====================================================================
    def legal_actions(self, pruned: bool = False) -> list[Action]:
        """Every legal move from the current state.

        `pruned=True` returns a strategically-equivalent *subset*, for bots:
        upgrade and trade options are deduplicated by the caravan they
        produce (the engine otherwise enumerates distinct orderings that land
        in the same place), and Acquire offers at most three payment
        multisets per row slot instead of every affordable combination.

        The default output is unchanged and exhaustive — the UI needs every
        option a human could click. Only bots should pass pruned=True.
        """
        if self.game_over:
            return []
        acts: list[Action] = []
        p = self.player

        # A pending discard blocks everything else — see apply_action. Every
        # distinct choice leaves a distinct caravan, so there is nothing for
        # `pruned` to collapse here.
        if self.pending_discard is not None:
            return list(self._discard_options(p, self.pending_discard))

        # --- Play ---
        for i, card in enumerate(p.hand):
            if isinstance(card, CrystalCard):
                acts.append(PlayCrystal(i))
            elif isinstance(card, UpgradeCard):
                opts = (self._upgrade_options_pruned(p, card.steps) if pruned
                        else self._upgrade_options(p, card.steps))
                acts.extend(PlayUpgrade(i, u) for u in opts)
            elif isinstance(card, TradeCard):
                acts.extend(self._trade_options(p, i, card, pruned))

        # --- Acquire ---
        for j, card in enumerate(self.merchant_row):
            if card is None:
                continue
            if j == 0:
                acts.append(Acquire(0, ()))           # leftmost is free
            elif p.total_crystals() >= j:
                pays = (self._payment_options_pruned(p, j) if pruned
                        else self._payment_options(p, j))
                for pay in pays:
                    acts.append(Acquire(j, pay))

        # --- Rest ---
        if p.played:
            acts.append(Rest())

        # --- Claim ---
        for j, pc in enumerate(self.point_row):
            if pc is not None and p.has(pc.cost_counter()):
                acts.append(Claim(j))

        return acts

    def _upgrade_options(self, p: Player, steps: int) -> Iterator[tuple[Crystal, ...]]:
        """All distinct sequences of up to `steps` single upgrades this player
        could legally perform (order matters because chaining is allowed)."""
        seen = set()
        def rec(caravan: list[int], chosen: tuple[Crystal, ...]):
            key = (tuple(caravan), chosen)
            if chosen not in seen:
                seen.add(chosen)
                yield chosen
            if len(chosen) == steps:
                return
            for c in (Crystal.YELLOW, Crystal.GREEN, Crystal.TURQUOISE):
                if caravan[c] > 0:
                    nxt = caravan[:]
                    nxt[c] -= 1
                    nxt[c + 1] += 1
                    yield from rec(nxt, chosen + (c,))
        yield from rec(p.caravan[:], ())

    def _upgrade_options_pruned(self, p: Player, steps: int) -> list[tuple[Crystal, ...]]:
        """Like _upgrade_options, but one option per *resulting caravan*.

        The exhaustive version enumerates orderings: upgrading yellow then
        green and green then yellow are separate entries that leave the
        caravan in the same state, so a bot scores the same position twice.
        Keeping the first sequence that reaches each caravan also prefers the
        shortest one, since the search widens by length.

        The do-nothing option `()` is deliberately kept. It looks useless, but
        it is the only way to discard an upgrade card without touching the
        caravan — which matters when every available step would break a golem
        cost you can already afford (e.g. holding exactly 2Y for a 2Y golem).

        Cheaper than the exhaustive version, not just narrower: if a caravan
        has already been reached in fewer steps, every caravan reachable from
        here is reachable from there too (with steps to spare), so the branch
        is abandoned. Each distinct caravan is therefore expanded once.
        """
        seen: dict[tuple[int, ...], tuple[Crystal, ...]] = {}
        depth: dict[tuple[int, ...], int] = {}

        def rec(caravan: list[int], chosen: tuple[Crystal, ...]) -> None:
            key = tuple(caravan)
            prev = depth.get(key)
            if prev is not None and prev <= len(chosen):
                return
            depth[key] = len(chosen)
            if key not in seen:
                seen[key] = chosen
            if len(chosen) == steps:
                return
            for c in (Crystal.YELLOW, Crystal.GREEN, Crystal.TURQUOISE):
                if caravan[c] > 0:
                    nxt = caravan[:]
                    nxt[c] -= 1
                    nxt[c + 1] += 1
                    rec(nxt, chosen + (c,))

        rec(p.caravan[:], ())
        return list(seen.values())

    def _trade_options(self, p: Player, idx: int, card: TradeCard,
                       pruned: bool = False) -> Iterator[PlayTrade]:
        cost = card.cost_counter()
        # max times limited by each cost color available
        max_times = min((p.caravan[c] // n for c, n in cost.items()), default=0)
        if not pruned:
            for t in range(1, max_times + 1):
                yield PlayTrade(idx, t)
            return
        # Deduplicate by resulting caravan. Repeating a trade t times moves the
        # caravan by t*(gain - cost), so two different repeat counts can only
        # land in the same place when gain == cost — a no-op trade. No card in
        # the compendium is one, so this is a single check up front rather than
        # per-repetition work: either every count is distinct, or all of them
        # collapse to one.
        if card.gain_counter() == cost:
            if max_times:
                yield PlayTrade(idx, 1)
            return
        for t in range(1, max_times + 1):
            yield PlayTrade(idx, t)

    def _payment_options(self, p: Player, j: int) -> Iterator[tuple[Crystal, ...]]:
        """Distinct multisets of j crystals the player can spend (one per card
        to the left). Returned as sorted tuples so duplicates collapse."""
        avail = []
        for c in range(4):
            avail.extend([Crystal(c)] * p.caravan[c])
        seen = set()
        for combo in itertools.combinations(avail, j):
            key = tuple(sorted(combo))
            if key not in seen:
                seen.add(key)
                yield key

    def _payment_options_pruned(self, p: Player, j: int) -> list[tuple[Crystal, ...]]:
        """At most three payment multisets for taking the card at slot `j`.

        The exhaustive version builds every C(total, j) combination and then
        throws ~90% of them away as duplicate multisets; at a full caravan
        that's 252 combinations collapsing to 28 options, all of which a bot
        then scores. These three cover the strategically distinct intents:

          1. cheapest — spend the lowest crystals in the upgrade chain
          2. most-surplus — spend from whatever colour you hold most of
          3. preserve — spend without emptying any colour entirely

        Caller guarantees p.total_crystals() >= j.

        A fourth ("keep the colours my best target golem needs") is in the
        brief but needs the TTC machinery from Step 2, so it isn't here yet.
        """
        car = p.caravan
        opts: list[tuple[Crystal, ...]] = []

        # 1. cheapest colors first
        pick: list[Crystal] = []
        for c in range(4):
            take = min(car[c], j - len(pick))
            pick.extend([Crystal(c)] * take)
            if len(pick) == j:
                break
        opts.append(tuple(pick))

        # 2. most-surplus colors first (ties break to the cheaper color)
        remain = car[:]
        pick = []
        while len(pick) < j:
            c = max(range(4), key=lambda x: (remain[x], -x))
            remain[c] -= 1
            pick.append(Crystal(c))
        opts.append(tuple(sorted(pick)))

        # 3. keep at least one of every color held, if that's possible at all
        remain = car[:]
        pick = []
        for c in range(4):
            while remain[c] > 1 and len(pick) < j:
                remain[c] -= 1
                pick.append(Crystal(c))
            if len(pick) == j:
                break
        if len(pick) < j:          # can't be done; fall back to cheapest
            for c in range(4):
                while remain[c] > 0 and len(pick) < j:
                    remain[c] -= 1
                    pick.append(Crystal(c))
                if len(pick) == j:
                    break
        opts.append(tuple(sorted(pick)))

        out: list[tuple[Crystal, ...]] = []
        seen: set[tuple[Crystal, ...]] = set()
        for o in opts:
            if o not in seen:
                seen.add(o)
                out.append(o)
        return out

    # =====================================================================
    #  Apply an action
    # =====================================================================
    def apply_action(self, action: Action, validate: bool = True) -> None:
        """Apply `action`, mutating the game.

        `validate=False` skips the legality checks. Use it ONLY for an action
        that came straight out of this same game's `legal_actions()` — i.e. on
        a bot's internal clone during search. An illegal action applied this
        way corrupts the game silently instead of raising. Server code must
        never pass it.
        """
        if validate and self.game_over:
            raise IllegalAction("game is over")
        p = self.player
        acting_seat = self.current
        caravan_before = p.caravan[:] if self.log else None
        self.last_discard = [0, 0, 0, 0]

        # While a discard is owed the turn is frozen mid-move: the only thing
        # that may happen next is the discard itself.
        if validate and self.pending_discard is not None and not isinstance(action, Discard):
            raise IllegalAction(
                f"must discard {self.pending_discard} crystal(s) before acting")

        if isinstance(action, Discard):
            action_type, info = "Discard", self._discard(p, action, validate)
        elif isinstance(action, PlayCrystal):
            action_type, info = "PlayCrystal", self._play_crystal(p, action, validate)
        elif isinstance(action, PlayUpgrade):
            action_type, info = "PlayUpgrade", self._play_upgrade(p, action, validate)
        elif isinstance(action, PlayTrade):
            action_type, info = "PlayTrade", self._play_trade(p, action, validate)
        elif isinstance(action, Acquire):
            action_type, info = "Acquire", self._acquire(p, action, validate)
        elif isinstance(action, Rest):
            action_type, info = "Rest", self._rest(p, validate)
        elif isinstance(action, Claim):
            action_type, info = "Claim", self._claim(p, action, validate)
        else:
            raise IllegalAction(f"unknown action {action!r}")

        self._enforce_caravan_limit(p)

        if self.log:
            self._log_action(acting_seat, action_type, info, caravan_before, p.caravan)

        # A move that overflowed the caravan has not finished: the same player
        # still owes a Discard, so the turn does not pass. Unreachable unless
        # discard_choice is on — _enforce_caravan_limit resolves it itself
        # otherwise, and pending_discard stays None.
        if self.pending_discard is None:
            self._advance_turn()

        if self.log and self.game_over:
            self._log_game_over()

    # ----- action implementations -----
    # Each returns a small dict of whatever _log_action (only ever called
    # when self.log) needs beyond the generic turn/player/caravan envelope —
    # which card(s) moved, and any action-specific detail (Acquire/Claim's
    # cost, PlayTrade's repeat count, Claim's token). Cheap to build even
    # when unused; the real cost of logging (id lookups, dict-of-dicts,
    # the append itself) stays fully behind the `if self.log` gate above.
    def _play_crystal(self, p: Player, a: PlayCrystal, validate: bool = True) -> dict:
        if validate:
            card = self._pop_playable(p, a.hand_index, CrystalCard)
        else:
            card = p.hand.pop(a.hand_index)
        for color, n in card.gain:
            p.add(color, n)
        p.played.append(card)
        return {"cards": [card]}

    def _play_upgrade(self, p: Player, a: PlayUpgrade, validate: bool = True) -> dict:
        if validate:
            card = p.hand[a.hand_index] if 0 <= a.hand_index < len(p.hand) else None
            if not isinstance(card, UpgradeCard):
                raise IllegalAction("not an upgrade card")
            if len(a.upgrades) > card.steps:
                raise IllegalAction("too many upgrade steps")
            # validate against a copy first
            test = p.caravan[:]
            for c in a.upgrades:
                if not Crystal(c).can_upgrade or test[c] <= 0:
                    raise IllegalAction("illegal upgrade step")
                test[c] -= 1
                test[c + 1] += 1
            p.caravan = test
        else:
            card = p.hand[a.hand_index]
            caravan = p.caravan
            for c in a.upgrades:
                caravan[c] -= 1
                caravan[c + 1] += 1
        p.hand.pop(a.hand_index)
        p.played.append(card)
        return {"cards": [card]}

    def _play_trade(self, p: Player, a: PlayTrade, validate: bool = True) -> dict:
        if validate:
            card = p.hand[a.hand_index] if 0 <= a.hand_index < len(p.hand) else None
            if not isinstance(card, TradeCard):
                raise IllegalAction("not a trade card")
            if a.times < 1:
                raise IllegalAction("must trade at least once")
        else:
            card = p.hand[a.hand_index]
        cost, gain = card.cost_counter(), card.gain_counter()
        if validate:
            for c, n in cost.items():
                if p.caravan[c] < n * a.times:
                    raise IllegalAction("not enough crystals to trade")
        for c, n in cost.items():
            p.caravan[c] -= n * a.times
        for c, n in gain.items():
            p.caravan[c] += n * a.times
        p.hand.pop(a.hand_index)
        p.played.append(card)
        return {"cards": [card], "times": a.times}

    def _acquire(self, p: Player, a: Acquire, validate: bool = True) -> dict:
        j = a.row_index
        if validate:
            if not (0 <= j < self.MERCHANT_ROW) or self.merchant_row[j] is None:
                raise IllegalAction("no merchant card there")
            if len(a.payment) != j:
                raise IllegalAction(f"must place exactly {j} crystals")
        pay = Counter(a.payment)
        if validate and not p.has(pay):
            raise IllegalAction("cannot afford payment")
        # pay: one crystal onto each card to the left
        for k, color in enumerate(a.payment):
            p.remove(color, 1)
            self.row_crystals[k][color] += 1
        # take card + any crystals sitting on it
        card = self.merchant_row[j]
        for color, n in self.row_crystals[j].items():
            p.add(color, n)
        self.row_crystals[j] = Counter()
        p.hand.append(card)
        self._slide_and_refill_merchants(j)
        return {"cards": [card], "row_index": j, "cost_paid": pay}

    def _rest(self, p: Player, validate: bool = True) -> dict:
        if validate and not p.played:
            raise IllegalAction("nothing to rest")
        cards = list(p.played)
        p.hand.extend(p.played)
        p.played.clear()
        return {"cards": cards}

    def _claim(self, p: Player, a: Claim, validate: bool = True) -> dict:
        j = a.row_index
        pc = self.point_row[j] if 0 <= j < self.POINT_ROW else None
        if validate and pc is None:
            raise IllegalAction("no point card there")
        cost = pc.cost_counter()
        if validate and not p.has(cost):
            raise IllegalAction("cannot pay point-card cost")
        for c, n in cost.items():
            p.caravan[c] -= n
        p.point_cards.append(pc)
        # token bonus on the two leftmost slots
        token_awarded = None
        if j in (0, 1) and self.point_tokens[j]:
            token = self.point_tokens[j].pop()
            p.tokens.append(token)
            token_awarded = "copper" if token == Token.COPPER else "silver"
            self._reflow_tokens()
        self._slide_and_refill_points(j)
        if len(p.point_cards) >= self.win_target:
            self._end_triggered = True
        return {"cards": [pc], "row_index": j, "cost_paid": cost, "token_awarded": token_awarded}

    # ----- board maintenance -----
    def _slide_and_refill_merchants(self, taken: int) -> None:
        row, crys = self.merchant_row, self.row_crystals
        for k in range(taken, self.MERCHANT_ROW - 1):
            row[k], row[k + 1] = row[k + 1], row[k]
            crys[k], crys[k + 1] = crys[k + 1], crys[k]
        row[-1] = self.merchant_deck.pop() if self.merchant_deck else None
        crys[-1] = Counter()

    def _slide_and_refill_points(self, taken: int) -> None:
        row = self.point_row
        for k in range(taken, self.POINT_ROW - 1):
            row[k] = row[k + 1]
        row[-1] = self.point_deck.pop() if self.point_deck else None

    def _reflow_tokens(self) -> None:
        # when the copper pile (slot 0) empties, slide silver up to slot 0
        if not self.point_tokens[0] and self.point_tokens[1]:
            self.point_tokens[0] = self.point_tokens[1]
            self.point_tokens[1] = []

    def _enforce_caravan_limit(self, p: Player) -> None:
        """Bring `p` back under the caravan limit, one way or the other.

        With `discard_choice=False` (the default, and what the multiplayer
        game has always done) the engine drops the cheapest crystals itself.
        With it True, nothing is dropped here: the overflow is recorded in
        `pending_discard` and apply_action stops short of ending the turn,
        leaving `legal_actions()` offering nothing but Discard.

        What got dropped is recorded in self.last_discard (per-color counts)
        for the acting player only — it is reset at the top of every action.
        """
        over = p.total_crystals() - CARAVAN_LIMIT
        if over <= 0:
            return
        if self.discard_choice:
            self.pending_discard = over
            return
        for _ in range(over):
            for c in range(4):
                if p.caravan[c] > 0:
                    p.caravan[c] -= 1
                    self.last_discard[c] += 1
                    break

    def _discard_options(self, p: Player, k: int) -> Iterator[Discard]:
        """Every way to throw away exactly `k` crystals from p's caravan.

        Small: `k` is the overflow, rarely more than two or three, and there
        are only four colors — at k=3 with a full caravan that is 20 options.
        """
        for y in range(min(k, p.caravan[0]) + 1):
            for g in range(min(k - y, p.caravan[1]) + 1):
                for t in range(min(k - y - g, p.caravan[2]) + 1):
                    m = k - y - g - t
                    if 0 <= m <= p.caravan[3]:
                        yield Discard((y, g, t, m))

    def _discard(self, p: Player, a: Discard, validate: bool = True) -> dict:
        """Resolve a pending over-limit discard with the player's own choice."""
        counts = a.counts
        if validate:
            if self.pending_discard is None:
                raise IllegalAction("no discard is pending")
            if len(counts) != 4 or any(k < 0 for k in counts):
                raise IllegalAction("discard counts must be four non-negative numbers")
            if sum(counts) != self.pending_discard:
                raise IllegalAction(
                    f"must discard exactly {self.pending_discard}, not {sum(counts)}")
            if any(counts[c] > p.caravan[c] for c in range(4)):
                raise IllegalAction("cannot discard crystals you do not have")
        for c in range(4):
            p.caravan[c] -= counts[c]
            self.last_discard[c] += counts[c]
        self.pending_discard = None
        return {"counts": list(counts)}

    def _advance_turn(self) -> None:
        last = (self.current + 1) % self.n == 0  # about to wrap to player 0
        self.current = (self.current + 1) % self.n
        # End after the round in which the trigger fired completes, so every
        # player has had the same number of turns. At n=1 `current` is always
        # 0, so the game ends the instant the solo player claims its target
        # golem — which is exactly what "fewest turns" has to mean.
        if self._end_triggered and self.current == 0:
            self.game_over = True

    # ----- helpers -----
    def _pop_playable(self, p: Player, idx: int, kind) -> MerchantCard:
        if not (0 <= idx < len(p.hand)) or not isinstance(p.hand[idx], kind):
            raise IllegalAction("wrong card / index")
        return p.hand.pop(idx)

    # ----- event log (self.log only — see __init__) -----
    def _build_card_identity(self) -> None:
        """One-time id assignment, built the moment logging turns on for
        this game. `card_id` is a compendium-position string ("merchant:13",
        "golem:7", "start:0"/"start:1") — stable across *games*, since it's
        just each card's fixed index into this game's deck sources
        (self._merchant_source / self._point_source; _setup() only shuffles
        a *copy* of them, so their own order never changes). `instance_id`
        is a plain incrementing int, unique to one physical card copy
        *within this one game* — starting cards get one instance per player
        (same design, same card_id, different copy), everything else gets
        exactly one (there's only one physical copy of each merchant/golem
        card in the whole game).

        Keyed by Python object identity (id(card)), not the cards' own
        dataclass equality — CrystalCard/UpgradeCard/TradeCard are frozen
        dataclasses, so two cards with the same fields compare equal and
        hash the same despite being different physical cards (there's
        exactly one such collision today: the starting "Upgrade 2" and any
        merchant upgrade card that ever ships with steps=2 — none currently
        does, only "Triple upgrade" at steps=3, but nothing stops a future
        compendium edit from adding one). Object identity has no such risk:
        it only ever matches a card against itself.
        """
        self._card_ids: dict[int, str] = {}
        self._instance_ids: dict[int, int] = {}
        next_instance = 0

        def register(card, card_id: str) -> None:
            nonlocal next_instance
            self._card_ids[id(card)] = card_id
            self._instance_ids[id(card)] = next_instance
            next_instance += 1

        for i, c in enumerate(self._merchant_source):
            register(c, f"merchant:{i}")
        for i, c in enumerate(self._point_source):
            register(c, f"golem:{i}")
        # Built fresh per player above (not drawn from a shared list), so
        # every player's own copy gets the same card_id (same design) but
        # its own instance_id (their own physical copy).
        for p in self.players:
            for i, c in enumerate(p.hand):
                register(c, f"start:{i}")

    def _card_ref(self, card) -> dict:
        return {"card_id": self._card_ids[id(card)], "instance_id": self._instance_ids[id(card)]}

    def _caravan_dict(self, caravan: list[int]) -> dict:
        return {"Y": caravan[0], "G": caravan[1], "B": caravan[2], "M": caravan[3]}

    def _counter_dict(self, counter: Counter) -> dict:
        return {
            "Y": counter.get(Crystal.YELLOW, 0),
            "G": counter.get(Crystal.GREEN, 0),
            "B": counter.get(Crystal.TURQUOISE, 0),
            "M": counter.get(Crystal.MAGENTA, 0),
        }

    def _log_action(
        self, seat: int, action_type: str, info: dict, caravan_before: list[int], caravan_after: list[int]
    ) -> None:
        self._turn_counter += 1
        cost_paid = info.get("cost_paid")
        self.event_log.append({
            "type": "action",
            "turn": self._turn_counter,
            "player": seat,
            "action_type": action_type,
            "cards": [self._card_ref(c) for c in info.get("cards", [])],
            "row_index": info.get("row_index"),
            "cost_paid": self._counter_dict(cost_paid) if cost_paid is not None else None,
            "times": info.get("times"),
            "token_awarded": info.get("token_awarded"),
            "caravan_before": self._caravan_dict(caravan_before),
            "caravan_after": self._caravan_dict(caravan_after),
        })

    def _log_game_over(self) -> None:
        self.event_log.append({
            "type": "game_over",
            "turn": self._turn_counter,
            "winner": self._winner_index(),
            "scores": [pl.score() for pl in self.players],
        })

    def to_jsonl(self) -> str:
        """`event_log` as newline-delimited JSON — one line per event, ready
        to append to a self-play data file."""
        return "\n".join(json.dumps(e) for e in self.event_log)

    _PLAY_ACTION_TYPES = ("PlayCrystal", "PlayUpgrade", "PlayTrade")

    def times_played(self, card) -> int:
        """How many times this exact physical card has been played
        (PlayCrystal/PlayUpgrade/PlayTrade) so far this game — a card
        rested back to hand and played again counts each time, since this
        is keyed by the card's own instance_id (see _build_card_identity),
        not just "is it currently in the played pile." Always 0 when
        log=False (nothing was recorded to count) or for a card this game
        never assigned an identity to (e.g. a merchant/golem card that's
        still sitting in the shared deck, never dealt to anyone)."""
        instance_id = self._instance_ids.get(id(card)) if self.log else None
        if instance_id is None:
            return 0
        return sum(
            1
            for e in self.event_log
            if e["type"] == "action"
            and e["action_type"] in self._PLAY_ACTION_TYPES
            and any(c["instance_id"] == instance_id for c in e["cards"])
        )

    # ----- results -----
    def scores(self) -> dict[str, int]:
        return {pl.name: pl.score() for pl in self.players}

    def _winner_index(self) -> int:
        best = max(pl.score() for pl in self.players)
        # tie-break: latest in turn order among the tied wins the tie
        tied = [i for i, pl in enumerate(self.players) if pl.score() == best]
        return tied[-1]

    def winner(self) -> Optional[str]:
        """Most points; ties broken by last player to take a turn."""
        if not self.game_over:
            return None
        return self.players[self._winner_index()].name


# ---------------------------------------------------------------------------
# Decks
# ---------------------------------------------------------------------------
# `Game` plays with the real 43/36-card compendium from century_cards.py by
# default (see _default_decks). The small hand-written decks below predate the
# transcription; they're kept because they're tiny and correct-by-construction,
# which makes them useful for tests that want a short, predictable game. Pass
# them explicitly: Game(names, merchant_deck=SAMPLE_MERCHANT_DECK, ...).
#
# MERCHANT_DECK / POINT_DECK are module-level *overrides*, None by default.
# Setting them (as server/engine_path.py has always done) forces every new
# Game onto those lists; leaving them None uses the compendium.
Y, G, T, M = Crystal.YELLOW, Crystal.GREEN, Crystal.TURQUOISE, Crystal.MAGENTA

MERCHANT_DECK: Optional[list[MerchantCard]] = None
POINT_DECK: Optional[list[PointCard]] = None

SAMPLE_MERCHANT_DECK: list[MerchantCard] = [
    CrystalCard(((Y, 2),), "2 yellow"),
    CrystalCard(((G, 1),), "1 green"),
    CrystalCard(((Y, 1), (G, 1)), "1 yellow 1 green"),
    CrystalCard(((T, 1),), "1 turquoise"),
    UpgradeCard(3, "Upgrade 3"),
    UpgradeCard(2, "Upgrade 2"),
    TradeCard(((Y, 2),), ((T, 1),), "2Y -> 1T"),
    TradeCard(((Y, 3),), ((M, 1),), "3Y -> 1M"),
    TradeCard(((G, 2),), ((M, 1),), "2G -> 1M"),
    TradeCard(((T, 1),), ((G, 2), (Y, 1)), "1T -> 2G1Y"),
    CrystalCard(((Y, 4),), "4 yellow"),
    CrystalCard(((G, 2),), "2 green"),
]

SAMPLE_POINT_DECK: list[PointCard] = [
    PointCard(((Y, 2), (G, 2)), 8, "2Y2G"),
    PointCard(((T, 2),), 9, "2T"),
    PointCard(((M, 2),), 12, "2M"),
    PointCard(((G, 2), (T, 2)), 12, "2G2T"),
    PointCard(((Y, 3), (T, 1)), 8, "3Y1T"),
    PointCard(((G, 3), (M, 1)), 14, "3G1M"),
    PointCard(((T, 1), (M, 1)), 11, "1T1M"),
    PointCard(((Y, 4),), 6, "4Y"),
    PointCard(((G, 4),), 10, "4G"),
    PointCard(((M, 1), (T, 1), (G, 1)), 13, "1M1T1G"),
]


_COMPENDIUM: Optional[tuple[list, list]] = None


def _compendium() -> tuple[list, list]:
    """The real card lists from century_cards.py, imported lazily and cached.

    Lazy because century_cards does `from century_engine import ...` at its
    top — importing it at *this* module's import time would be circular. By
    the time a Game is constructed both modules are fully loaded, so it's safe.

    The fallback covers being imported as `engine.century_engine` (a PEP 420
    namespace package) from the repo root, where a bare `import century_cards`
    can't resolve: century_cards imports the engine flat, so its own directory
    has to be importable.
    """
    global _COMPENDIUM
    if _COMPENDIUM is None:
        try:
            import century_cards as _c
        except ModuleNotFoundError:
            import os
            _here = os.path.dirname(os.path.abspath(__file__))
            if _here not in sys.path:
                sys.path.insert(0, _here)
            import century_cards as _c
        _COMPENDIUM = (_c.MERCHANT_CARDS, _c.POINT_CARDS)
    return _COMPENDIUM


def _default_decks() -> tuple[list, list]:
    """Module-level overrides win; otherwise the compendium."""
    merchant, point = _compendium()
    return (MERCHANT_DECK if MERCHANT_DECK is not None else merchant,
            POINT_DECK if POINT_DECK is not None else point)


# ---------------------------------------------------------------------------
# Smoke test: play a few scripted/random turns and confirm the engine runs.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    g = Game(["Alice", "Bob", "Chris"], seed=42)
    turns = 0
    while not g.game_over and turns < 500:
        acts = g.legal_actions()
        if not acts:
            break
        # naive policy: prefer claiming, else a random legal action
        claim = next((a for a in acts if isinstance(a, Claim)), None)
        g.apply_action(claim or g.rng.choice(acts))
        turns += 1
    print(f"Finished in {turns} turns. Game over: {g.game_over}")
    print("Scores:", g.scores())
    print("Winner:", g.winner())

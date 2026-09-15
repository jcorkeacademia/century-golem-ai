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

WHAT YOU STILL NEED TO DO:
  The photos don't contain the full deck. The card lists near the bottom
  (MERCHANT_DECK, POINT_DECK) are a small, correct-by-construction SAMPLE so
  the engine runs. Transcribe the real 40-ish Merchant cards and 36 Point
  cards from your physical copy into those lists. The engine itself won't
  change — only the data.
"""

from __future__ import annotations
from dataclasses import dataclass, field, replace
from enum import IntEnum
from collections import Counter
from typing import Optional, Iterator
import itertools
import json
import random


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

Action = PlayCrystal | PlayUpgrade | PlayTrade | Acquire | Rest | Claim


class IllegalAction(Exception):
    pass


# ---------------------------------------------------------------------------
# Game state
# ---------------------------------------------------------------------------

class Game:
    POINT_ROW = 5           # face-up point cards
    MERCHANT_ROW = 6        # face-up merchant cards

    def __init__(self, player_names: list[str], seed: Optional[int] = None, log: bool = False):
        if not (2 <= len(player_names) <= 5):
            raise ValueError("Century supports 2–5 players")
        self.seed = seed
        self.rng = random.Random(seed)
        self.players = [Player(n) for n in player_names]
        self.n = len(player_names)
        self.current = 0
        self.game_over = False
        # end trigger: 6th point card in 2–3p, else 5th
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

        self._setup()

    # ----- setup -----
    def _setup(self) -> None:
        # Point deck + row (draw 5)
        deck = list(POINT_DECK)
        self.rng.shuffle(deck)
        self.point_deck = deck
        self.point_row: list[Optional[PointCard]] = [self.point_deck.pop() for _ in range(self.POINT_ROW)]

        # Tokens: coppers above slot 0, silvers above slot 1 (count = players x2)
        self.point_tokens: list[list[Token]] = [[] for _ in range(self.POINT_ROW)]
        self.point_tokens[0] = [Token.COPPER] * (self.n * 2)
        self.point_tokens[1] = [Token.SILVER] * (self.n * 2)

        # Merchant deck + row (draw 6); crystals sitting on row cards
        mdeck = list(MERCHANT_DECK)
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

    # =====================================================================
    #  Legal-action enumeration  (used by AI; also handy for UI validation)
    # =====================================================================
    def legal_actions(self) -> list[Action]:
        if self.game_over:
            return []
        acts: list[Action] = []
        p = self.player

        # --- Play ---
        for i, card in enumerate(p.hand):
            if isinstance(card, CrystalCard):
                acts.append(PlayCrystal(i))
            elif isinstance(card, UpgradeCard):
                acts.extend(PlayUpgrade(i, u) for u in self._upgrade_options(p, card.steps))
            elif isinstance(card, TradeCard):
                acts.extend(self._trade_options(p, i, card))

        # --- Acquire ---
        for j, card in enumerate(self.merchant_row):
            if card is None:
                continue
            if j == 0:
                acts.append(Acquire(0, ()))           # leftmost is free
            elif p.total_crystals() >= j:
                for pay in self._payment_options(p, j):
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

    def _trade_options(self, p: Player, idx: int, card: TradeCard) -> Iterator[PlayTrade]:
        cost = card.cost_counter()
        # max times limited by each cost color available
        max_times = min((p.caravan[c] // n for c, n in cost.items()), default=0)
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

    # =====================================================================
    #  Apply an action
    # =====================================================================
    def apply_action(self, action: Action) -> None:
        if self.game_over:
            raise IllegalAction("game is over")
        p = self.player
        acting_seat = self.current
        caravan_before = p.caravan[:] if self.log else None

        if isinstance(action, PlayCrystal):
            action_type, info = "PlayCrystal", self._play_crystal(p, action)
        elif isinstance(action, PlayUpgrade):
            action_type, info = "PlayUpgrade", self._play_upgrade(p, action)
        elif isinstance(action, PlayTrade):
            action_type, info = "PlayTrade", self._play_trade(p, action)
        elif isinstance(action, Acquire):
            action_type, info = "Acquire", self._acquire(p, action)
        elif isinstance(action, Rest):
            action_type, info = "Rest", self._rest(p)
        elif isinstance(action, Claim):
            action_type, info = "Claim", self._claim(p, action)
        else:
            raise IllegalAction(f"unknown action {action!r}")

        self._enforce_caravan_limit(p)

        if self.log:
            self._log_action(acting_seat, action_type, info, caravan_before, p.caravan)

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
    def _play_crystal(self, p: Player, a: PlayCrystal) -> dict:
        card = self._pop_playable(p, a.hand_index, CrystalCard)
        for color, n in card.gain:
            p.add(color, n)
        p.played.append(card)
        return {"cards": [card]}

    def _play_upgrade(self, p: Player, a: PlayUpgrade) -> dict:
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
        p.hand.pop(a.hand_index)
        p.played.append(card)
        return {"cards": [card]}

    def _play_trade(self, p: Player, a: PlayTrade) -> dict:
        card = p.hand[a.hand_index] if 0 <= a.hand_index < len(p.hand) else None
        if not isinstance(card, TradeCard):
            raise IllegalAction("not a trade card")
        if a.times < 1:
            raise IllegalAction("must trade at least once")
        cost, gain = card.cost_counter(), card.gain_counter()
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

    def _acquire(self, p: Player, a: Acquire) -> dict:
        j = a.row_index
        if not (0 <= j < self.MERCHANT_ROW) or self.merchant_row[j] is None:
            raise IllegalAction("no merchant card there")
        if len(a.payment) != j:
            raise IllegalAction(f"must place exactly {j} crystals")
        pay = Counter(a.payment)
        if not p.has(pay):
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

    def _rest(self, p: Player) -> dict:
        if not p.played:
            raise IllegalAction("nothing to rest")
        cards = list(p.played)
        p.hand.extend(p.played)
        p.played.clear()
        return {"cards": cards}

    def _claim(self, p: Player, a: Claim) -> dict:
        j = a.row_index
        pc = self.point_row[j] if 0 <= j < self.POINT_ROW else None
        if pc is None:
            raise IllegalAction("no point card there")
        cost = pc.cost_counter()
        if not p.has(cost):
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
        # NOTE: player "chooses" which to drop; here we drop cheapest first.
        # For a real UI/AI, surface this as a sub-decision instead.
        while p.total_crystals() > CARAVAN_LIMIT:
            for c in range(4):
                if p.caravan[c] > 0:
                    p.caravan[c] -= 1
                    break

    def _advance_turn(self) -> None:
        last = (self.current + 1) % self.n == 0  # about to wrap to player 0
        self.current = (self.current + 1) % self.n
        # end after the round in which the trigger fired completes
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
        just each card's fixed index into MERCHANT_DECK/POINT_DECK (module
        globals swapped in by server/engine_path.py; _setup() only shuffles
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

        for i, c in enumerate(MERCHANT_DECK):
            register(c, f"merchant:{i}")
        for i, c in enumerate(POINT_DECK):
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
# SAMPLE DECKS  <-- replace with your transcription of the physical cards
# ---------------------------------------------------------------------------
Y, G, T, M = Crystal.YELLOW, Crystal.GREEN, Crystal.TURQUOISE, Crystal.MAGENTA

MERCHANT_DECK: list[MerchantCard] = [
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

POINT_DECK: list[PointCard] = [
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

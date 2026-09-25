"""Step 8: a cheaper Game.clone() for the search.

Measured, Game.clone() costs ~11.5us and is the largest per-child cost in
dfbb. Over half of that is one line: every clone builds a fresh
random.Random(), which seeds itself from the OS (~6us). The engine's own
docstring says a clone's rng is "effectively unused" — the engine only draws
from rng during setup. Another ~2.4us is Counter.copy() on the six row-crystal
Counters, which goes through Counter's general-purpose update path.

fast_clone() is Game.clone() with exactly those two things changed:

    rng            the clone SHARES its parent's rng object instead of
                   building a new one. Safe because nothing after setup draws
                   from it; a test plays whole games and checks the rng state
                   never moves.
    row_crystals   copied as Counter.__new__ + dict.update, which gives an
                   identical Counter without the general-purpose path.

Everything else is copied exactly as the engine does.

Why this lives in solver/ and not in the engine: practice-mode bots call
Game.clone(), so changing it would touch the multiplayer game. The cost of a
second copy routine is that it can drift if the engine gains a field (as it
did when pending_discard arrived in step 3). Two tests guard that: one
compares fast_clone with Game.clone field by field over thousands of
positions, and one fails if a Game ever carries an attribute this module does
not know about.

The brute force in solver.tiny deliberately keeps using Game.clone(), so the
reference the search is checked against does not share this code.
"""

from __future__ import annotations

from collections import Counter

from bots._engine import Game, Player

# Every attribute a Game carries, as Game.clone() copies them. If the engine
# grows a new one, test_fastclone fails until it is added here and below.
KNOWN_FIELDS = frozenset({
    "seed", "rng", "n", "current", "game_over", "win_target", "_end_triggered",
    "_merchant_source", "_point_source", "last_discard", "discard_choice",
    "pending_discard", "players", "point_deck", "point_row", "point_tokens",
    "merchant_deck", "merchant_row", "row_crystals", "log", "event_log",
    "_turn_counter",
})
LOG_FIELDS = frozenset({"_card_ids", "_instance_ids"})   # only when log=True

_new_counter = Counter.__new__
_dict_update = dict.update


def _copy_counter(src: Counter) -> Counter:
    c = _new_counter(Counter)
    _dict_update(c, src)
    return c


def fast_clone(self: Game) -> Game:
    """Game.clone(), minus a fresh rng and Counter's slow copy path."""
    g = Game.__new__(Game)

    g.seed = self.seed
    g.rng = self.rng                 # shared: nothing draws from it after setup
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
    g.row_crystals = [_copy_counter(rc) for rc in self.row_crystals]

    g.log = self.log
    g.event_log = self.event_log[:] if self.log else []
    g._turn_counter = self._turn_counter
    if self.log:
        g._card_ids = self._card_ids
        g._instance_ids = self._instance_ids
    return g

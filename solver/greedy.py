"""Step 5: a starting upper bound `b` for the search.

DFBB prunes any branch where turns spent + h >= b. `h` is weak (roughly
claims left + 1, at most about 7), so `b` does most of the pruning, and the
smaller it starts, the less of the tree the search ever sees.

Any complete, legal plan gives a valid `b`: it is a turn count known to be
achievable. So this module plays the existing bots from `bots/` solo, keeps
the shortest plan, and proves it by replaying it on a fresh game with the
same seed. Measured over seeds 0-19:

    GreedyBot ("medium")        mean 60.6 turns, worst 262
    WeightedBot tuned_split     mean 39.5 turns, worst 50

The solo patch
--------------
WeightedBot's end-of-game scoring (`bots.features.terminal_value`) compares
your score against the best OPPONENT, and a solo game has none, so it crashes
on an empty max(). With nobody to beat, finishing is winning, so the solo
version is one line.

`bots/` is NOT edited: practice mode imports it, and changing it would change
the multiplayer game. Instead `_solo_scoring()` swaps the function in for the
duration of a solo run and always puts the original back, even on error. The
solver runs as its own process and never alongside the server, but restoring
is still cheap insurance, and a test checks it.
"""

from __future__ import annotations

import random
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator, Optional

import bots.features as features
from bots.bots import GreedyBot, WeightedBot
from bots.features import Scales, Weights

from solver.solo import new_solo_game, turns_in

# Solo games by these bots finish in tens of turns. A plan that has not won
# by this many actions is stuck in a loop (arch_rush was seen to do this),
# and is thrown away rather than waited on.
ACTION_CAP = 1000

# Weight sets worth trying. tuned_split is practice mode's "hard" bot and
# the strongest solo; handset_v1 is kept because on some seeds a weaker bot
# finds a shorter line, and b only needs one good plan. arch_rush is left
# out: it failed to finish 4 of 20 solo seeds.
DEFAULT_WEIGHTS = ("tuned_split", "handset_v1")


@dataclass(frozen=True)
class Plan:
    """A complete solo win: what to play, and what it costs."""
    turns: int              # turns_in(actions) — the number b is
    actions: tuple          # every action, Discards included, in order
    bot: str                # which bot found it


@contextmanager
def _solo_scoring() -> Iterator[None]:
    """Swap in solo end-of-game scoring for the duration, then restore."""
    original = features.terminal_value

    def solo_terminal(game, me):
        return features.WIN_VALUE if game.game_over else None

    features.terminal_value = solo_terminal
    try:
        yield
    finally:
        features.terminal_value = original


def _play(seed: int, bot) -> Optional[tuple]:
    """Play one bot solo. Returns the actions if it won, else None."""
    game = new_solo_game(seed=seed)
    actions = []
    while not game.game_over and len(actions) < ACTION_CAP:
        action = bot.choose(game)
        if action is None:
            return None
        game.apply_action(action)
        actions.append(action)
    return tuple(actions) if game.game_over else None


def _makers(weights: tuple[str, ...], include_greedy: bool
            ) -> list[tuple[str, Callable[[int], object]]]:
    scales = Scales.load()
    makers = []
    for name in weights:
        w = Weights.load(name)
        makers.append((name, lambda seed, w=w, name=name:
                       WeightedBot(w, scales, rng=random.Random(seed), name=name)))
    if include_greedy:
        makers.append(("greedy", lambda seed: GreedyBot(seed=seed)))
    return makers


def verify(seed: int, plan: Plan) -> None:
    """Replay `plan` on a fresh game with the same seed; raise if it does not
    win in exactly `plan.turns` turns.

    The same check step 6 runs on DFBB's output, so a starting b can never be
    a number the search then fails to reproduce.
    """
    game = new_solo_game(seed=seed)
    for i, action in enumerate(plan.actions):
        if game.game_over:
            raise AssertionError(f"game ended early, before action {i}")
        game.apply_action(action)
    if not game.game_over:
        raise AssertionError("plan did not finish the game")
    if turns_in(plan.actions) != plan.turns:
        raise AssertionError(
            f"plan claims {plan.turns} turns but replays in {turns_in(plan.actions)}")


def upper_bound(seed: int, weights: tuple[str, ...] = DEFAULT_WEIGHTS,
                include_greedy: bool = True) -> Plan:
    """The shortest verified plan any of the bots finds on this seed.

    Deterministic: each bot's randomness is seeded from `seed`, so the same
    seed always gives the same b.
    """
    best: Optional[Plan] = None
    with _solo_scoring():
        for name, make in _makers(weights, include_greedy):
            actions = _play(seed, make(seed))
            if actions is None:
                continue
            plan = Plan(turns_in(actions), actions, name)
            if best is None or plan.turns < best.turns:
                best = plan
    if best is None:
        raise RuntimeError(f"no bot finished seed {seed}")
    verify(seed, best)
    return best


if __name__ == "__main__":  # pragma: no cover - manual check
    for seed in range(10):
        p = upper_bound(seed)
        print(f"seed {seed}: b = {p.turns:3}  via {p.bot}")

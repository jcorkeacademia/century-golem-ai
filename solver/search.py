"""Step 6: depth-first branch and bound.

Skeleton only — the bodies are yours. The algorithm, from the handover:

    Explore one line of play to the end, record its turn count as the bound,
    then backtrack and skip any branch that provably cannot beat it.

    g  turns taken so far on the current path
    h  a lower bound on turns remaining (solver.bound.h, step 4)
    b  fewest total turns of any complete win found so far

    At each state: if the game is won, set b = g if better. Otherwise, for
    each legal action, prune the child if g + h(child) >= b, else recurse.

Optimal because h never overestimates, so no pruned branch could have been
shorter. The check for this step: the plan it returns, replayed on a fresh
game with the same seed, wins in exactly the turns claimed —
`solver.greedy.verify(seed, plan)` already does that.

Five things that differ from the handover's pseudocode
------------------------------------------------------
1. g is TURNS, not depth. A Discard (step 3) goes through apply_action but
   costs no turn, so a child's g is g + 0 after a Discard and g + 1 after
   anything else. The pseudocode's `g + 1 + h(child)` is wrong the moment a
   caravan overflows. `turns_in` in solver.solo counts the same way.

2. b does not start at infinity. It starts at the step-5 plan from
   solver.greedy.upper_bound, and that plan is also the starting answer: if
   the search never finds anything strictly shorter, the greedy plan WAS
   optimal, and it is what gets returned.

3. Prune on >=, not >. A child that can at best tie b cannot improve on a
   plan you already hold, so there is no reason to enter it.

4. Use legal_actions() with pruned=False. pruned=True caps Acquire at three
   payment options per slot, which is a heuristic cut in the handover's
   sense: faster, but it can lose the optimum. Correctness first; step 7's
   brute-force comparison is where you find out whether pruned=True is
   safe, and step 8 is where it earns a place.

5. h on a child mid-discard is fine. While a Discard is pending the caravan
   briefly holds more than ten crystals, so value(caravan) is too high, the
   deficit too low, and h too SMALL — the safe direction. No special case.

Not in this step: the seen-state table (solver.state.key is ready for it),
move ordering, dominance and the heuristic cuts. Those are step 8, added one
at a time and each re-checked against step 7. `order()` below is the hook
move ordering will plug into; for now it should change nothing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from bots._engine import Acquire, Action, Crystal, Discard, Game
from solver.bound import h
from solver.greedy import Plan, upper_bound, verify
from solver.solo import new_solo_game, turns_in


@dataclass
class Stats:
    """What step 8 compares before and after each speed-up."""
    nodes: int = 0          # states expanded
    pruned: int = 0         # children skipped because g + h >= b
    improved: int = 0       # times b went down
    started: float = field(default_factory=time.perf_counter)

    def elapsed(self) -> float:
        return time.perf_counter() - self.started


@dataclass(frozen=True)
class Result:
    """The answer, and whether it is proven.

    `optimal` is True only if the search ran to completion. If it stopped on
    a budget, `plan` is still the best found — the search is anytime — but it
    is only an upper bound, not a proof.
    """
    plan: Plan
    optimal: bool
    stats: Stats


class OutOfBudget(Exception):
    """Raised inside the recursion to stop early; solve() catches it."""


def turn_cost(action: Action) -> int:
    """What an action adds to g: 0 for a Discard, 1 for anything else."""
    return (0 if isinstance(action, Discard) else 1)


Moves = Callable[[Game], list[Action]]


def all_moves(game: Game) -> list[Action]:
    """Every legal move. The default, and the only one that is exact."""
    return game.legal_actions()


def cheap_payments(game: Game) -> list[Action]:
    """Every legal move, except acquires paid with any blue or magenta.

    The user's rule: an acquire is only ever worth paying for in yellow and
    green. It cuts the dominant cost — Acquire is ~73% of all moves, because
    each payment mix is a separate move — to the yellow/green mixes only.

    NOT proven safe. Paying green keeps yellow a trade might need, and a blue
    paid onto a row card comes back if you later acquire that card. Whether
    it ever loses the optimum is measured in solver.tiny, not assumed.
    """
    return [a for a in game.legal_actions()
            if not (isinstance(a, Acquire)
                    and any(c > Crystal.GREEN for c in a.payment))]


def order(game: Game, actions: list[Action]) -> list[Action]:
    """Move ordering hook. Identity for now.

    Step 8 fills this in — claims first, then efficient trades, so b shrinks
    early. It is a *safe* speed-up: it changes the order children are tried,
    never which ones are, so the optimum survives.
    """
    return actions


def dfbb(game: Game, g: int, path: list[Action], best: dict, stats: Stats,
         node_budget: Optional[int], deadline: Optional[float],
         moves: Moves = all_moves) -> None:
    """Recurse from `game`, having spent `g` turns along `path`.

    `best` holds the incumbent: {"turns": int, "actions": tuple}. Mutate it
    when a strictly shorter win is found; never return a value.

    `path` is one list shared down the whole recursion: append before
    recursing, pop after. Copying it at every level (the handover's
    `path + [action]`) allocates a new list per node for nothing.

    Raise OutOfBudget when `stats.nodes` passes `node_budget` or the clock
    passes `deadline`.

    `moves` lists the moves to try from a state. all_moves (every legal
    move) is exact; anything narrower, like cheap_payments, is a speed-up
    whose effect on the optimum has to be checked.
    """
    stats.nodes += 1
    if node_budget is not None and stats.nodes > node_budget:
        raise OutOfBudget
    if deadline is not None and time.perf_counter() > deadline:
        raise OutOfBudget
    
    if game.game_over: #reach end of game on a path
        if g < best["turns"]: #if the candidate path is better than the best path so far, we update the best path and store the path that brought us there
            best["turns"] = g
            best["actions"] = tuple(path)
            stats.improved += 1
        return

    for action in order(game, moves(game)): #recursion stage
        child = game.clone() 
        child.apply_action(action)

        child_g = g + turn_cost(action) #number of steps it takes to get to a child
        if child_g + h(child) >= best["turns"]: #can't beat best
            stats.pruned += 1; continue #skip to next action, this action will not produce something better 
        path.append(action) #otherwise we explore deeper the branch deeper and look at all the possible actions/pruning from recursing on this node
        dfbb(child, child_g, path, best, stats, node_budget, deadline, moves) #when the call returns, the whole subtree has been explored
        path.pop() #remove the path so it can go to how it was and now we can explore the sibling



def solve(seed: int, node_budget: Optional[int] = None,
          time_limit: Optional[float] = None,
          moves: Moves = all_moves) -> Result:
    """Fewest turns to win on this seed.

        1. Get the starting plan and b from upper_bound(seed).
        2. Run dfbb from a fresh new_solo_game(seed), g = 0, empty path.
        3. Catch OutOfBudget: the answer is then the best so far, unproven.
        4. Verify whatever plan you return — verify(seed, plan) raises if
           it does not replay to a win in exactly plan.turns turns.
    """
    # 1. The greedy plan is both the starting b and the starting answer: if
    #    nothing strictly shorter turns up, it was already optimal.
    start = upper_bound(seed)
    best = {"turns": start.turns, "actions": start.actions}

    # The clock starts after the greedy run, so time_limit is search time.
    stats = Stats()
    deadline = None if time_limit is None else stats.started + time_limit

    # 2. Search from the opening position: no turns spent, empty path.
    # 3. Running out of budget is not an error — the best plan so far is
    #    still a real plan, it just is not proven optimal.
    optimal = True
    try:
        dfbb(new_solo_game(seed=seed), 0, [], best, stats, node_budget,
             deadline, moves)
    except OutOfBudget:
        optimal = False

    found_by = start.bot if stats.improved == 0 else "dfbb"
    plan = Plan(best["turns"], tuple(best["actions"]), found_by)

    # 4. Never hand back a plan that does not replay.
    verify(seed, plan)
    return Result(plan, optimal, stats)


if __name__ == "__main__":  # pragma: no cover - manual check
    import sys
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    r = solve(seed, time_limit=60)
    print(f"seed {seed}: {r.plan.turns} turns, "
          f"{'optimal' if r.optimal else 'NOT proven (budget)'}, "
          f"{r.stats.nodes:,} nodes, {r.stats.pruned:,} pruned, "
          f"{r.stats.elapsed():.1f}s")

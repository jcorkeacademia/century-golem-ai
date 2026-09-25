# Handoff: why does depth-first branch and bound work for StarCraft build orders but not for Century?

## The question for you

We built a solver for a solo version of the board game *Century: Golem Edition*, modelled directly on
**Churchill & Buro (2011), "Build Order Optimization in StarCraft" (AIIDE)**: depth-first branch and
bound (DFBB) with an admissible lower bound. It is correct, meaning it matches brute force wherever brute
force can run. But it cannot solve a real game. In StarCraft the same approach produces build orders
quickly enough to be practical.

**What is structurally different about this problem that makes the same algorithm fail, and what
should we change?** We'd like a diagnosis first, then a ranked list of concrete changes, each labelled
*safe* (keeps optimality) or *heuristic* (faster, may lose optimality).

Everything below is measured unless marked otherwise. Anything said about the StarCraft paper beyond
what our design doc states is from memory, so please check it against the paper instead of trusting it.

---

## 1. The problem

- **One player, a fixed random seed, no opponents.** The seed fixes both shuffled decks, so the
  problem is fully deterministic and observable.
- **Goal:** claim 6 golems (victory-point cards) in the fewest turns. Points don't matter.
- **One action per turn.** There's no time dimension other than the turn count.
- **State:** the caravan (4 crystal colours, yellow < green < blue < magenta, at most 10 crystals at
  the end of any turn), the hand of merchant cards, the played pile, a 6-card merchant row with
  crystals sitting on its cards, a 5-card golem row, both decks, and golems claimed.
- **Actions:**

  | Action | Effect |
  |---|---|
  | Play a crystal card | gain fixed crystals, e.g. +2 yellow |
  | Play an upgrade card | move up to *n* crystals one colour up |
  | Play a trade card | exchange cost → gain, repeated any number of times in one turn |
  | Acquire a merchant card from slot *j* | pay *j* crystals of **any colours**, one onto each card to its left; take the card plus any crystals piled on it |
  | Rest | return every played card to hand |
  | Claim a golem | pay its crystal cost |
  | Discard | if the caravan goes over 10, choose what to throw away. Part of the same turn; costs no turn |

- **Played cards are "borrowed".** They come back only through a Rest, which costs a whole turn and
  produces nothing. In the StarCraft model's terms: required ≈ nothing (there are no prerequisite
  chains), borrowed = played cards, consumed = crystals.

## 2. What the solver does

The code is in `solver/`; the engine is `engine/century_engine.py`, and the engine is the only
implementation of the rules.

- **DFBB** (`solver/search.py`, `dfbb`). The turns spent `g` count Discards as 0. A child is pruned if
  `g_child + h(child) ≥ b`. The incumbent `b` starts from a real plan.
- **Starting incumbent `b`** (`solver/greedy.py`): the best of several existing heuristic bots. For
  seeds 0–9, `b` = 41, 42, 42, 40, 50, 43, 41, 42, 43, 34 turns. **The true optimum is unknown for
  every real seed.**
- **Speed-ups already in place:**
  - Seen-state table: a transposition table keyed by a canonical state key. Hand and played pile are
    unordered; claimed golems are recorded by count only. It skips a state already reached in no
    more turns.
  - Claims-first move ordering.
  - An opt-in *heuristic* rule: acquire payments may use only yellow and green. It has held on 120+
    small boards but isn't proven.
- **Lower bound `h`** (`solver/bound.py`). Crystals are valued in "yellow-equivalents", Y=1, G=2,
  B=3, M=4, optionally capped at the highest colour any remaining golem needs. `owed` is the summed
  value of the cheapest `claims_left` golems remaining.
  `h = claims_left + max(by_caravan, by_potential)`, where:
  - `by_caravan = ceil((owed − caravan value) / 40)`. 40 is what a full caravan can be worth; no turn
    can add more.
  - `by_potential = ceil((owed − Φ) / 10)`, where Φ = caravan value + value of all crystals on the
    row. Acquire only moves crystals between caravan and row, so Φ is unchanged; only card plays
    raise it, by at most 10 per turn (computed exactly per card with the 10-crystal limit applied
    to the output, and confirmed tight on 1,056,859 real turns).
- **Validation:** `h` has never exceeded the true remaining turns (42,749 states from playthroughs;
  98 states with a proven optimum). DFBB agrees with an independent breadth-first brute force on
  every tiny board it can check, and a deliberately inflated `h` is caught.

## 3. What the numbers say

| Measurement | Value |
|---|---|
| Legal moves per state (real games, averaged) | **~21**, of which **73% are Acquire** (every payment colour mix is its own move) |
| …with the yellow/green payment rule | ~12 |
| Game length in turns (good bot) | 34–50; optimum unknown, plausibly 20–30 |
| Search speed (Python) | ~500 states/s originally; ~1,400–1,600/s after the speed-ups |
| Full game from the opening, 60 s | 72,785 states searched and 746,623 children skipped as transpositions; **never beats the bot's plan, never proves anything** |
| Positions with 4/6 golems claimed, 20k-state budget | 4 of 8 finish |
| Positions with 2–3 golems claimed, 20k-state budget | **0 of 8** finish, with the old or the new `h` |
| Opening `h` | 11 (was 8 before the potential bound), against an incumbent of ~40 |
| Building part of `h` over a game | 0–5 turns (was 0–2) |
| Effect of the stronger `h` on mid-game search | only **3–6% more pruning**, no extra positions finished, no shorter plans |
| Per-child cost after optimisation | clone ≈ 2 µs, `h` ≈ 8 µs, state key ≈ 4 µs; the engine's own move listing is significant |

**Our current reading, which we'd like you to test:** DFBB only prunes where `g + h ≥ b`. With `b`
around 40 from a bot and `h` around 11 at the root, nothing is cut until roughly 29 turns deep, and
with ~12–21 moves per turn nothing that deep is ever reached. Within budget the search never finds a
shorter plan, so `b` never tightens. A better `h` moves the pruning line only a few levels, which the
branching factor swamps.

## 4. Candidate explanations to weigh

Our hypotheses, not conclusions:

1. **Depth versus time.** StarCraft actions have durations, so a plan of many actions may span few
   decision points once the simulation fast-forwards to the next moment an action becomes possible.
   Here every action is a full turn, so depth equals plan length, about 40.
2. **Branching.** Prerequisites make most StarCraft actions illegal most of the time. Here almost
   nothing is ever illegal. Acquire payments alone multiply the move count, and trade repeat counts
   add more.
3. **Lower bounds.** In StarCraft, prerequisite chains and build times give strong "you can't have X
   before time T" bounds. Century has essentially no prerequisites, so that kind of bound collapses
   to "one turn per claim". Our value-based bound is admissible but may be structurally weak: it
   ignores forced Rests, which gain nothing, the need to buy engine cards, and colour-specific
   bottlenecks.
4. **Cycles and resource conversion.** Crystals convert up and down through trades, cards cycle
   through Rest, and positions transpose heavily (10 transposition hits per state searched), which
   is unlike a monotone build order.
5. **A poor incumbent.** Bot plans may be 30–50% above optimum, and nothing within budget improves
   on them.
6. **Implementation speed.** Python at ~1.5k states/s versus a C++ system (BOSS) likely orders of
   magnitude faster. This is real, but we suspect it's a constant factor, not the diagnosis.
7. **Macro actions.** From memory, and to be verified: Churchill & Buro search over macro actions
   and prune dominated or useless actions heavily. Our design doc lists Century analogues we haven't
   built yet: "play an upgrade card fully", "Rest then play card X", "fix trade repeats at the
   maximum", "don't buy cards whose outputs no remaining golem needs", "cap total acquisitions".

## 5. Ideas already on the table

- **IDA\*:** use `h` rather than the loose `b` to set the cut-off, so a stronger `h` pays off from the
  first move.
- **A bound that counts forced zero-gain turns:** plays need cards; *n* cards allow at most *n* plays
  between Rests; buying cards costs zero-gain turns too. Minimise plays + rests + acquires + claims.
- **Per-colour bounds** (magenta-grade crystals needed versus magentas producible per turn), taking
  the maximum over several valid bounds.
- **Taking the maximum of `h` over all four value scales**, not just the one `cap_for` picks.
- **Macro actions and action pruning**, as in section 4, item 7.

## 6. Constraints any suggestion must respect

- **The engine is authoritative.** The search calls `legal_actions()` / `apply_action()`. No second
  implementation of the rules, not even a partial one for predicting a move's effect.
- **The solver is a side project.** It must not change `engine/`, `server/` or `web/` behaviour, since
  those run a live multiplayer game. Opt-in engine flags that default to the old behaviour are
  acceptable; they have been done once, for the discard choice.
- **Label every speed-up safe or heuristic,** and check it against the tiny-board brute force
  (`solver/tiny.py`) and the benchmark (`python -m solver.bench`) before trusting it.

## 7. Files, if you have repository access

| File | Contents |
|---|---|
| `solver/search.py` | `dfbb`, `solve`, move lists, orderings |
| `solver/bound.py` | the value scales, `h`, `g_max`, `g_play`, the potential |
| `solver/state.py` | the transposition key |
| `solver/greedy.py` | the starting incumbent from existing bots |
| `solver/tiny.py` | tiny boards and the brute force |
| `solver/bench.py` | the benchmark |
| `HANDOVER.md` | the engine design doc |
| the "Century Solo Solver — Design Handover" PDF | the original plan, with the StarCraft analogy |

*State at the time of writing:* the potential bound in `solver/bound.py` and its tests are finished
and passing but not yet committed.

# API_NOTES.md — the engine as it actually is

**Steps 0–1.** Every name and shape below was verified by running the code,
not read off a doc. Where `BOT_IMPLEMENTATION_PROMPT.md` assumes something
that isn't true, §4 says so.

§§1–5 record the engine **as Step 0 found it**, and §4 is the mismatch list
that produced Step 1's work. §6–7 are Step 1's results. Where Step 1 changed
something §§1–5 describes, the line is marked `[Step 1: ...]` — the
before-picture is kept because §4's reasoning depends on it.

Engine source: `engine/century_engine.py` (706 lines), `engine/century_cards.py`
(179 lines). Read those before trusting any summary, including this one.

---

## 1. Getting the engine imported

`engine/` has **no `__init__.py`**, and `century_cards.py` imports the engine
*flat*:

```python
from century_engine import (Crystal, CrystalCard, ...)   # century_cards.py:18
```

Measured from the repo root, in a fresh process, with no `sys.path` changes:

| statement | result |
|---|---|
| `import engine.century_engine` | OK (PEP 420 namespace package) |
| `from engine.century_engine import Game` | OK |
| `import engine.century_cards` | **`ModuleNotFoundError: No module named 'century_engine'`** |

So the engine module imports as a package but the compendium does not. This
collides with brief §0.6 ("run everything from the repo root as modules, no
`sys.path` hacks") — see §4.3 for the options.

**What works today** is what `server/engine_path.py` does: put `engine/` on
`sys.path`, import flat, then swap the decks.

```python
import sys; sys.path.insert(0, "<repo>/engine")
import century_engine as E, century_cards as C
E.MERCHANT_DECK = C.MERCHANT_CARDS
E.POINT_DECK    = C.POINT_CARDS
```

---

## 2. Verified API surface

### 2.1 `Game`

```python
Game(player_names, seed=None, log=False, merchant_deck=None, point_deck=None)
#                                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ [Step 1]
```

- 2–5 players (`ValueError` outside that).
- ~~**There is no deck parameter.** Decks are read from the *module globals*
  `century_engine.MERCHANT_DECK` / `POINT_DECK` at `_setup()` time. Those default
  to a 12-card / 10-card **sample deck**, not the real compendium (43/36).~~
  **[Step 1]** Decks now resolve: explicit argument → module global override →
  the real compendium. The globals default to `None`; the old sample decks are
  `SAMPLE_MERCHANT_DECK` / `SAMPLE_POINT_DECK`. See §7.1.
- `log=True` is undocumented in the brief. It enables `event_log` and costs a
  per-action dict build; leave it **off** for search and tuning.

Class constants: `Game.POINT_ROW = 5`, `Game.MERCHANT_ROW = 6`.
Module constant: `CARAVAN_LIMIT = 10`.

| member | signature / type | notes |
|---|---|---|
| `legal_actions(pruned=False)` | `-> list[Action]` | `pruned` added in Step 1.5; default output unchanged |
| `apply_action(action, validate=True)` | `-> None` | `validate` added in Step 1.6; raises `IllegalAction` |
| `scores()` | `-> dict[str, int]` | **keyed by player NAME — see §4.4** |
| `winner()` | `-> Optional[str]` | name, not index; `None` until `game_over` |
| `_winner_index()` | `-> int` | private; ties → **highest seat** (`tied[-1]`) |
| `player` | property `-> Player` | `players[current]` |
| `to_jsonl()` | `-> str` | `log=True` only |
| `times_played(card)` | `-> int` | `log=True` only; returns 0 otherwise |

Readable state, all confirmed present:

| attribute | type | notes |
|---|---|---|
| `current` | `int` | seat index whose turn it is |
| `players` | `list[Player]` | seating order |
| `n` | `int` | player count |
| `game_over` | `bool` | |
| `win_target` | `int` | 6 for 2–3p, 5 for 4–5p (verified: 2p → 6) |
| `point_row` | `list[Optional[PointCard]]` | length 5; **slots can be `None`** when the deck runs dry |
| `merchant_row` | `list[Optional[MerchantCard]]` | length 6; same `None` caveat |
| `row_crystals` | `list[Counter]` | length 6, parallel to `merchant_row` |
| `point_tokens` | `list[list[Token]]` | length 5; only slots 0 and 1 ever filled |
| `point_deck` | `list[PointCard]` | **order is hidden information** — see §5.1 |
| `merchant_deck` | `list[MerchantCard]` | same |
| `seed`, `rng` | `int|None`, `random.Random` | |
| `log`, `event_log`, `_turn_counter` | `bool`, `list[dict]`, `int` | |
| `_end_triggered` | `bool` | private; **[Step 1]** public `end_triggered` property added — see §4.4 |
| `last_discard` | `list[int]` | **[Step 1]** per-color counts dropped by the caravan limit, reset each action |

~~**Not present**: `clone`, `shuffle_hidden`, `last_discard`.~~
**[Step 1]** All three now exist — see §7.1.

### 2.2 `Player`

```python
@dataclass
class Player:
    name: str
    caravan: list[int]              # length 4, indexed by Crystal — COUNTS
    hand: list[MerchantCard]
    played: list[MerchantCard]
    point_cards: list[PointCard]
    tokens: list[Token]
```

Methods: `total_crystals() -> int`, `add(color, n=1)`, `remove(color, n=1)`
(raises `ValueError` if short), `has(counter) -> bool`, `score() -> int`.

`score()` = golem points + `sum(int(t) for t in tokens)` + one point per
non-yellow crystal. Golem points alone are `sum(pc.points for pc in point_cards)`
— derived, never stored.

### 2.3 Actions — exactly as the brief describes

```python
PlayCrystal(hand_index: int)
PlayUpgrade(hand_index: int, upgrades: tuple[Crystal, ...])   # ordered, len <= card.steps
PlayTrade(hand_index: int, times: int)                        # >= 1
Acquire(row_index: int, payment: tuple[Crystal, ...])         # len == row_index
Rest()
Claim(row_index: int)
```

All frozen dataclasses. `Action` is their union; `IllegalAction(Exception)`.

### 2.4 Cards

| class | fields | helpers |
|---|---|---|
| `CrystalCard` | `gain: tuple[tuple[Crystal,int],...]`, `name` | `as_counter()` |
| `UpgradeCard` | `steps: int`, `name` | — |
| `TradeCard` | `cost`, `gain`, `name` | `cost_counter()`, `gain_counter()` |
| `PointCard` | `cost`, `points: int`, `name` | `cost_counter()` |

All **frozen dataclasses → compared by value, not identity.** Two cards with
identical stats are `==` and hash the same. The shipped compendium is
content-unique today, so this only bites if you key a dict by card; key by
`id(card)` when you mean a specific physical card.

`Crystal`: `YELLOW=0, GREEN=1, TURQUOISE=2, MAGENTA=3`, with `.can_upgrade`
(`False` only for MAGENTA). `Token`: `COPPER=3, SILVER=1` — the enum *value is
the point value*, so `int(token)` scores directly.

### 2.5 `event_log`

Present, `log=True` only. `list[dict]`; one `game_start`, one `action` per
turn (with `caravan_before`/`caravan_after`, `cost_paid`, `times`,
`token_awarded`, and stable `card_id`/`instance_id` refs), one `game_over`.
Not needed until Step 10 contribution logs, and it costs throughput, so keep
it off for tuning.

---

## 3. Step 0 benchmark

100 random-play 2-player games, real 43/36 compendium, Python 3.13.14,
single process. Random policy = uniform over `legal_actions()`.

```
games/sec              67.7
actions/sec            24,674
mean actions/game      364.2      (median 287, min 140)
mean legal_actions len 19.2       (max observed 149)
mean ms per action     0.041
mean golems claimed    4.67 per player
mean final score       69.9
```

Mean game length (364) matches `BOT_RULES_REFERENCE.md` §5's "~330 actions".
**Mean per-action cost does not:** that doc reports ~14 ms, this measures
0.041 ms — a ~340× gap. The doc's figure came from a harness running
invariant checks on every action; 0.041 ms is the engine alone. Budget
rollouts off 0.041 ms.

### 3.1 Where the time goes

Over 5,660 actions in 20 games:

| | time | share |
|---|---|---|
| `legal_actions()` | 0.211 s | **90.9%** |
| `apply_action()` | 0.021 s | 9.1% |

Enumeration is the whole cost. Step 1.5's pruning is the single highest-leverage
change in the plan, and Step 1.6's `validate=False` fast path targets the 9%.

> **Corrected in Step 1.** That 91% is real but it describes a *random
> rollout*, where `apply_action` is the only other work. A bot's loop also
> clones and scores a position per candidate move (~25 µs each), which dwarfs
> enumeration (~50 µs for the whole list). For bot workloads the number that
> matters is **list length**, not enumeration time. See §7.

### 3.2 What enumeration wastes

`Acquire` dominates branching — at a full caravan `[3,3,2,2]` with a 6-card
row, `legal_actions()` returns 102 actions of which **86 are `Acquire`**.
`_payment_options` builds every `itertools.combinations` of the expanded
crystal list and then dedupes to multisets:

| j | raw combinations | distinct multisets | wasted |
|---|---|---|---|
| 1 | 10 | 4 | 2.5× |
| 3 | 120 | 18 | 6.7× |
| 5 | 252 | 28 | 9.0× |

`_upgrade_options` dedupes by **sequence**, not by resulting caravan, so it
emits up to ~2× redundant options (`[4,3,3,0]` with a 3-step card: 40 sequences
→ 20 distinct caravans). Step 1.5 collapses both.

### 3.3 Game length vs Step 5's turn cap

| p50 | p75 | p90 | p95 | max |
|---|---|---|---|---|
| 288 | 386 | 440 | 648 | **never terminated** |

**1 game in 100 did not finish in 20,000 actions.** This is not a bug — a
random policy can cycle play/Rest indefinitely without ever assembling a golem
cost, and once both decks are exhausted the row stops offering new material.
Step 5's 1,000-action cap is genuinely load-bearing, and at 1% of *random*
games it's cheap. Real bots claim golems, so expect ~0% capped there; if a
tuned bot starts hitting the cap, that's a finding about the bot, not noise.

---

## 4. Mismatches with the brief

Ordered by how much they can hurt.

### 4.1 `scores()` silently collides on duplicate names — **fix before Step 5**

```python
Game(["bot", "bot"]).scores()   ->   {'bot': 0}      # len 1, not 2
```

It's a dict comprehension over `pl.name`. Two bots of the same type in one
match — the obvious arena lineup — silently lose a player's score, and
`winner()` returns a name that matches two seats. The arena must assign unique
seat-tagged names (`"greedy@0"`), and every internal comparison should use
**seat index**, via `[p.score() for p in game.players]` rather than `scores()`.
Not an engine bug for the server (real players have distinct names), so per
brief §0.3 I'm flagging rather than changing it.

### 4.2 The compendium is not loaded by default

`MERCHANT_DECK`/`POINT_DECK` default to a 12/10-card sample. Anything that
forgets the swap silently plays a different game. Already Step 1.1; noting it
because every Step 0 measurement above had to do the swap by hand, and
`century_trace.py` still doesn't (HANDOVER §8.6).

### 4.3 `python -m bots.x` cannot import the compendium (brief §0.6)

Per §1: `import engine.century_cards` fails from the repo root because the file
imports `century_engine` flat. Three ways out:

1. **Add `engine/__init__.py` and make the two imports relative.** Cleanest,
   but touches engine files and is *not* on Step 1's allowed-edits list, and
   CLAUDE.md warns about renaming/moving these files. Would also need
   `server/engine_path.py` re-checked.
2. **A `bots/_engine.py` shim** that does the `sys.path` insert + deck swap
   once, and have every bot module do `from bots._engine import Game, ...`.
   Zero engine edits. Technically the "`sys.path` hack" §0.6 rules out, but
   confined to one file that mirrors the server's existing approach.
3. Leave it and run scripts from `engine/`. Contradicts §0.6 outright.

**I recommend option 2** and will use it unless told otherwise — it keeps
Step 1's edit list honest and matches how the server already solves this.

### 4.4 No public end-trigger accessor

Brief §2.7 needs "if the end is triggered and `me` has no turns left this
round". The only source is `game._end_triggered` (private). `game_over` flips
in `_advance_turn` when `current` wraps to 0. Options: read the private
attribute, or derive it as
`any(len(p.point_cards) >= game.win_target for p in game.players)` — which is
exactly equivalent, since `_end_triggered` is set only at `_claim` when that
condition first holds and is never cleared. **The derived form is safer** (no
private access, same answer); use it unless Step 1 adds a property.

### 4.5 `PlayUpgrade(i, ())` is a legal, offered action

`_upgrade_options` yields the empty tuple first, so "play an upgrade card and
upgrade nothing" is in `legal_actions()` — it burns the card to the played
pile for zero gain. Verified: a fresh seat-0 hand offers `[(), (0,), (0,0),
(0,1)]`. It's rules-correct (every step is optional) but it is never the best
move outside contrived positions, and a WeightedBot *will* pick it if the
weights happen to favour emptying the hand. Watch for it in `explain()` output;
Step 1.5's pruning should probably drop it when any non-empty option exists.

### 4.6 Smaller confirmations (brief was right)

- `_enforce_caravan_limit` drops **cheapest-first**, deterministically, to 10 —
  as brief §2.5 and §5.4 assume.
- `Claim` requires exact colors (`p.has(cost_counter())`), so §2.3's shortfall
  model is correct.
- `_reflow_tokens` moves the whole silver **list** to slot 0 when copper
  empties, leaving slot 1 empty — feature #9's "account for silver sliding" is
  a real case.
- `win_target` = 6 (2–3p) / 5 (4–5p). Confirmed 6 at 2p.
- Seat starting crystals are fixed, not randomized: `{0:[3,0], 1:[4,0],
  2:[4,0], 3:[3,1], 4:[3,1]}`. Combined with the highest-seat tie-break, seat
  asymmetry is real — brief §5.6's seat rotation is required, not optional.

### 4.7 Environment

`numpy 2.4.2` and `pytest 9.0.3` are installed. **`cma` is not** — needed at
Step 6, `pip install cma` before then.

---

## 5. Standing constraints

### 5.1 The hidden-information line

`game.merchant_deck` and `game.point_deck` are plain lists sitting in memory,
fully readable. Brief §0.2: bots may use deck **composition** (derivable from
the compendium minus everything visible) but never **order**. In practice:

- Never index into either deck, never read `deck[-1]`, never iterate it in a
  feature.
- `len(deck)` is fine — the server publishes counts (`CONTRACT.md`).
- Applying `Acquire`/`Claim` to a clone pops the *true* next card. Step 1.3's
  `shuffle_hidden(rng)` on the clone first is what keeps this honest (brief
  §5.3), and it is easy to forget.

### 5.2 Cloning

`copy.deepcopy(Game)` on a mid-game state measures **0.726 ms** — already near
Step 1.2's <1 ms target, but it deep-copies every frozen card object, which is
pure waste. Cards are immutable and shared with the module-level deck lists, so
a manual clone copies only: the four `Player` lists per seat, `caravan`,
`point_row`/`merchant_row` (shallow), `row_crystals` (per-`Counter` copy),
`point_tokens` (per-list copy), both decks (shallow), and the scalars. Expect
a large multiple of the deepcopy figure.

Note `rng` — a cloned `Game` shares or copies a `random.Random`; decide
deliberately, since `shuffle_hidden` takes its own rng anyway.

---

## 6. Proposed next action

Step 1, as written, plus one addition: the `bots/_engine.py` shim from §4.3,
and unique seat-tagged bot names to dodge §4.1. Neither touches `engine/`.

---

## 7. Step 1 results

### 7.1 What changed in `engine/century_engine.py`

| change | shape |
|---|---|
| compendium default | `Game(..., merchant_deck=None, point_deck=None)`; module globals `MERCHANT_DECK`/`POINT_DECK` are now `None`-by-default *overrides*; old sample decks renamed `SAMPLE_MERCHANT_DECK`/`SAMPLE_POINT_DECK` |
| `Game.clone()` | manual copy, shares frozen card objects |
| `Game.shuffle_hidden(rng)` | reshuffles both undrawn decks in place |
| `Game.last_discard` | `list[int]` per-color, reset at the top of every action |
| `Game.end_triggered` | public read-only property over `_end_triggered` (§4.4) |
| `legal_actions(pruned=False)` | default output unchanged |
| `apply_action(action, validate=True)` | default behavior unchanged |

Precedence for decks: explicit argument → module global → compendium.

### 7.2 Benchmarks

**Clone** — mid-game 2p state:

| | per call |
|---|---|
| `copy.deepcopy(game)` | 0.7085 ms |
| `game.clone()` | **0.0112 ms** (63× faster) |

This is the change that makes search viable at all, and it beats the brief's
<1 ms target by ~90×.

**Pruning** — measured two ways, and the difference matters:

| state source | mean list, full | mean list, pruned | cut |
|---|---|---|---|
| random play | 20.1 | 17.7 | 12% |
| heuristic play | 22.2 | **12.9** | **42%** |

Random play acquires every chance it gets and strips the merchant row bare, so
`Acquire` — the thing pruning cuts hardest — barely appears. On states from
heuristic play (row stays full, which is what a real bot sees) the row is 6/6
cards and Acquire is 66% of the action list:

| kind | full | pruned | cut | % of list |
|---|---|---|---|---|
| Acquire | 21,803 | 8,876 | **59%** | 66% |
| PlayUpgrade | 4,598 | 3,657 | 20% | 14% |
| PlayTrade | 3,114 | 3,114 | 0% | 9% |
| PlayCrystal | 2,421 | 2,421 | 0% | 7% |
| Rest | 1,165 | 1,165 | 0% | 4% |
| Claim | 130 | 130 | 0% | 0% |

**Trade repeat counts cannot be deduplicated.** Repeating a trade `t` times
moves the caravan by `t·(gain − cost)`, so two counts collide only if
`gain == cost` — a no-op trade, and no card in the compendium is one. They are
all genuinely distinct choices. If trade branching ever needs cutting it has
to be *lossy* (cap the repeat count), which is beyond the brief's mandate.

**The bot's real loop** — enumerate, then clone + `shuffle_hidden` + apply +
score every candidate, over 400 heuristic-play states:

| | moves | per decision | per move |
|---|---|---|---|
| full list | 8,631 | 0.546 ms | 25.3 µs |
| pruned + `validate=False` | 4,951 | **0.311 ms** | 25.1 µs |

**1.76× faster per decision**, entirely from evaluating 43% fewer moves.
`validate=False` is worth <1% (25.3 → 25.1 µs), exactly as §Step 1 predicted —
`apply_action` never re-enumerated, so there was little to skip.

### 7.3 Correctness

- **Golden trace:** 12,083 recorded states across 40 games at 2/3/4/5 players,
  captured before the edits, byte-identical after (sha `31a4b90d…`). Default
  `legal_actions()` output, full game states, final scores and winners all
  unchanged.
- **38 tests pass** (`bots/tests/test_engine_step1.py`), the repo's first. The
  load-bearing one is `test_pruned_is_a_subset_of_legal`: every pruned option
  must be an option the full enumeration offers, checked across 2/3/5-player
  games.
- **Server verified live**, not just by inspection: `uvicorn main:app`, two
  websocket clients, a real game started and played, real compendium on the
  wire (37+6 merchant, 31+5 golem). Illegal actions still rejected with the
  engine's own messages (`nothing to rest`, `cannot pay point-card cost`).
- **Tracer** now defaults to the real cards — HANDOVER §8.6 / CLAUDE.md's
  second owed fix, closed as a side effect of the deck change.

### 7.4 Deviations from the brief

1. **Acquire's third payment heuristic is a stand-in.** The brief asks for "a
   mix that keeps colors needed for my best target", which needs TTC (Step 2).
   Shipped instead: *preserve* — spend without emptying any color entirely.
   Swap it in `_payment_options_pruned` once features exist.
2. **`PlayUpgrade(i, ())` is kept**, against §4.5's own suggestion. It is the
   only way to discard an upgrade card without touching the caravan, which is
   strictly best when every available step would break a golem cost you can
   already afford (holding exactly 2Y for a 2Y golem). Costs one action.
3. **The remaining owed engine fix is untouched:** the over-10 caravan discard
   is still automatic, not a player sub-decision (HANDOVER §8.1). Out of scope
   for Step 1, and features #20–21 plus the sim's limit rule assume the current
   cheapest-first behavior.

---

## 8. Step 2 results

`bots/sim.py` — the solitaire simulator. Nothing in it mutates a `Game`; it
works on tuples of ints, which is what makes it cheap enough to call millions
of times.

### 8.1 Surface

| name | what |
|---|---|
| `YE = (1,2,3,4)` | yellow-equivalent value per colour; one constant, so tuning can replace it |
| `ye_of(caravan)` | total YE held |
| `nominal_output(card)` | YE a card produces per play; negative for trade-down cards |
| `throughput(player)` | mean YE per turn over owned cards, `/(n+1)` for the Rest turn |
| `shortfall(caravan, cost)` | upgrade steps from here to payable; 0 means claimable |
| `can_pay(caravan, cost)` | exact-colour affordability |
| `enforce_limit(caravan)` | the engine's cap as a pure function |
| `ttc(player, golem, depth=3)` | turns-to-claim |
| `ttc_row(player, point_row, depth=3)` | TTC for the whole row, `None` for empty slots |
| `card_id`, `card_ids`, `cost_of` | compact ids for cache keys |
| `clear_cache()`, `cache_size()` | the memo table |

### 8.2 Card identity is keyed on mechanics, not name

The engine builds its own starting cards — `CrystalCard(((Y,2),), "Create 2")`
— which are **not equal** to `century_cards.STARTING_CARDS`
(`"Create 2 (+2Y)"`), because frozen-dataclass equality includes `name`. Keying
the cache on card equality or identity would treat every starting card as
unknown. `card_id` therefore hashes a card's *mechanics* only:
`(CRYSTAL, gain)` / `(UPGRADE, steps)` / `(TRADE, cost, gain)`.

Two mechanically identical cards then share an id — which is correct, not a
collision: they are interchangeable for simulation, so sharing an id makes the
cache hit more often at no cost in accuracy.

### 8.3 Performance

Positions sampled from heuristic play (1,200 states, TTC for every golem on
the row for both players — 12,000 calls), depth 3:

| | per call |
|---|---|
| cold cache (cleared per position) | **0.349 ms** |
| warm cache (shared) | **0.262 ms** |

Comfortably inside the brief's 1 ms target. Cost by depth, so Step 6 can price
the hyperparameter:

| depth | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| ms/call | 0.036 | 0.089 | **0.201** | 0.430 | 0.722 |

Depth 4 is still affordable if tuning wants it; depth 5 is not, at scale.

Optimising after the first profile roughly halved the cost — `shortfall` was
the top hotspot at 215k calls, and batching its matching per level instead of
per crystal took it from 0.534 s to 0.168 s of profile time. `_successors` is
now the top entry, and the remaining fat is tuple-sorting for cache keys
(~5%); not worth chasing at 4× headroom.

### 8.4 What TTC returns

12,000 values at depth 3: mean 3.66, median 3.0.

```
 0 turns    196   1 turns  1,344   2 turns  2,463   3 turns  2,328
 4 turns  2,089   5 turns  1,465   6 turns    964   7 turns    558
 8 turns    266   9 turns    178  10 turns     74  11+        75
```

**53% of values are found by the search; 47% are extrapolated** from the
fallback (`depth + ceil(shortfall at the best leaf / throughput)`). That is a
lot of estimate, and it is the number to watch: a feature built on TTC is, half
the time, built on an extrapolation rather than a plan. Raising the default
depth to 4 is the obvious lever and costs about 2×.

Sanity check: the lowest-TTC golem on the row is also the lowest-shortfall one
in 85% of positions. The 15% where they disagree is TTC doing its job — seeing
that a card in hand closes a bigger gap faster than a smaller gap can be closed
without one.

### 8.5 Cost of a bot decision, with TTC on every candidate

One position, evaluating every legal move (clone + shuffle + apply + TTC for
the whole row for both players):

| | moves | per decision |
|---|---|---|
| full list | 49 | 6.76 ms |
| pruned list | 17 | **2.18 ms** |

TTC now dominates a decision (~128 µs/move against ~25 µs in Step 1), which is
expected — it is the expensive part of the value function, and the reason
Step 3 must compute it **once per evaluated state and reuse it** across
features rather than calling it per feature.

### 8.6 Deviations from the brief

None. All four required TTC cases are tested (1-turn with the upgrade in hand,
2-turn with it in the played pile, 0 when already payable, fallback above
depth), plus the "has magenta, needs green" shortfall case.

One judgement call worth recording: the fallback uses the shortfall at the
**best leaf reached**, not at the starting state, exactly as the brief
specifies. The difference is large — for an empty caravan chasing 5M it is
19 turns rather than 23 — and it is easy to get wrong, so there is a test
pinning the arithmetic.

---

## 9. Step 3 results

`bots/features.py` (features, value function, `explain`) and
`bots/calibrate.py` (scales). 47 new tests; 122 pass overall.

### 9.1 The twelve core features

| key | group | sym | what |
|---|---|---|---|
| `golem_points` | score | ✓ | points on claimed golems |
| `token_points` | score | ✓ | copper×3 + silver×1 |
| `cry_y/g/b/m` | caravan | – | crystals held, per colour |
| `best_target` | targets | ✓ | max over row of `points / (1 + TTC)` |
| `token_race` | targets | – | token value / (1 + TTC) over the two token slots |
| `throughput` | engine | ✓ | mean YE/turn over owned cards |
| `playable_now` | hand | – | usable output sitting in hand |
| `exhausted` | hand | – | output locked in the played pile |
| `dead_hand` | hand | – | 1 when the hand can produce nothing |

Only four are `symmetric` — the ones worth measuring an opponent by. Your
leftover yellow is not a thing to deny someone.

`token_race` gets the silver-reflow rule for free by reading the pile's own
top token: once copper empties the engine slides silver into slot 0, so
whatever sits there is what you would actually be handed. Tested directly.

### 9.2 `Ctx` — the reason this is affordable

Step 2 measured TTC at ~0.2 ms a call, dominating a decision. `Ctx` computes
`ttc_row` once per (state, player) and shares it with every feature.
`test_ctx_computes_ttc_once_per_player` pins this with a call counter — it is
the kind of thing that silently regresses into a 5× slowdown.

### 9.3 Terminal handling uses seat, not name

`terminal_value` identifies the winner by `_winner_index()`, not
`winner()`. The name form walks straight into API_NOTES §4.1 — two bots of
the same type in one match share a name, and the win/loss sign would be
wrong for one of them. Pinned by `test_terminal_uses_seat_not_name`.

### 9.4 Calibration and the scale trap

200 TempGreedyBot self-play games, 21,164 observations, ttc_depth 3:

| feature | mean | std | p95 | zero% | **norm p95** |
|---|---|---|---|---|---|
| golem_points | 26.96 | 19.44 | 60.0 | 14% | 3.09 |
| token_points | 1.45 | 1.88 | 6.0 | 48% | 3.19 |
| cry_y | 2.50 | 1.96 | 6.0 | 19% | 3.06 |
| cry_g | 1.74 | 1.67 | 5.0 | 31% | 2.99 |
| cry_b | 0.80 | 1.07 | 3.0 | 54% | 2.80 |
| cry_m | 0.36 | 0.71 | 2.0 | 75% | 2.81 |
| best_target | 4.65 | 3.15 | 12.0 | 0% | 3.81 |
| token_race | 0.86 | 0.48 | 1.8 | 0% | 3.66 |
| throughput | 1.89 | 0.42 | 2.5 | 0% | **5.97** |
| playable_now | 5.19 | 5.35 | 16.0 | 16% | 2.99 |
| exhausted | 6.26 | 6.55 | 20.0 | 15% | 3.05 |
| dead_hand | 0.16 | 0.37 | 1.0 | 84% | 2.70 |

**The trap did not materialise, but the guard is worth keeping.** The brief's
`scale = max(std, 1e-6)` has a floor that protects against nothing: a feature
that barely varies gets a small std, and dividing by it amplifies that
feature. The diagnostic that actually matters is `norm p95 = p95 / scale` —
what a weight of 1.0 buys in a strong position. All twelve land between 2.70
and 5.97, so a weight means roughly the same thing for each and hand-set
weights are directly comparable. `calibrate.py` flags anything outside
(1.5, 6.0) rather than shipping it silently.

`throughput` at 5.97 sits at the edge of the band — it is nearly constant in
real play (mean 1.89, std 0.42, range 1.33–2.9), so normalising inflates it
almost 6×. Watch its weight: a hand-set 0.5 is really more like a 3.0.

**Scales depend on the sampling policy.** They come from TempGreedyBot, a
stand-in for Step 4's GreedyBot. Recalibrate once the real one exists,
and note that every weight fitted against the old scales is then stale.

### 9.5 `explain()` works, with one caveat

```
seat 1 (B)  caravan [4, 4, 0, 0]  phase 0.33  14 legal moves
#1 PlayTrade(hand 5, x1)      V=+7.64
   throughput +2.52   best_target +1.91   token_race +1.42   cry_m +1.27 ...
#2 PlayCrystal(hand 2)        V=+6.92
   throughput +2.52   best_target +2.03   token_race +1.42 ...
```

**Several contributions are identical across moves** — `golem_points +1.08`,
`token_points +0.96`, `-opp:throughput -1.19` appear on every line, because
one action rarely changes them. They inflate V without discriminating. The
ranking is still correct (a constant added to every candidate cannot change
the order), but for *reading* the bot, the differences are what matter. A
delta view against the best alternative would be more legible; worth adding
when the analysis in Step 10 needs it.

### 9.6 Deviations from the brief

1. **TempGreedyBot** is a throwaway sampler, as §Step 3.3 permits. The real
   GreedyBot lands in Step 4 and the scales must be recomputed then.
2. **`norm p95` is an addition**, not in the brief. The brief's own scale
   formula is kept exactly; this is a diagnostic on top of it.

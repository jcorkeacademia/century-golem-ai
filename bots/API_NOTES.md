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

# Century: Golem Edition — Rules & Bot-Design Reference

Written for planning bot features. Everything here is grounded in the actual
implementation (`engine/century_engine.py`, `engine/century_cards.py`,
`CONTRACT.md`) rather than the abstract rulebook — where this app's rules
deviate from the physical game, that's called out explicitly, because those
deviations change what a bot needs to handle. Cross-references: `CLAUDE.md`
(engine gotchas), `HANDOVER.md` (original design doc — §7/§8 of that doc are
the direct ancestor of this one).

---

## 1. What the game is

A caravan/engine-building game for 2–5 players. You collect and refine
crystals (four colors, ranked cheap→expensive) and spend them to claim golem
cards, which are the only source of victory points during play. First to
claim enough golems ends the game; highest total score wins.

There is no combat, no hand-to-hand interaction, no blocking — the only
head-to-head pressure is **contention over a shared, shrinking pool of
resources** (which merchant cards and golem cards are available *right now*,
and whether someone else claims what you were saving up for). This makes it
much closer to a solitaire optimization problem with opponents racing you for
the same finite goals than to an adversarial game like chess.

---

## 2. Components, as the engine models them

**Crystals** — four colors, strictly ordered by the upgrade chain:

| Color | Engine name | Index | Upgrades to |
|---|---|---|---|
| Yellow | `Crystal.YELLOW` | 0 | Green |
| Green | `Crystal.GREEN` | 1 | Turquoise |
| Turquoise ("Blue") | `Crystal.TURQUOISE` | 2 | Magenta |
| Magenta | `Crystal.MAGENTA` | 3 | — (`can_upgrade` is `False`) |

A player's holdings (`Player.caravan`) are **counts**, not individual tokens
— `[3, 2, 0, 1]` means 3 yellow, 2 green, 0 turquoise, 1 magenta. There's no
identity to an individual crystal beyond its color; two yellows are
completely interchangeable. Physical supply is unlimited in this engine
(HANDOVER §8.5) — the rulebook's "substitute if exhausted" is modeled as no
cap at all, so a bot never has to reason about crystal scarcity across
players, only about what's in *its own* caravan.

**End-game crystal value**: yellow is worth 0, every other color is worth 1,
counted from whatever's left in your caravan when the game ends. This is a
real, easily-missed source of points — a caravan full of magenta you never
spent is not wasted, it's banked value.

**Merchant cards** (43 in the shipped compendium) — three kinds:
- **Crystal card**: gain a fixed bundle immediately (e.g. "+2Y").
- **Upgrade card**: perform up to N single-step upgrades, each optional,
  each on any crystal you choose — including upgrading the *same* crystal
  multiple times in one play (Y→G→B is two steps on one crystal, legal on a
  2-step card).
- **Trade card**: pay a fixed cost, receive a fixed gain, **repeatable any
  number of times in one play** as long as you can keep affording it.

**Golem/point cards** (36) — pure victory points: pay a fixed crystal cost,
receive fixed points, once, forever (this card leaves circulation the
instant someone claims it — see §9 for why this matters for identity).

**Point tokens** — bonus points for claiming a golem *quickly*: 3 points
(copper) for whoever claims from row-slot 0, 1 point (silver) for slot 1,
first-come only (each pile has `players × 2` tokens; once claimed it's gone
from that slot). Slot 1's supply slides up to slot 0 once slot 0 empties.

---

## 3. Setup, exactly

- Golem deck shuffled, 5 dealt face-up to the **point row**.
- Copper pile (`players × 2` tokens) above point-row slot 0; silver pile
  (same count) above slot 1.
- Merchant deck shuffled, 6 dealt face-up to the **merchant row**.
- Every player's starting hand: one `Create 2` (crystal card, +2 yellow) and
  one `Upgrade 2` (2-step upgrade card) — identical for everyone.
- Starting caravan, **by seat, not randomized**:

  | Seat | Yellow | Green |
  |---|---|---|
  | 0 | 3 | 0 |
  | 1 | 4 | 0 |
  | 2 | 4 | 0 |
  | 3 | 3 | 1 |
  | 4 | 3 | 1 |

  This is a real, small first-mover-disadvantage-compensation baked into
  setup — later seats start with marginally better resources. Worth knowing
  if you ever benchmark a bot's win rate by seat position; a skewed result
  might be this, not a bot weakness.
- `win_target` is fixed by player count: **6 golems** for 2–3 players, **5**
  for 4–5. Fewer players → each golem is relatively "worth more" turns, so
  the target is raised to keep game length comparable.

---

## 4. The turn cycle

**One action per turn**, always — the granularity is that fine (this is not
"play cards then buy" like a deck-builder; one single action of any of the
six kinds below *is* the whole turn). After the action resolves: caravan
limit is enforced (§6), then play passes to the next seat.

The six actions, exactly one chosen per turn:

### Play — Crystal card
Add the card's fixed gain to your caravan. Card moves from hand → played
pile. No cost, no choice beyond *which* crystal card to play.

### Play — Upgrade card
Choose up to `card.steps` crystals in your own caravan (any of them, any
combination, repeats on the same slot allowed) and bump each one color up
the chain. Every step is optional — you can play a 3-step upgrade card and
only take 1 step, or 0. Card moves to played pile regardless.

*Implementation note*: `PlayUpgrade.upgrades` is an **ordered tuple of
colors**, not slot indices — the engine just needs "how many of each color
became eligible, upgraded in this order," not which physical unit moved.
The client UI tracks it positionally (so a specific caravan swatch visibly
advances) but the wire action only carries colors.

### Play — Trade card
Pay the card's fixed cost, receive its fixed gain — and you can repeat this
**as many times in one play as you can afford**, not just once. A "2Y→1B"
card played with `times=3` costs 6 yellow for 3 turquoise, all in the one
action. This is one of the two places (besides Acquire, below) where a
single turn can move a *lot* of resource.

### Acquire — take a merchant-row card
This is the one genuinely fiddly rule. Take the card at row index `j`
(0-indexed, left to right). **Payment is positional**: you place exactly `j`
crystals, your choice of color each, one onto each of the `j` cards sitting
to its left (not into any shared pool — literally onto those specific
cards). The leftmost card (`j=0`) is always free. Any crystals *already*
sitting on the card you're taking (left there by previous acquires that
passed over it) come home with it into your caravan. After taking it, the
row slides left to fill the gap and a new card is dealt onto the far right
from the merchant deck.

Two consequences worth internalizing:
- **The merchant row is a self-funding queue.** Every non-free acquire
  *feeds* the cards behind it. A card sitting at position 4 that nobody's
  touched has accumulated up to 4 crystals (one from every acquire that has
  passed over each of those left-side positions since it arrived) — it gets
  more valuable to take the longer it's ignored, an actively-growing bounty,
  not a static list.
- **Payment choice matters strategically**, not just for affordability:
  you're choosing which color to *donate* to each card to its left, shaping
  what the *next* player finds there, including your own future turns if
  the row hasn't moved.

### Rest
No cost, no cards involved: your entire played pile returns to your hand,
face-up, ready to play again. This is the *only* way to reuse a card — the
merchant deck is one-shot, but your own already-acquired cards are
infinitely replayable via play → Rest → play → Rest. Skippable only in the
sense that a turn spent Resting is a turn spent doing nothing else; the real
decision is **timing** — Rest too early and you've wasted a turn with cards
still playable; Rest too late and you're stuck holding nothing playable for
turns in a row.

### Claim — take a golem card
Pay a point-row card's exact crystal cost (no change, no partial), take the
card. If it was sitting in row-slot 0 or 1, also take one token from that
slot's pile (copper from 0, silver from 1) if any remain. Row slides and
refills like the merchant row. If this brings your claimed-golem count to
`win_target`, the end is **flagged**, not immediate (see §7).

---

## 5. Legal-action enumeration (what the bot actually searches over)

`Game.legal_actions()` is the single hook a bot plugs into (`HANDOVER.md`
already frames it this way) — it doesn't just check "is this move legal," it
**enumerates every distinct legal move from the current state**, including:

- every affordable `PlayTrade` repeat count, 1 up to the max the caravan
  supports;
- every *distinct* upgrade sequence up to `card.steps` (order matters
  because chaining the same crystal twice is different from splitting
  across two crystals — both are enumerated, deduplicated by resulting
  sequence, not by resulting caravan);
- every *distinct multiset* of payment crystals for each affordable
  `Acquire` — `_payment_options` returns each option as a **sorted** tuple,
  so it enumerates "which colors, in what quantity" once each, not every
  permutation of which color lands on which specific left-hand card. That's
  a deliberate `legal_actions()` simplification, not a rule — see the
  payment-placement note in §12, it's a real decision `legal_actions()`
  under-represents.

This means the branching factor is **not** "6 action kinds" — it's
"6 action kinds, several of which explode combinatorially with caravan
size." `HANDOVER.md` §8.2 already flags this as a known scaling concern:
*"Acquire-payment and upgrade-sequence enumeration grows with caravan size.
Fine for correctness and small games; the AI's search may need pruning or a
compressed action representation."* Concretely: a caravan of 10 crystals
across 4 colors choosing a 5-crystal payment multiset is `C(10,5)=252`
raw combinations before dedup — not enormous, but multiplied across every
row index simultaneously being evaluated, plus every upgrade sequence, plus
every trade repeat count, the actual `legal_actions()` list for a single
turn late in a resource-rich game can run into the hundreds.

*Empirical numbers from stress-testing this session* (1200 randomly-played
full games, all player counts, real 43/36-card compendium): average game
length **~330 actions**, full range from ~150 to (uncommonly) 4000+ for a
purely-random policy that never prioritizes finishing. A single
`apply_action` call + invariant checks averaged **~14ms** in that harness
(includes the `legal_actions()` call driving the random choice) — useful as
a rough rollout-cost baseline if you're budgeting MCTS iterations.

---

## 6. Caravan limit — the one rule that ISN'T fully implemented yet

Hard cap: **10 crystals total**, enforced automatically at the end of every
turn (`_enforce_caravan_limit`). **As implemented right now, this auto-drops
the cheapest crystals** (lowest color index first) rather than letting the
player choose — `HANDOVER.md` §8.1 flags this explicitly as a simplification
owed a fix: *"The real rule lets the player choose. For the server/AI,
surface this as a sub-decision instead of auto-resolving."* `CONTRACT.md`
already reserves a `pending_decision` shape for it
(`{"kind": "caravan_discard", ...}`) that the server doesn't emit yet.

**This matters a lot for a bot.** Right now, any policy that ends a turn
over 10 crystals gets its discard chosen *for* it, deterministically
(cheapest-first) — which means a bot trained against the current engine is
implicitly trained assuming "going over 10 always burns yellow first." If
this sub-decision ever gets surfaced as a real choice, that's a **new action
type** with its own branching factor (which crystals to drop, out of
however many you're over by), and any bot logic that was leaning on the
current auto-drop behavior (e.g. deliberately overflowing on yellow because
it's "free" to lose) would need retraining, not just a wrapper.

---

## 7. End-game trigger — the timing subtlety

The instant a `Claim` brings someone's golem count to `win_target`, the
engine sets an internal flag (`_end_triggered`) — but `game_over` doesn't
flip to `True` until play **wraps back around to seat 0** (i.e., the current
round finishes). Concretely: if seat 3 (of 5) triggers the end, seats 4, 0,
1, 2 still each get their turn before the game actually ends — wait, more
precisely, the check is "has `current` become 0 again," which happens right
after seat `n-1`'s turn. So **everyone who hasn't gone yet in the current
round gets exactly one more turn**, including the triggering player's
opponents, who get a genuine last chance to claim one more golem or
otherwise improve score.

This is a real strategic knob: triggering the end on *your own* last turn of
a round denies opponents any response; triggering it on your *first* turn of
a round gives everyone else a full round to react. A bot with any lookahead
at all should treat "which turn in the round am I on when I could trigger
the end" as a first-class strategic variable, not just "claim the golem that
finishes me off as soon as affordable."

---

## 8. Scoring & the winner

Total score = golem points + token value (copper=3, silver=1, summed) +
non-yellow leftover crystals (1 each). All of it is computed fresh, never
stored (`Player.score()` is a pure function of current state) — there's no
running-total field to desync.

Ties: highest score wins outright; if still tied, **the player with the
higher seat index wins** — equivalent in practice to "whoever took the last
turn of the final round," since the round always completes in ascending
seat order ending at `n-1` before wrapping. A bot doing self-play evaluation
should be aware seat position has this tie-break asymmetry (seat `n-1` is
very slightly favored in ties), on top of the starting-resources asymmetry
in §3.

---

## 9. Card identity — a subtlety worth knowing for logging, replay, or per-card statistics

Every golem and merchant card in the compendium is **content-unique** today
(verified this session: zero duplicate cost/gain signatures across all 43
merchant + 36 golem cards) — but the engine's own card objects are frozen
dataclasses compared **by value**, not identity, so two cards that ever *did*
share stats would be indistinguishable by content alone. If your bot's
logging/analysis needs to track a *specific physical card* (e.g. "how many
times has this exact card been replayed after a Rest," which is exactly what
this session's event-log feature does — see `Game.event_log` / `Game.log`),
key by **object identity** (`id(card)`), not equality. A merchant/golem
card's compendium *position* is stable across games (same shuffle source
list); an *instance* is only stable within one game.

---

## 10. Where this implementation deviates from the physical game

Read these before assuming "the bot should model X the way the rulebook
says," because for several of these, this app made a different call:

1. **Hands are fully public**, by explicit design
   (`CONTRACT.md`: `"hand": [...] // hands are PUBLIC (design decision)"`).
   The physical game has private hands. This is the single biggest
   simplification relevant to bot design — see §11 below, it changes the
   whole information-theoretic shape of the problem.
2. **Caravan-limit discard is automatic**, not a player choice (§6).
3. **Crystal supply is unlimited** — no scarcity across players, even though
   the physical box only has 35Y/30G/20B/20M (`HANDOVER.md` §4, §8.5).
4. **`legal_actions()` fully enumerates** combinatorial options rather than
   letting a UI/agent build them incrementally — a design choice for
   simplicity/correctness, with the scaling caveat in §5.
5. First-player is always seat 0, never rotates (`CLAUDE.md`/`HANDOVER.md`
   §8.3) — not a deviation from the physical rules exactly, but a fixed
   assumption baked into `_advance_turn`'s end-of-round detection; don't
   build a "rotating first player" variant without revisiting that code.

None of these are bugs — they're documented, deliberate simplifications. But
"deliberate simplification of the reference implementation" is precisely the
kind of thing a bot built to be *optimal against this engine* needs to
target, even where it diverges from "optimal at the real board game."

---

## 11. What a bot actually knows and doesn't — the real information structure

This is the section most directly useful for choosing an algorithm family.

**Fully observable, always**: your own caravan/hand/played pile, every
opponent's caravan/hand/played pile (public hands!), both face-up rows and
what's sitting on each merchant card, every token pile count, every
player's claimed golems and score. If a bot is built on top of the `Game`
object directly (self-play, not going through the network layer), literally
everything above is a plain attribute read — no belief modeling, no
opponent-hand inference, none of the machinery a hidden-information game
(poker, most deck-builders) needs.

**Not observable, genuinely stochastic**: the **order** of the remaining
merchant deck and point deck. `CONTRACT.md` is explicit that the server
"never sends deck contents or order — counts only," which is the correct
fairness stance for human play and the correct *framing* for a bot too: even
though the engine object technically holds the full remaining deck in
memory, a bot that peeks at `game.merchant_deck`'s actual contents to plan
ahead is reading information no legitimate opponent would ever have. Treat
deck order as hidden, deck **composition** as fully known and computable
(every card that exists is in `century_cards.py`; subtract what's visible on
the two rows, in every hand, and in every played pile, and what's left is
exactly what's still in the two decks, just not yet in a known order).

**Net effect for algorithm choice**: this is a **perfect-information,
stochastic** game from a legitimate bot's point of view — much closer in
shape to backgammon or a solitaire card-optimization problem than to poker.
That's exactly why `HANDOVER.md`'s own roadmap (§9, Phase 3) lands on MCTS:
`legal_actions()` + `apply_action()` already give a clean simulate/rollout
interface, and the only randomness a rollout has to sample is "which card
comes up next," which is drawable from a known-composition, unknown-order
deck — no determinization-over-hidden-hands trick required, unlike
imperfect-information MCTS variants.

---

## 12. Feature ideas this points toward

Not a prescription — you asked for the rules writeup specifically to make
this call yourself — but here's what falls out directly of the mechanics
above, in case it's useful raw material:

- **A legal-action pruner/sampler**, given §5's combinatorial blowup —
  something between "search all of `legal_actions()`" and "uniform random
  sample," e.g. capping Acquire-payment options to a few heuristically
  chosen multisets (cheapest-color-first, most-idle-color-first) rather than
  every raw combination, especially once caravans get large.
- **A card-counting deck-composition tracker**, per §11 — since remaining
  deck composition is exactly computable, a bot that tracks "how many
  magenta-granting cards are still unseen" has a real, legitimate edge over
  one that doesn't, and it's cheap to maintain incrementally (subtract every
  card as it becomes visible).
- **Explicit Rest-timing logic** — `HANDOVER.md` §9 already flags this as
  the known weakness of the current baseline bot ("hoards and never rests").
  Given Rest is your *only* card-reuse mechanism, a bot's estimate of
  "expected value of cards currently in played pile, discounted by how many
  turns until I'd realistically get back to playing them" seems like a
  cheap, high-leverage heuristic feature even before any search layer.
- **End-of-round trigger-timing awareness** (§7) — treating "which position
  in the round would I be triggering the end from" as an explicit feature
  in the value function, not just "can I afford win_target's golem."
- **Acquire payment placement as a decision `legal_actions()` hides.**
  `apply_action` validates a payment tuple purely on affordability
  (`Counter(payment)` vs. what you hold) — it never checks that the tuple is
  sorted. `legal_actions()` only ever *offers* the sorted canonical form
  (per §5), because sortedness doesn't matter for proving something's
  affordable. But which color lands on *which specific card* absolutely
  matters strategically (it shapes what the row looks like for the next
  player, including your own future turns if it doesn't move) — so a bot
  that constructs `Acquire` actions directly, instead of only ever picking
  from `legal_actions()`'s menu, has access to a real strategic degree of
  freedom the naive enumeration throws away. Worth treating "which row card"
  and "which color goes where" as two separable decisions rather than one
  opaque combinatorial choice.
- **A ready-made ground-truth signal for supervised pretraining**: this
  session's `Game(log=True)` event log (`event_log`/`to_jsonl()`) records
  every action with before/after caravan state, cost paid, and stable
  per-copy card identity — self-play batches logged this way are already in
  a shape you could train a value/policy network on without building a
  separate data pipeline.

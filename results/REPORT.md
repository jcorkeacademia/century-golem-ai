# What matters when playing Century: Golem Edition

A bot was built to answer one question: *what actually matters in this
game?* Not to be strong — strength is only the evidence that its
opinions are worth reading.

It scores every legal move as a weighted sum of twelve named things,
plays the highest-scoring one, and had those weights tuned by
evolutionary search over self-play. The weights, plus what happens when
each is removed, are the findings below.

Evidence base: **49,300 recorded tournament games**, 221 tuning generations, 41,700 logged decisions.

Every claim cites the number behind it. Where a number is not solid, it
says so.

---

## The short version

1. **Ignore your opponent.** Measured four separate ways; all four say
   the same thing.
2. **Ending the game beats scoring well.** Take more, cheaper golems.
3. **Yellow crystals are worth far more than they look.**
4. **Build production early; convert it late.**
5. **The copper and silver bonus tokens do not change how to play.**

---

## 1. Ignore your opponent

The strongest result here, and the most surprising. Four independent
experiments, each capable of showing an effect, none of which did:

| experiment | result |
|---|---|
| Delete the opponent term from the value function entirely | 50.2% CI [47.1, 53.3] — free |
| Add five opponent-modelling features, one at a time | all rejected; best 50.1% |
| Simulate the opponent's reply before moving (1-ply lookahead) | 50.2% CI [48.8, 51.5] over 10,000 games |
| Raise the player count to 3, 4 and 5, where contention is higher | ordering unchanged at every count |

Century has no blocking, no attacks, no interaction beyond racing for
the same shared cards. A bot that spends its attention on its own engine
and never models the opposition loses nothing — and the lookahead
version cost 1.8x the computation for a coin flip.

**At the table:** watching what your opponent is collecting is, at this
level of play, wasted attention. Play your own game.

The caveat: this is measured between bots of roughly equal strength. It
does not rule out opponent-awareness mattering between strong human
players, and the effect it rules out is a *large* one — a 2% edge would
not have shown up reliably.

---

## 2. Ending the game beats scoring well

Century ends when someone claims a fixed number of golems — a **count**,
not a score. Three separate experiments converge on the consequence.

**Archetypes.** Three bots were tuned under different philosophies. The
one that chases expensive golems and ignores the count (`bigcard`) does
exactly that — it collects the most valuable golems in every single
configuration tested — and loses everywhere:

| | golems | points per golem | ended the game | win rate |
|---|---|---|---|---|
| rush | 5.74 | 11.5 | **67.4%** | **62.5%** |
| bigcard | 4.84 | **13.4** | 32.6% | 37.5% |

The `ended the game` column tracks the win rate almost perfectly, across
nine lineups at 2, 3, 4 and 5 players.

**Phase weights.** Allowed to value things differently early and late,
the bot independently learned to value production nearly twice as highly
late (4.46 against 2.30) and started closing games out — 57.4% of
endings against 42.6%. That beat the single-weight version 54.7% CI
[53.7, 55.7] over 10,000 games, with a control confirming the gain came
from the split rather than from extra tuning (that control: 50.0%).

**Contribution logs.** Across 41,700 decisions, the weight on claimed
points nearly quadruples from early game to late (0.570 to 2.236) while
every other feature stays flat.

**At the table:** a cheap golem you can take now is usually worth more
than an expensive one two turns away. Get to the finish line.

---

## 3. What each crystal is worth

Measured directly: give one bot a single extra crystal at setup, play
3,000 games against an identical bot without it, alternate which side
gets the bonus.

| crystal | win rate | 95% CI | edge over even | relative to yellow |
|---|---|---|---|---|
| Yellow | 53.9% | [52.1%, 55.7%] | +3.9 | 1.00 |
| Green | 55.0% | [53.2%, 56.8%] | +5.0 | 1.28 |
| Blue | 55.7% | [53.9%, 57.4%] | +5.7 | 1.44 |
| Magenta | 58.9% | [57.1%, 60.6%] | +8.9 | 2.26 |

**A magenta is worth about 2.3 yellows.** Not the ~11x its position on
the upgrade chain suggests, and not the infinite ratio its end-game
scoring implies (yellow scores 0, magenta scores 1).

This is the one number in the project confirmed by two unrelated
methods. Reading it off the tuned weights instead gives
1.00 / 1.36 / 1.73 / **2.29**; playing the games gives
1.00 / 1.28 / 1.44 / 2.26.

**Yellow is the headline.** It scores nothing at the end of the game, so
it was hand-priced at 0.05 points and tuning put it at 0.32 — six and a
half times higher. One extra yellow at setup is worth +3.9
percentage points of win rate on its own. It is the fuel everything
else is made from, and it is
systematically undervalued by anyone reasoning from the scoring rules.

**At the table:** do not despise yellow, and do not over-pay for magenta.
The chain is much flatter than it looks.

*Caveat:* green's score margin (+1.16) came out below yellow's (+1.42)
even though its win rate is higher. Margin includes leftover crystals
and is noisier than win rate; the win-rate ordering is the one to trust,
but the inconsistency is real and unexplained.

---

## 4. Which of the twelve features actually matter

Each feature was switched off and the crippled bot played 2,000 games
against the full one. Lower is worse.

| feature | win rate without it | cost, in points of win rate | verdict |
|---|---|---|---|
| `golem_points` | 0.3% | -49.7 | **load-bearing** |
| `playable_now` | 20.2% | -29.8 | **load-bearing** |
| `cry_y` | 30.8% | -19.2 | **load-bearing** |
| `best_target` | 33.1% | -16.8 | **load-bearing** |
| `cry_g` | 33.2% | -16.8 | **load-bearing** |
| `cry_b` | 35.2% | -14.8 | **load-bearing** |
| `throughput` | 35.9% | -14.2 | **load-bearing** |
| `cry_m` | 40.3% | -9.7 | **load-bearing** |
| `exhausted` | 42.6% | -7.4 | **load-bearing** |
| `token_race` | 47.9% | -2.1 | no measurable cost |
| `token_points` | 49.0% | -1.0 | no measurable cost |
| `dead_hand` | 51.5% | +1.5 | no measurable cost |

**Nine of twelve are load-bearing. Three are not.**

**The bonus tokens do not matter.** Neither `token_points` (the 3 and 1
points themselves) nor `token_race` (racing to reach them) has a
measurable cost. That is a statement about Century: the copper and
silver bonuses are not worth planning around.

**`dead_hand` can be deleted.** Three signals agree — its weight never
stabilised across runs (-0.39 to -5.26), it contributes 0.003 per
decision, and removing it is if anything slightly positive.

### A trap worth naming

The crystal rows run **exactly opposite** to the crystal values in
section 3. Yellow costs 19 points to remove but is worth the least per
crystal; magenta costs 10 but is worth the most.

Both are correct. Ablation cost measures **how often** a feature steers
a decision; value measures **how much each unit is worth**. Yellow is in
nearly every position (zero only 19% of the time), magenta in a quarter
of them. Reading this table as an importance ranking would invert the
crystal advice completely.

---

## 5. What drove the decisions

41,700 decisions logged over 500 games, mean absolute contribution of the move actually chosen.

| feature | early | late | change |
|---|---|---|---|
| `golem_points` | 0.570 | 2.236 | 3.9x |
| `throughput` | 0.275 | 0.403 | 1.5x |
| `best_target` | 0.116 | 0.121 | 1.0x |
| `token_points` | 0.022 | 0.116 | 5.4x |
| `playable_now` | 0.084 | 0.049 | 0.6x |
| `cry_y` | 0.037 | 0.032 | 0.9x |
| `cry_g` | 0.012 | 0.043 | 3.6x |
| `token_race` | 0.030 | 0.023 | 0.7x |
| `cry_b` | 0.023 | 0.025 | 1.1x |
| `cry_m` | 0.020 | 0.023 | 1.2x |
| `exhausted` | 0.020 | 0.012 | 0.6x |
| `dead_hand` | 0.003 | 0.003 | 1.2x |

Two features do most of the work — claimed points and production.
Everything below `best_target` is an order of magnitude smaller.

**But small contributions are not unimportant.** `playable_now`
contributes 0.084 and costs 30 points to remove — the second most
expensive feature in the set. The contribution log says what the bot
weighs on a typical turn; the ablation says what breaks without it.
They answer different questions and they disagree.

---

## 6. How strong is the bot

| | vs the rule-based bot | vs the hand-tuned bot |
|---|---|---|
| Hand-tuned weights | 91.3% | — |
| Tuned, one weight set | 97.9% | 75-78% |
| Tuned, early/late split | — | **81.8%** CI [80.0, 83.4] |

The rule-based bot beats random play 100% of the time, so the ladder is
real rather than a comparison between two weak things.

---

## 7. What to trust, and what not to

### Solid

* **Opponents do not matter** — four experiments, four different designs.
* **Ending the game beats scoring well** — three experiments.
* **Magenta is about 2.3 yellows** — two unrelated methods, 2.26 from direct play and 2.29 from the tuned weights.
* **Yellow is undervalued** — confirmed three ways: 6.3x the hand-set estimate (0.32 against 0.05, the only weight to come out *stable* across 5 runs), +3.9 percentage points measured directly, and 19 points of
  win rate to remove.
* **Production is undervalued** — every one of 5 runs put it above the hand-set 1.0, ranging 1.8 to 3.4 (mean 2.8). The *direction* is solid; the
  magnitude is not, and widened when runs four and five were added.
* **Nine of twelve features are load-bearing** — 2,000 games each.

### Not solid

* **3 of the 11 tuned feature weights never
  stabilised** across 5 independent tuning runs: `token_race`, `exhausted`, `dead_hand`.
  Their values should not be quoted. Note this is about the
  *weights*, not the features: `playable_now` has one of the least
  stable weights and the second largest ablation cost.
* **Two Step 7 verdicts are resolution limits, not conclusions.**
  `denial` fires in 2% of positions and `response_threat` in ~0%. Both
  screened at 50.1%, which is what 'almost never happens' looks like
  through a whole-game win rate — not evidence that the rare case is
  unimportant.
* **Everything is measured against bots, not people.** A finding that
  holds between two machines optimising the same twelve numbers may not
  hold between humans who bluff, misjudge and get bored.
* **The engine simplifies one rule.** Going over the ten-crystal cap
  auto-discards cheapest-first rather than letting the player choose, so
  any strategy that deliberately overflows is mis-modelled.

---

## 8. What the human got wrong

The hand-set weights were a deliberate baseline: a person's honest guess
at what matters, written in victory points so it could be argued with.
Tuning disagreed with most of it.

| | guessed | measured | |
|---|---|---|---|
| yellow crystal | 0.05 | 0.32 | **6.3x too low** |
| production | 1.00 | 2.77 | **2.8x too low** |
| a nearly-affordable golem | 0.35 | 0.66 | 1.9x too low |
| a wasted turn | -2.00 | ~0 | it barely matters |

Two features were proposed for deletion on the grounds that their
weights would not settle. One of them, `playable_now`, turned out to
cost 30 points — the second most important feature in the set. A weight
that wanders is not a feature that does nothing.

The single most robust finding in the project came from **removing**
things, not adding them. Eighteen candidate features were built and
tested; every one was rejected.

---

*Generated 2026-09-19 from the
files in `results/`. Supporting detail: `feature_log.md` (the 18
rejected features), `archetype_log.md` (the matchup matrix),
`lookahead_log.md`, `weight_stability.json`, `ablation.json`,
`crystal_value.json`, `contributions.json`.*

# Feature log (Step 7)

Screen: each candidate bolted onto `tuned_split` at four fixed contributions
(-1.0, -0.3, +0.3, +1.0 in V units at the feature's p95), played head-to-head
against the same weights without it. 2,000 games per variant, 144,000 games
total, 192 minutes. `KEEP` requires the lower confidence bound above 50%.

## Positive control

The screen adds a feature *without* rebalancing the other weights, so it could
in principle be biased against every candidate: the base already sits at an
optimum, and any new term perturbs it. Tested by stripping `playable_now` —
known from Step 6's ablation to be worth 21 points — out of the base and
screening it back in as if new:

| contribution | win rate | 95% CI |
|---|---|---|
| -1.0 | 0.0% | [0.0%, 0.2%] |
| -0.3 | 1.2% | [0.8%, 1.8%] |
| +0.3 | 63.1% **detected** | [61.0%, 65.2%] |
| +1.0 | 0.0% | [0.0%, 0.2%] |

Detected at 63.1%, so the instrument works and the rejections below are real.
Note how narrow the useful band is: +0.3 wins at 63.1%, +1.0 loses at 0.0%.

## Results

| feature | group | best | at | worst | verdict |
|---|---|---|---|---|---|
| `card_count` | engine | 51.8% | +0.3 | 30.0% | harmful |
| `upgrade_steps` | engine | 47.8% | -1.0 | 45.9% | harmful |
| `feedable_trades` | engine | 36.2% | -0.3 | 0.5% | harmful |
| `color_coverage` | engine | 43.0% | +0.3 | 34.4% | harmful |
| `free_space` | caravan | 24.0% | -0.3 | 0.4% | harmful |
| `overflow_waste` | caravan | 49.5% | -1.0 | 27.0% | harmful |
| `golem_count` | score | 50.3% | -0.3 | 27.9% | harmful |
| `race_lead` | race | 50.0% | +0.3 | 0.7% | harmful |
| `row_bounty` | row | 34.2% | -0.3 | 0.9% | harmful |
| `option_breadth` | targets | 6.5% | -0.3 | 0.1% | harmful |
| `shaped_target` | targets | 23.4% | -0.3 | 0.1% | harmful |
| `clock_lead` | race | 46.9% | +0.3 | 0.2% | harmful |
| `snipe_risk` | opponent | 40.7% | -0.3 | 1.1% | harmful |
| `contested_target` | opponent | 19.1% | -0.3 | 0.2% | harmful |
| `contested_tokens` | opponent | 10.2% | -0.3 | 0.1% | harmful |
| `denial` | opponent | 50.1% | +0.3 | 46.2% | no measurable effect |
| `response_threat` | opponent | 50.1% | -1.0 | 50.1% | no measurable effect |
| `opp_fit_bounty` | opponent | 26.4% | -0.3 | 0.4% | harmful |

**Kept: none of the 18.**

## What the failures say

**Restatements of `best_target` are actively poisonous.** `option_breadth`
(6.5%), `contested_target` (19.1%), `shaped_target` (23.4%) and
`contested_tokens` (10.2%) all recompute points-over-distance in a slightly
different shape. Adding one alongside `best_target` doubles the *promise*
term, which is the exact failure that made the first hand-set bot skip 48
legal claims and lose 120 games in a row. `contested_target` is the feature
the brief ranks first of all eighteen.

**The opponent family failed as predicted.** Step 6 measured that dropping
the opponent term entirely costs nothing (50.2%, CI [47.1, 53.3]). All five
opponent features here are harmful or undetectable. Century has no blocking
and no interaction beyond racing for shared cards, and the bot is measurably
better off ignoring its opponent and optimising its own engine.

**Two verdicts are resolution limits, not conclusions.** `denial` is zero in
98% of positions and `response_threat` in ~100%. Both screened at 50.1% —
which is what 'this feature almost never fires' looks like through a
whole-game win rate, not evidence that the rare case does not matter. To
test them properly you would need to score only the positions where they
fire, which the current harness cannot do.

## Conclusion

The twelve core features are sufficient for this game at this level of play.
Further strength has to come from somewhere other than more features —
Step 8's opponent-reply lookahead is the remaining lever in the brief.

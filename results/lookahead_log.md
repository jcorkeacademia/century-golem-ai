# Lookahead log (Step 8)

`WeightedBot(lookahead=1)`: score every move at one ply, take the best K, let
the opponent answer each, re-score the resulting position, pick the winner.
All comparisons against the identical bot at `lookahead=0`.

| variant | games | win rate | 95% CI | ms/decision |
|---|---|---|---|---|
| greedy reply, top_k=4 | 5,000 | 50.2% | [48.8, 51.5] | 1.33 (1.8x) |
| weighted reply, top_k=4 | 3,000 | 51.0% | [49.2, 52.8] | 3.42 (4.7x) |
| greedy reply, top_k=8 | 3,000 | 49.6% | [47.8, 51.4] | ~2.0 |
| *baseline* | | | | 0.73 |

**No effect, at 1.8x to 4.7x the cost.** Every interval contains 50%, and the
mean scores are identical to a decimal place (71.3 against 71.3).

## Why, and why this was predicted

Lambda is 0 — Step 6 measured the opponent term as worthless and removing it
was free. So V contains no term that reads an opponent's position. Simulating
their reply can therefore only change the evaluation through what their move
does to the *shared board*: a golem taken off the row, a merchant card
removed, crystals left sitting. Those move `best_target` and `token_race`,
which V does read, but it is a narrow channel and evidently not worth 1.8x.

The three variants rule out the obvious objections:

* **A crude reply policy?** No — a full WeightedBot reply also gives nothing.
* **Too narrow a shortlist?** No — doubling K to 8 gives nothing.

## Where this sits

Third independent measurement pointing the same way:

1. Removing the opponent term entirely: 50.2% CI [47.1, 53.3] (Step 6)
2. All five opponent-modelling features rejected (Step 7)
3. One-ply opponent lookahead: no effect (Step 8)

Century has no blocking and no direct interaction; players race for shared
cards but cannot interfere with each other. At this level of play the bot is
measurably better off spending its compute on its own engine and ignoring the
opponent completely. That is a statement about the game, not about the bot.

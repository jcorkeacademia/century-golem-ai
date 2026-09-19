# Archetype log (Step 9)

Three constrained bots, each tuned for 20 generations from the Step 6
optimum with 22 phase-split parameters. `shaped_target` replaces
`best_target` (identical at alpha=beta=1, so the swap is lossless), and
`golem_count` is pinned to define the archetype.

| archetype | constraint | intent |
|---|---|---|
| rush | beta 2.5, golem_count 1.5 | punish distance, take many cheap golems, end fast |
| bigcard | alpha 1.6, golem_count 0 | reward points superlinearly, wait for expensive golems |
| balanced | unconstrained | the Step 6 bot (`tuned_split`) |

## Strength against a fixed yardstick (2 players)

| archetype | vs greedy | vs handset_v1 |
|---|---|---|
| balanced | 97.9% | 81.8% |
| rush | 97.5% | 75.0% |
| bigcard | 92.6% | 60.8% |

All three beat the hand-set baseline, so all three are functioning bots
rather than one bot and two cripples. That is the precondition for the
matrix meaning anything.

## Matchup matrix

Win rate, with the per-player-count chance baseline in brackets. Every
seed is played once per cyclic seat rotation, so seat advantage cancels.

| players | lineup | balanced | rush | bigcard |
|---|---|---|---|---|
| 2 (chance 50%) | 2p: rush, bigcard | - | 62.5% | 37.5% |
| 2 (chance 50%) | 2p: rush, balanced | 53.1% | 46.9% | - |
| 2 (chance 50%) | 2p: bigcard, balanced | 63.4% | - | 36.6% |
| 3 (chance 33%) | 3p: rush, bigcard, balanced | 42.3% | 35.8% | 21.9% |
| 4 (chance 25%) | 4p: rush, rush, bigcard, balanced | 32.9% | 26.1% x2 | 14.9% |
| 4 (chance 25%) | 4p: bigcard, bigcard, rush, balanced | 33.2% | 31.6% | 17.6% x2 |
| 4 (chance 25%) | 4p: balanced, balanced, rush, bigcard | 30.0% x2 | 25.7% | 14.2% |
| 5 (chance 20%) | 5p: rush, rush, bigcard, bigcard, balanced | 27.8% | 22.5% x2 | 13.6% x2 |
| 5 (chance 20%) | 5p: balanced, balanced, rush, bigcard, bigcard | 26.8% x2 | 21.5% | 12.4% x2 |

`x2` means that archetype appeared twice in the lineup and the figure is
the mean of the two.

## Findings

**The ordering is transitive and never reverses: balanced > rush >
bigcard.** It holds in every pairing at 2 players, in the 3-player game,
in all three 4-player lineups and in both 5-player lineups. There is no
rock-paper-scissors in Century — no archetype counters another.

**The archetypes are behaviourally distinct, exactly as constrained.**
Across every configuration bigcard takes the most valuable golems
(13.4-13.7 points each against rush's 11.5-11.9) and the fewest of them
(3.5 against 4.2-5.7). The constraints did what they were meant to do.

**And it loses anyway, because ending the game is worth more than what
you collected.** The `ended` column tracks win rate almost perfectly: in
the 2-player rush-vs-bigcard match, rush ends 67.4% of games and wins
62.5%. Century's end condition is a *count* of golems, not a score, so a
strategy indifferent to the count is fighting the win condition. This is
the same result Step 6b found from the other direction, where the
phase-split bot learned to value production twice as highly late and
closed out 57% of its games.

**Adding players does not rescue the weaker archetypes.** The obvious
hypothesis was that rush's speed would pay off with more rivals competing
for the same row. It does not: rush is +2.5 points over chance at 3
players and roughly at chance by 5, while balanced stays clearly ahead at
every count. Bigcard gets *worse* as players are added, from 37.5% heads-
up against rush down to 10.9-14.4% at 5 players.

**Which is a fourth measurement that opponents do not matter much.**
More players means more contention for the same cards — the one condition
under which opponent-awareness should start to pay. It does not change
the ordering at all. That is consistent with the lambda ablation (free to
remove), the five rejected opponent features, and the null lookahead
result.

# What near-optimal solo plans do

Beam search (width 1000) plus plan repair on 100 seeds, against the
tuned bot's own plans on the same seeds. The calibration puts the beam
within ~0-1 turn of the proven optimum wherever a proof was possible.

## Tempo and habits

| | near-optimal | tuned bot |
|---|---|---|
| turns to win (mean) | 33.0 | 43.5 |
| turns to win (range) | 23-44 | 29-61 |
| turn of golem 1-6 (mean) | 12, 17.6, 22.7, 27.0, 30.6, 33.0 | 8.1, 15.6, 23.1, 30.0, 37.0, 43.5 |
| cards bought per game | 5.1 | 5.3 |
| ...of which before the first golem | 4.2 | 2.6 |
| turn of the last purchase | 16.4 | 21.3 |
| mean slot bought from (0 = free) | 0.92 | 0.58 |
| cards owned at the first claim | 6.2 | 4.6 |
| card plays per game | 18.1 | 23.8 |
| Rests per game | 3.8 | 8.4 |
| mean golem cost (crystals) | 4.69 | 4.75 |
| bonus tokens per game | 2.55 | 2.06 |

## Cards near-optimal plans buy, by pick rate

Bought / times the card appeared in the row across all plans; cards offered
at least 10 times. The bot's rate is alongside for comparison.

| card | near-optimal | tuned bot |
|---|---|---|
| +1B1Y | 16/17 (94%) | 16/21 (76%) |
| 1B->2G1Y | 15/20 (75%) | 13/21 (62%) |
| +1G2Y | 17/23 (74%) | 17/25 (68%) |
| +2G | 22/30 (73%) | 24/29 (83%) |
| 4Y->3B | 18/26 (69%) | 20/28 (71%) |
| +1M | 13/19 (68%) | 16/22 (73%) |
| 2G->1M2Y | 19/31 (61%) | 15/33 (45%) |
| +3Y | 15/26 (58%) | 16/28 (57%) |
| +4Y | 16/28 (57%) | 18/25 (72%) |
| +1B | 17/31 (55%) | 20/32 (62%) |
| Triple upgrade | 14/26 (54%) | 17/25 (68%) |
| 5Y->2M | 15/28 (54%) | 16/30 (53%) |
| 1B->1G4Y | 10/19 (53%) | 11/21 (52%) |
| 3Y->3G | 12/23 (52%) | 16/22 (73%) |
| 3G->1M1B1Y | 13/25 (52%) | 14/26 (54%) |
| 1G->3Y | 13/25 (52%) | 7/25 (28%) |
| 2M->2B3G | 18/35 (51%) | 21/34 (62%) |
| 3G->2M | 14/28 (50%) | 13/30 (43%) |
| 1M->2G2Y | 13/26 (50%) | 11/25 (44%) |
| 1M->1B1G1Y | 10/22 (45%) | 8/23 (35%) |
| 1M->2B | 12/27 (44%) | 9/29 (31%) |
| 3G->3B | 11/25 (44%) | 12/24 (50%) |
| 1B2Y->2M | 12/28 (43%) | 12/31 (39%) |
| 3B->3M | 11/26 (42%) | 13/28 (46%) |
| 2G->2B | 8/19 (42%) | 9/25 (36%) |
| 2Y->2G | 7/17 (41%) | 9/18 (50%) |
| 2M->3B1G1Y | 10/25 (40%) | 10/21 (48%) |
| 2B->3G2Y | 10/25 (40%) | 11/28 (39%) |
| 4Y->1M1B | 11/28 (39%) | 14/26 (54%) |
| 3Y->1M | 12/33 (36%) | 10/29 (34%) |
| 2B->2M | 9/25 (36%) | 9/25 (36%) |
| 3Y->1G1B | 10/28 (36%) | 8/26 (31%) |
| 1M->3G | 11/31 (35%) | 10/34 (29%) |
| +1G1Y | 11/32 (34%) | 16/31 (52%) |
| 1B->2G | 8/24 (33%) | 6/27 (22%) |
| 2Y->1B | 9/28 (32%) | 7/27 (26%) |
| 1M->1B3Y | 8/25 (32%) | 8/23 (35%) |
| 2B->1M2G | 9/30 (30%) | 11/27 (41%) |
| 2G->1B3Y | 7/24 (29%) | 6/24 (25%) |
| 1G1Y->1M | 6/22 (27%) | 7/23 (30%) |
| 3G->2B2Y | 5/19 (26%) | 5/18 (28%) |
| 2B->1M1G2Y | 7/29 (24%) | 7/25 (28%) |
| 4Y->2B | 7/33 (21%) | 9/33 (27%) |

## Most-played cards (near-optimal plans)

| card | plays | per game |
|---|---|---|
| Upgrade 2 | 318 | 3.2 |
| Create 2 | 196 | 2.0 |
| +2G | 91 | 0.9 |
| +1B1Y | 82 | 0.8 |
| +1G2Y | 76 | 0.8 |
| +4Y | 65 | 0.7 |
| +1B | 64 | 0.6 |
| +1M | 60 | 0.6 |
| Triple upgrade | 54 | 0.5 |
| 4Y->3B | 47 | 0.5 |
| 2M->2B3G | 42 | 0.4 |
| 2G->1M2Y | 42 | 0.4 |

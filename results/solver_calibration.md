# Calibrating the bracket on smaller goals

Same seeds, goal lowered to 2-4 golems, where the true optimum can be
proven from the opening (dfbb, 600s budget per case). `truth` is
proven where marked; otherwise it is only the best plan found.

| seed | golems | h | flow | beam | truth | proven | h gap | flow gap | beam gap |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 2 | 6 | 7 | 10 | 10 | yes | 4 | 3 | 0 |
| 0 | 3 | 9 | 9 | 17 | 17 | no | 8 | 8 | 0 |
| 1 | 2 | 6 | 7 | 12 | 12 | yes | 6 | 5 | 0 |
| 1 | 3 | 9 | 10 | 18 | 18 | no | 9 | 8 | 0 |
| 2 | 2 | 6 | 7 | 12 | 12 | yes | 6 | 5 | 0 |
| 2 | 3 | 9 | 10 | 20 | 20 | no | 11 | 10 | 0 |
| 3 | 2 | 6 | 8 | 14 | 14 | yes | 8 | 6 | 0 |
| 3 | 3 | 10 | 10 | 20 | 20 | no | 10 | 10 | 0 |
| 4 | 2 | 6 | 8 | 14 | 14 | yes | 8 | 6 | 0 |
| 4 | 3 | 9 | 10 | 18 | 18 | no | 9 | 8 | 0 |
| 5 | 2 | 6 | 7 | 12 | 12 | yes | 6 | 5 | 0 |
| 5 | 3 | 9 | 9 | 17 | 16 | yes | 7 | 7 | 1 |
| 5 | 4 | 11 | 13 | 23 | 22 | no | 11 | 9 | 1 |
| 6 | 2 | 5 | 6 | 10 | 10 | yes | 5 | 4 | 0 |
| 6 | 3 | 7 | 9 | 14 | 14 | yes | 7 | 5 | 0 |
| 6 | 4 | 10 | 12 | 19 | 19 | no | 9 | 7 | 0 |
| 7 | 2 | 6 | 7 | 13 | 13 | yes | 7 | 6 | 0 |
| 7 | 3 | 10 | 11 | 19 | 19 | no | 9 | 8 | 0 |
| 8 | 2 | 6 | 8 | 14 | 13 | yes | 7 | 5 | 1 |
| 8 | 3 | 10 | 11 | 19 | 19 | no | 9 | 8 | 0 |
| 9 | 2 | 6 | 7 | 12 | 12 | yes | 6 | 5 | 0 |
| 9 | 3 | 9 | 9 | 16 | 16 | no | 7 | 7 | 0 |

2 golems, 10 proven: mean truth - h 6.3, truth - flow 5.0, beam - truth 0.1.

3 golems, 2 proven: mean truth - h 7.0, truth - flow 6.0, beam - truth 0.5.

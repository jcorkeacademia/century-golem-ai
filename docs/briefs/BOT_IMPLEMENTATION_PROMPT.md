# Century: Golem Edition — Interpretable Bot: Implementation Brief

> **For the coding agent.** Read this whole file before writing code. Work **one step at a time**. At the end of each step, **stop**, report what you built, show test and benchmark output, and wait for approval before starting the next step.

---

## 0. Context and goal

This repo contains a working rules engine for *Century: Golem Edition* (`engine/century_engine.py`, `engine/century_cards.py`). Background docs: `docs/HANDOVER.md`, `docs/BOT_RULES_REFERENCE.md`, `docs/CONTRACT.md`, `CLAUDE.md`.

**Goal:** a bot whose decisions a human can **read and learn from**, not a black box.

- The bot scores each candidate move with a **weighted sum of named features**: V = Σ wᵢ·fᵢ. It picks the highest-scoring move.
- **CMA-ES** tunes the weights over many self-play games.
- The tuned weights, ablations, and contribution logs then answer "what matters most when playing Century."

### Non-negotiable rules
1. **The engine is the single source of truth.** Bots act only through `Game.legal_actions()` and `Game.apply_action()`, or through actions they build that `apply_action` accepts. Never duplicate or bypass rule logic in real games.
2. **No hidden-information cheating.** Bots must never read the *order* of `merchant_deck` or `point_deck`. Deck *composition* is public (full card list minus everything visible). See §3.3 for how simulations handle this.
3. **Engine edits are limited to Step 1's list.** If you find a rule bug or a mismatch with this brief, **stop and report it**. Don't silently change it.
4. **Verify before assuming.** API names in this brief come from the docs. Confirm them against the actual code (Step 0) and adapt.
5. Python 3.13, type hints everywhere, `dataclasses`, `pytest`. Dependencies: `numpy`, `cma`, `pytest` (optionally `matplotlib`).
6. Run everything from the repo root as modules, e.g. `python -m bots.arena`. No `sys.path` hacks.

---

## 1. Target layout

```
century/
  engine/
    __init__.py
    century_engine.py
    century_cards.py
  bots/
    __init__.py
    sim.py          # lightweight solitaire simulator + TTC
    features.py     # feature functions, normalization, explain()
    bots.py         # RandomBot, GreedyBot, WeightedBot
    arena.py        # match runner (paired seeds, seat rotation, parallel)
    tune.py         # CMA-ES tuning
    analyze.py      # ablations, weight stability, contribution logs, report
    weights/        # hand-set and tuned weight JSON files
    tests/
  results/          # run outputs (gitignored except summaries)
```

---

## 2. Shared definitions (used throughout)

### 2.1 Crystal levels and YE
- Levels: Y=0, G=1, B(TURQUOISE)=2, M=3. The caravan is a length-4 count list.
- **YE (yellow-equivalent) value** of a crystal = level + 1, so Y=1, G=2, B=3, M=4. Put this in one constant, `YE = (1, 2, 3, 4)`, so it can later be replaced by tuned crystal values.

### 2.2 Card output (nominal YE per play)
| Card | Output |
|---|---|
| Crystal card | Σ YE of its gain |
| Upgrade card | `steps` (each step adds +1 YE) |
| Trade card | YE(gain) − YE(cost) for one repetition (can be ≤ 0) |

### 2.3 Paying a golem: shortfall
Golem costs must be paid in **exact colors**. A crystal of level `l` can cover a cost crystal of level `c` only if `l ≤ c`, after `c − l` upgrade steps.

`shortfall(caravan, cost)`:
1. Expand the cost into a list of levels, sorted descending.
2. For each cost level `c`, assign the **highest available** crystal with level ≤ `c`, which costs `c − l` steps.
3. For each unmatched cost crystal, add `c + 1` (its full YE).
4. Return the total. 0 means claimable now.

Unit-test this with hand-made cases, including "has magenta, needs green" (the magenta can't be used).

### 2.4 Throughput
`throughput(player) = Σ nominal output of all owned cards / (number of owned cards + 1)`.
The `+1` accounts for the Rest turn in each play cycle.

### 2.5 TTC: Turns-To-Claim
`ttc(player, golem, depth=3)` estimates the turns until `player` can pay `golem.cost`, using **only that player's own** hand, played pile, and Rest. It ignores opponents, acquisitions, and deck draws. Implement it in `bots/sim.py`.

- **State:** `(caravan: tuple[4], hand: tuple[sorted card ids], played: tuple[sorted card ids])`. Card ids are stable compendium indices.
- **Moves:**
  - Play any hand card.
    - Crystal: add its gain.
    - Upgrade: enumerate distinct **resulting caravans** from up to `steps` upgrades, deduplicated.
    - Trade: try times = 1 … max affordable, deduplicated by resulting caravan.
  - Rest: move played → hand. Only allowed if played is non-empty.
- **Caravan limit:** after each simulated turn, apply the same rule as the engine (currently: drop the cheapest crystals down to 10).
- **Search:** BFS up to `depth` turns. Return the first turn index where `shortfall == 0`. Return 0 if already payable.
- **Fallback** if nothing is found within `depth`: `depth + ceil(shortfall_at_best_leaf / max(throughput, 0.5))`, where the best leaf is the reachable state with the lowest shortfall.
- **Pruning:** in the sim, skip upgrade and trade results that don't reduce shortfall or increase total YE.
- **Cache:** `functools.lru_cache` or a dict keyed by `(state, cost)`.
- **Performance target:** ≤ 1 ms average per call after caching. Report the measured number.
- Make `depth` a parameter; it will be treated as a hyperparameter later.

**Required tests:**
- Golem 2B, caravan 2G, `Upgrade 2` in hand → TTC = 1.
- Same, but `Upgrade 2` in the played pile → TTC = 2.
- Already payable → 0.
- Unreachable within depth → uses the fallback and returns > depth.

### 2.6 Game phase and weight blending
`phase = max over players of claimed golems / win_target`, clamped to [0, 1].
Effective weights: `w = (1 − phase)·w_early + phase·w_late`.
Start with `w_late = w_early` (a single set). Phase-splitting is turned on in Step 6b.

### 2.7 Value function
```
V(state_after, me) = Σ wᵢ · normᵢ(fᵢ(state_before, state_after, me))
                   − λ · Σ wᵢ · normᵢ(fᵢ(..., opp))
```
- `opp` = the opponent with the highest current score (ties → highest best-target value).
- Mark each feature as `symmetric` or `me_only`. Only symmetric features go in the λ term.
- **Terminal handling (not a feature):**
  - If `game_over`: V = ±1000 for a win/loss (+ score margin).
  - If the end is triggered and `me` has no turns left this round: V = 10 × (my score − best opponent score).
- **Normalization:** `normᵢ(x) = x / scaleᵢ`. Scales come from a calibration run (Step 3) and are stored in `bots/weights/feature_scales.json`. Weights are then comparable across features.

### 2.8 Weight file schema (`bots/weights/*.json`)
```json
{
  "name": "handset_v1",
  "features": ["golem_points", "token_points", "..."],
  "w_early": {"golem_points": 1.0, "...": 0.0},
  "w_late":  {"golem_points": 1.0, "...": 0.0},
  "lambda": 0.5,
  "params": {"ttc_depth": 3, "alpha": 1.0, "beta": 1.0},
  "meta": {"player_counts": [2], "created": "...", "source": "handset|cma run id"}
}
```

---

## 3. Feature catalog

Each feature is a function `f(before: Game, after: Game, pid: int, ctx: Ctx) -> float`, registered in a `FEATURES` dict with metadata `(group, symmetric, description)`. `ctx` holds caches: TTC per (player, golem), throughput, etc. **Compute TTC once per evaluated state and reuse it.**

**Core set (Step 3):** 1, 2, 3–6, 7, 9, 11, 16, 17, 18 (12 features, since 3–6 count as four).

| # | Key | Sym | Definition |
|---|---|---|---|
| 1 | `golem_points` | ✓ | Sum of claimed golem points |
| 2 | `token_points` | ✓ | 3·copper + 1·silver |
| 3–6 | `cry_y/g/b/m` | – | Caravan counts per color |
| 7 | `best_target` | ✓ | max over point row of `points / (1 + TTC)` |
| 8 | `option_breadth` | – | Σ over point row of `points / (1 + TTC)²` |
| 9 | `token_race` | – | Σ over slots 0–1 with a non-empty token pile of `token_value / (1 + TTC(golem in slot))`. Account for silver sliding to slot 0 when copper is empty. |
| 10 | `snipe_risk` | – | 1 if some opponent's TTC ≤ my TTC for my best target |
| 11 | `throughput` | ✓ | §2.4 |
| 12 | `upgrade_steps` | – | Σ steps over owned upgrade cards |
| 13 | `feedable_trades` | – | Σ over owned trade cards of `max(net YE, 0) × min(times affordable from current caravan, 3)` |
| 14 | `color_coverage` | – | Number of colors in {G, B, M} I can produce. Color c counts if a crystal/trade card gains c, or my largest single upgrade card has steps ≥ c. |
| 15 | `card_count` | – | Number of owned merchant cards |
| 16 | `playable_now` | – | Σ over **hand** cards of usable output now: crystal = gain YE; upgrade = min(steps, available upgrade steps in caravan); trade = net YE × affordable times (cap 3), 0 if unaffordable or net ≤ 0 |
| 17 | `exhausted` | – | Σ nominal output of the **played** pile |
| 18 | `dead_hand` | – | 1 if `playable_now == 0` |
| 19 | `row_bounty` | – | Best merchant deal left for the next player: max over row index j of `card nominal YE + YE of crystals on card − j` |
| 20 | `free_space` | – | 10 − caravan total |
| 21 | `overflow_waste` | – | YE auto-discarded by the caravan limit on this move (needs Step 1's `last_discard`) |
| 22 | `race_lead` | – | My golem count − highest opponent golem count |
| 23 | `response_threat` | – | If the end is triggered: Σ over opponents still to act this round of their best points with TTC = 0 |
| 24 | `contested_target` | – | Variant of #7: max over the row of `points × P / (1 + TTC)`. P = 1 if my TTC < every opponent's TTC; 0.5 if tied (1 if I act before them in turn order); 0.2 if an opponent is faster. |
| 25 | `denial` | – | Σ points of golems that were on the row in `before`, had some opponent with TTC ≤ 1, and are gone in `after` because I claimed them |
| 26 | `contested_tokens` | – | #9, counting only slots where my TTC ≤ every opponent's TTC |
| 27 | `opp_fit_bounty` | – | For the next player: max over row cards of (reduction in their best TTC if they owned the card + YE of crystals on it − j) |
| 28 | `golem_count` | ✓ | Number of claimed golems, separate from their points |
| 29 | `shaped_target` | – | Variant of #7/#24: `points^α × P / (1 + TTC)^β`. α and β are tunable params. |
| 30 | `clock_lead` | – | `(my score − best opponent score) / (1 + turns_to_end)`, where `turns_to_end = min over players of (win_target − golems) × max(1, mean TTC over row)` |

**`explain(game, pid, weights, top_k=3)`** prints the top-k legal moves. For each, it lists V and every feature's contribution `wᵢ·normᵢ(fᵢ)`, sorted by absolute size. Example:
```
#1 Claim(row 0)          V=+4.21
   golem_points  +2.40   token_points +1.10   best_target -0.35 ...
```

---

## 4. Steps

### Step 0 — Orientation (no code changes)
1. Read `engine/century_engine.py`, `engine/century_cards.py`, and the docs listed in §0.
2. Write `bots/API_NOTES.md` confirming the real names and shapes of:
   - `Game`, `Player`, the action classes, `legal_actions`, `apply_action`, `scores`, `winner`
   - `point_row`, `merchant_row`, `row_crystals`, `point_tokens`, `game_over`, `win_target`, `current`
   - the end-trigger flag and `event_log` (if present)
3. List any mismatches with this brief.
4. Benchmark: 100 random-play 2-player games with the real compendium. Report games/sec, mean actions per game, and mean `legal_actions()` length.

**Checkpoint.**

### Step 1 — Engine prep (only these changes)
1. **Compendium default:** `Game` uses `century_cards.MERCHANT_CARDS` / `POINT_CARDS` by default. Keep a way to pass custom decks for tests.
2. **`Game.clone()`:** a fast manual copy. Cards are immutable, so copy lists and counters, not card objects. **Don't** use `deepcopy`. Target < 1 ms. Test that mutating the clone leaves the original unchanged.
3. **`Game.shuffle_hidden(rng)`:** reshuffles the remaining merchant and point decks in place. Used only on clones (see §5.3).
4. **`last_discard`:** record the crystals removed by `_enforce_caravan_limit` on the most recent turn. Don't change the discard rule itself.
5. **`legal_actions(pruned=True)`** option. Keep the default output unchanged for the server.
   - **Acquire:** per row index, offer at most 3 payment multisets: cheapest colors first, most-surplus colors first, and a mix that keeps colors needed for my best target.
   - **Upgrade:** deduplicate by resulting caravan.
   - **Trade:** deduplicate by resulting caravan.
6. **Fast path:** a way to apply an action already known to be legal without re-enumerating `legal_actions()` (e.g. `apply_action(a, validate=False)`, used only on bot-internal clones).
7. Benchmark again and report the speedup.

**Done when:** all existing tests still pass, new tests pass, and the benchmark improves. **Checkpoint.**

### Step 2 — Solitaire simulator + TTC (`bots/sim.py`)
Implement §2.2–2.5 with their tests. Report the average TTC call time on positions from real games. **Checkpoint.**

### Step 3 — Core features (`bots/features.py`)
1. Implement the core set (§3) with the registry, `Ctx` caching, and `explain()`.
2. Write a unit test per feature on a hand-built position.
3. **Calibration:** play 200 `GreedyBot` self-play games (a temporary GreedyBot is fine). Record each feature's distribution and set `scale = max(std, 1e-6)`. Write `feature_scales.json`.

**Checkpoint.**

### Step 4 — Bots (`bots/bots.py`)
Common interface: `choose(game: Game) -> Action`, plus an optional `explain` hook.
- **RandomBot:** uniform over `legal_actions()`, seeded.
- **GreedyBot** (fixed rules, in order):
  1. Claim the highest-points affordable golem, preferring slot 0/1 on ties.
  2. Play the trade or upgrade card that most reduces shortfall to my best target.
  3. Rest if `dead_hand`.
  4. Play the crystal card with the best output.
  5. Acquire the best card among the first 2 row slots.
  6. Otherwise Rest, or take any legal move.
- **WeightedBot(weights_json, rng, lookahead=0, samples=1):**
  - For each action in `legal_actions(pruned=True)`: clone, `shuffle_hidden(rng)`, apply, evaluate V (§2.7).
  - For Acquire and Claim (which reveal a refill card), average V over `samples` reshuffles. Start with 1 and test 3.
  - Break ties with the rng.
- Hand-set starting weights in `bots/weights/handset_v1.json`, using sensible signs (golem points +1, Y small, M larger, dead_hand negative, etc.).

**Done when:** handset `WeightedBot` beats `GreedyBot` in over 60% of 2-player games (paired, seats swapped). **Checkpoint.**

### Step 5 — Arena (`bots/arena.py`)
- `run_match(bot_factories, n_players, seeds, rotate_seats=True, workers=N) -> MatchResult`.
- **Paired seeds:** every bot lineup plays the same seed list. **Seat rotation:** each seed is played with every cyclic seat rotation.
- **Turn cap:** 1000 actions. If reached, record `capped=True` and score normally.
- **Outputs per bot:**
  - win rate with a 95% Wilson interval, mean score and margin
  - win rate by seat
  - game length, golems claimed, points per golem, share of games that bot ended
- Use `multiprocessing.Pool`. Each worker builds its own bots from factories. RNG seeds must be deterministic.
- CLI: `python -m bots.arena --bots handset_v1 greedy --players 2 --games 1000 --workers 8`.
- Save JSON and a short text summary to `results/arena/<timestamp>/`.

**Done when:** two 1,000-game runs with different seed sets agree within their confidence intervals. **Checkpoint.**

### Step 6 — Tuning (`bots/tune.py`)
**6a (single weight set):**
- Parameter vector: core weights + λ. `golem_points` is fixed at 1.0 as the anchor.
- `cma.CMAEvolutionStrategy(x0=handset, sigma0=0.5, {popsize: 12, seed})`.
- **Fitness** (minimize): `−(win_rate + 0.01 · mean_margin)` over `G` games (default 200, 2 players). Each candidate plays a pool opponent, with pool opponents sampled evenly.
- **Opponent pool:** RandomBot (small share), GreedyBot, handset_v1, and a **hall of fame** holding the best weights from every 5th generation.
- **Common random numbers:** all candidates in a generation use the same seed list; the list changes between generations.
- Save every generation to `results/tune/<run_id>/gen_XXX.json` (mean, best, sigma, fitness). Support `--resume`.
- Every 10 generations: validate the current best with 1,000 fresh games vs GreedyBot and handset_v1.

**6b:** turn on `w_early`/`w_late` (doubling the parameters) and compare against 6a on the same validation seeds.

**Done when:** the tuned bot beats handset_v1 with a confidence interval that excludes 50%. **Checkpoint.**

### Step 7 — Feature expansion (ablation-gated)
Add features in this order: **#24, #25**, then 8, 10, 12–15, 19–23, 26–30. For each:
1. Add it, retune starting from the current best weights (short run).
2. Validate on fixed seeds.
3. **Keep it only if** the win rate improves by an amount outside the confidence interval, or it enables an archetype in Step 9.

Record everything in `results/feature_log.md`: feature, Δ win rate, CI, kept/dropped. **Checkpoint.**

### Step 8 — Opponent-reply lookahead
Option `WeightedBot(lookahead=1)`:
1. Score all my moves at 1-ply and take the top K (default 4).
2. For each, simulate the **next** opponent's move using a GreedyBot or WeightedBot with the current weights.
3. Re-evaluate V after their reply and pick the best.

Compare against `lookahead=0` on the same seeds. Report win rate and time per move. **Checkpoint.**

### Step 9 — Archetypes
Tune three bots with constraints:
- **Rush:** β high (≥ 2), `golem_count` weight fixed high.
- **Big-card:** α high (≥ 1.5), `golem_count` weight fixed at 0.
- **Balanced:** unconstrained.

Then:
1. Build a matchup matrix (every archetype vs every other) for 2, 3, 4, and 5 players.
2. **Optional:** MAP-Elites over a behavior grid of (points per golem, game length). Keep the best bot per cell and plot a heatmap.

**Checkpoint.**

### Step 10 — Analysis (`bots/analyze.py`)
1. **Weight stability:** 5–10 tuning runs from different seeds. Report mean ± std per normalized weight, and flag unstable weights.
2. **Ablation table:** drop each kept feature, retune briefly, report the Δ win rate.
3. **Contribution logs:** across 500 games, the mean |wᵢ·fᵢ| of the chosen move per feature, split into early and late game.
4. **Exchange rates:** implied YE value of G, B, and M relative to Y, from the crystal weights.
5. **Per player count:** weights and archetype results for 2–5 players.
6. **Report:** write `results/REPORT.md` with plain-English findings. Each claim cites its supporting number, e.g. "Magenta ≈ 3.4 yellow (±0.3)" or "Rest when hand output < X: ablation −6% win rate."

**Final checkpoint.**

---

## 5. Implementation notes and pitfalls

1. **Performance comes first.** Tuning runs millions of move evaluations. Profile (`cProfile`) after Steps 2, 4, and 6, and report hotspots. Cache TTC per state. Avoid `deepcopy`.
2. **Evaluation after the move is an opponent's turn.** Features like `row_bounty` describe what the *next player* gets. Their weights should come out negative; if they don't, investigate.
3. **Refill leakage.** Applying Acquire or Claim on a clone draws a real hidden card. Always call `shuffle_hidden(rng)` on the clone first (§Step 1.3), so the bot sees a plausible card, not the true one.
4. **Caravan discard is automatic** (cheapest first) today. If the engine later makes it a player choice, features #20–21 and the sim's limit rule must change, and weights must be retuned.
5. **Acquire payment placement.** `apply_action` accepts unsorted payment tuples, so which color lands on which card is a real choice. For now, use the pruned multisets in sorted order. A possible later extension: choose placement to minimize `opp_fit_bounty`.
6. **Seat asymmetry.** Later seats start with more crystals, and the highest seat wins ties. Always rotate seats, and report per-seat results.
7. **End timing.** The game ends when play returns to seat 0 after the trigger. Use the engine's flag. Never re-implement the trigger logic.
8. **Determinism.** Every run is reproducible from `(seed, weights file, code version)`. Log the git commit hash in the results.
9. **Tests.** Every module has tests. `pytest -q` must pass at every checkpoint.

---

## 6. Checkpoint report template
```
## Step N report
- Built: ...
- Files changed: ...
- Tests: X passed
- Benchmarks: ...
- Results: ... (with CIs)
- Issues / deviations from brief: ...
- Proposed next action: ...
```

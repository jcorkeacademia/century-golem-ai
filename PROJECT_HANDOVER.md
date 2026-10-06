# Century: Golem Edition: Project Handover

*Written 27 Sep 2026. Covers everything from the first commit (15 Sep) to today.*

This is the map of the whole project: what exists, how it was built, what was
learned, how to run it, and what is still open. It links out to the detailed
documents rather than repeating them. Every number here comes from a commit
message or a results file, and the source is named wherever it matters.

---

## Contents

1. [The project in one page](#1-the-project-in-one-page)
2. [Timeline](#2-timeline)
3. [The game platform](#3-the-game-platform): engine, cards, art, server, web client
4. [The bots](#4-the-bots-steps-010): "what matters when playing", Steps 0–10
5. [The solo solver](#5-the-solo-solver-fewest-turns-to-six-golems): the fastest possible game
6. [Guided TEST rooms](#6-guided-test-rooms-watch-the-best-path-in-the-game)
7. [Everything learned about playing Century](#7-everything-learned-about-playing-century)
8. [How to run things](#8-how-to-run-things)
9. [Repository map](#9-repository-map)
10. [Rules of the codebase](#10-rules-of-the-codebase)
11. [Known issues, gotchas and loose ends](#11-known-issues-gotchas-and-loose-ends)
12. [What to do next](#12-what-to-do-next)
13. [Document index](#13-document-index)

---

## 1. The project in one page

An online implementation of the board game *Century: Golem Edition*, built
**engine-first**: one authoritative Python rules engine that both the
multiplayer server and all the AI work sit on top of. The rules are never
implemented twice.

The project has two goals (from `HANDOVER.md`):
1. **Play online with friends.** Done.
2. **Find the most optimal way to play.** The stated priority goal, pursued through two AI tracks.

| Part | State |
|---|---|
| Rules engine and full card set (43 merchant + 36 golem cards) | Complete, verified |
| Custom card art (hockey-team photos) | Complete: 36 golems, 45 merchant cards |
| Multiplayer server (FastAPI + WebSockets) | Working: rooms, lobby, reconnect, practice mode |
| Web client (React + Vite) | Working: full board, drag-to-pay, dialogs, turn clock |
| Practice mode bots | Three difficulties: easy / medium / hard (tuned) |
| **Bot track** (Steps 0–10) | Complete. Findings in `results/REPORT.md` |
| **Solo solver** (fewest turns to 6 golems) | Complete through roadmap step 9. Step 10 (hidden deck) not started |
| **Guided TEST rooms** | Working and tested. **Not yet committed** (see §11) |

The two AI tracks ask different questions:
- **The bots** (Steps 0–10) ask *what matters when playing*, against opponents. They're interpretable: a weighted sum of twelve named features, tuned by evolutionary search.
- **The solver** asks *how fast can a single player possibly win*, on a known deck. It's a search for the shortest plan, with provable bounds.

---

## 2. Timeline

| Date | What happened |
|---|---|
| before 15 Sep | Engine, card compendium and tracer written and verified (`HANDOVER.md`). Card art pipeline built (`CARD_ART_HANDOVER.md`). Server and web client built |
| 15 Sep | Initial commit: engine, server, web client, design docs. Bot Steps 0–5: orientation, engine prep, solitaire simulator, features, first bots, arena |
| 16–17 Sep | Step 6: CMA-ES tuning; phase-split weights. Step 7: 18 candidate features screened, all rejected |
| 18 Sep | Step 8: opponent lookahead (nothing). Step 9: archetypes, 2–5 player matchups |
| 19 Sep | Step 10: ablations, contribution logs, crystal values, `REPORT.md`. Tuned bot put into practice mode |
| 20 Sep | `best_target` double-count fix (behind a `kappa` switch, default off). Kappa sweep and retune started |
| 22–24 Sep | **Solver** steps 1–7: solo mode, state key, discard as a choice, admissible bound, starting plan, branch and bound, tiny-board verification |
| 25 Sep | Solver step 8: benchmark, speed-ups, three stronger bounds, crystal-flow bound. Diagnosis of why full proofs are out of reach; beam search; the proven bracket |
| 26 Sep | Calibration on small goals; step 9 study over 500 seeds; turn-by-turn plan logs |
| 27 Sep | **Guided TEST rooms** in the real game; the full-upgrade house rule; 68 seeds re-solved |

50 commits on branch `step0-orientation` as of writing (main is `main`).

---

## 3. The game platform

### 3.1 Rules engine (`engine/`)

`century_engine.py` is the single source of truth for the rules. The key API
(full reference in `HANDOVER.md` §6):

- `Game(player_names, seed=None, log=False, merchant_deck=None, point_deck=None, discard_choice=False)`: 1 to 5 players.
- `game.legal_actions(pruned=False)` enumerates every legal move. `pruned=True` is a smaller, strategically equivalent set for bots.
- `game.apply_action(action, validate=True)` applies a move, raising `IllegalAction` if it isn't legal.
- Actions: `PlayCrystal`, `PlayUpgrade`, `PlayTrade`, `Acquire`, `Rest`, `Claim`, and `Discard` (only with `discard_choice=True`).
- `game.clone()`, `game.shuffle_hidden(rng)`, `game.scores()`, `game.winner()`, `game.win_target`, `game.end_triggered`, `game.pending_discard`.
- Win target: 6 golems for 1–3 players, 5 golems for 4–5.

Changes made to it over the project, **each additive, defaulting to the old behaviour, and verified against a byte-identical state trace**:

| When | Change | Why |
|---|---|---|
| Bot step 1 | Real compendium by default; `clone()` (63× faster than deepcopy); `shuffle_hidden`; `last_discard`; `end_triggered`; `legal_actions(pruned=)`; `apply_action(validate=)` | Bots simulating millions of games without seeing the hidden deck |
| Solver step 1 | Allow **1 player** | The solo solver |
| Solver step 3 | `discard_choice=True` makes the over-10 discard a player decision (`pending_discard` + `Discard` action) | The auto "drop cheapest first" throws away the yellow that pays for acquisitions |

`century_cards.py` holds the full card data and a validator.
`century_trace.py` prints a whole game move by move.

### 3.2 Card art (`engine/`)

Custom artwork: hockey-team faces replace the published art. There are 36 golem
PNGs and 45 merchant PNGs (the 43-card deck plus the 2 starting cards), print
PDFs, and generators (`make_cards.py`, `make_merchants.py`). `card_art.py`
maps art to engine cards **by content, not by position**, with an audit. The
source photos and generated PNGs (426 MB) are gitignored and can be
regenerated. Details are in `CARD_ART_HANDOVER.md`.

### 3.3 Server (`server/`)

FastAPI + plain WebSockets. There is one `Game` per room, and it is the only
source of truth. Clients send *intents*; the server rebuilds them into engine
actions (`actions.py`), validates them with `apply_action`, and sends each
player their own view of the state (`serialize.py`). The message contract is in
`CONTRACT.md`.

- **Rooms:** the first person to connect is the host. Others join by code until the game starts (2–5 players). A refresh reconnects to the same seat.
- **Practice mode** (`?solo=true&players=N&difficulty=`): you against bots, no lobby, and your seat is shuffled. Difficulties are in `bot_policy.py`:
  - `easy`: claim if you can, otherwise a random move
  - `medium`: GreedyBot
  - `hard`: the tuned bot

  If the bots package or its weight files are unavailable, every difficulty falls back to `easy`.
- **Guided TEST rooms:** see §6. They're handled in `guided.py`.
- **Debug endpoints:** `/debug/simulate/{room}` and `/debug/reset/{room}`.
- `engine_path.py` puts `engine/` and the repo root on `sys.path` and swaps in the real compendium.
- Card art is served from `/static/golems`, `/static/merchants` and `/static/crystals`.

### 3.4 Web client (`web/`)

React 18 + Vite, with one WebSocket per browser.

- **Layout:** a radial table with your panel at the bottom and opponents around it. It adapts to the number of opponents; zero is only possible in a TEST room.
- **Your panel** (`MePanel`): caravan, playable and played cards (reorderable by drag), golems, tokens, points, turn clock, and the Rest button (labelled **"Reset"**).
- **The centre** (`CenterBoard`): the golem row with token piles, the merchant row with crystals on the cards, and both decks.
- **Moves:**
  - *Acquire:* drag crystals from your caravan onto the cards to the left, then click the card you want.
  - *Upgrade:* click the crystals to upgrade, then Confirm. The Confirm button only enables at exactly N picks.
  - *Trade and Claim:* open centred dialogs.
- **Also:** game-over overlay, per-player detail overlay, avatars, and the session is saved in `localStorage` so a refresh reconnects.

---

## 4. The bots (Steps 0–10)

**Question:** *what actually matters in this game?* Strength was the evidence,
not the goal. The full write-up is `results/REPORT.md`, which is generated from
the results files. The original brief is `BOT_IMPLEMENTATION_PROMPT.md`.

### 4.1 How it was built

| Step | What | Key result |
|---|---|---|
| 0 | Checked the engine API against the brief | `scores()` is keyed by name, so duplicate names collide (the arena uses seat tags). 91% of rollout time was spent in `legal_actions` |
| 1 | Engine prep for search (see 3.1) | Golden trace of 12,083 states identical; pruning makes move lists 42% shorter |
| 2 | `bots/sim.py`: solitaire simulator, *turns-to-claim* (TTC) | About 0.26 ms per call |
| 3 | `bots/features.py`: 12 core features, value function, `explain()`, calibration | Every feature's typical value lands inside the target band |
| 4 | RandomBot, GreedyBot, WeightedBot | Hand-set WeightedBot beats GreedyBot 90.8%. GreedyBot needed an engine-building rule, or it never bought a card |
| 5 | `bots/arena.py`: parallel tournaments, seat rotation, Wilson intervals | Reproducible: 91.3% and 91.5% on disjoint seed sets. A per-worker bot cache bug caught |
| 6 | CMA-ES tuning (`bots/tune.py`), then phase-split early/late weights | `tuned_split` beats hand-set **81.8%** and greedy 97.9%. The split, not extra generations, earned the gain |
| 7 | 18 candidate features screened (144,000 games), with a positive control | **All rejected.** The 12 core features are sufficient |
| 8 | One-ply opponent lookahead | **Nothing**: 50.2% over 10,000 games |
| 9 | Archetypes (balanced, rush, bigcard), 2–5 players | balanced > rush > bigcard at every player count. No rock-paper-scissors |
| 10 | Ablations, contribution logs, direct crystal values, 5-run stability | Magenta is worth about **2.3 yellows** (two independent methods agree) |
| — | Tuned bot put into practice mode as "hard" | Three difficulties, failing safe |
| — | `best_target` double-count fix (`kappa`, default 0) | Skipped claims 20.9% → 5.9%, but **no win-rate gain** at current weights. A retune with kappa free is unfinished (§11) |

Evidence base: 49,300 recorded tournament games, 221 tuning generations,
41,700 logged decisions.

### 4.2 What the bots say (from `results/REPORT.md`)

1. **Ignore your opponent.** Four independent experiments found no effect: removing the opponent term, adding opponent features, lookahead, and more players.
2. **Ending the game beats scoring well.** Take more, cheaper golems. The game ends on a *count* of golems, not a score.
3. **Yellow crystals are worth far more than they look.** Measured values are Y 1.00, G 1.28, B 1.46, M 2.28, not 1/2/3/4.
4. **Build production early, convert it late.**
5. **The copper and silver bonus tokens don't change how to play.**

Caveat, recorded in memory: every bot win rate is measured against another bot
built in this project, and **you beat `hard` easily** at the table. Self-play is
a weak ruler.

---

## 5. The solo solver: fewest turns to six golems

**Question:** with one player and a known deck (a fixed seed), what is the
fewest number of turns to claim 6 golems? This is Phase 3's first step,
modelled on Churchill & Buro (2011), *Build Order Optimization in StarCraft*.
The design is the "Century Solo Solver — Design Handover" PDF, and all the code
is in `solver/`.

### 5.1 The roadmap, as built

| Step | What | Where | Result |
|---|---|---|---|
| 1 | Solo mode, fixed seed | `solo.py` | Engine allows 1 player. Multiplayer verified identical over a **15,211-state trace** |
| 2 | Hashable state fingerprint | `state.py` `key()` | Hand and played pile unordered; claimed golems by count only; cards by mechanics |
| 3 | Discard as a choice | engine `discard_choice` | Opt-in; the multiplayer default is unchanged |
| 4 | Admissible lower bound `h` | `bound.py` | See 5.2. Never exceeded the truth on 42,749 states or 98 proven optima |
| 5 | Starting plan and bound `b` | `greedy.py` | Tuned bot solo: 39.5 turns mean, against GreedyBot's 60.6 |
| 6 | Depth-first branch and bound (DFBB) | `search.py` `dfbb`, `solve` | Correct on 38 of 38 checkable positions. Written by you; `solve()` and the tests added around it |
| 7 | Tiny boards vs brute force | `tiny.py` | 60 of 60 agree. A deliberately inflated `h` is caught |
| 8 | Speed-ups, benchmark | `bench.py`, `fastclone.py`, … | See 5.3 |
| 9 | Many seeds: what good plans do | `study.py` | 500 seeds. See §7 |
| 10 | Replanning, hidden deck | — | **Not started** |

Beyond the roadmap: `improve.py` (beam search and plan repair), `flow.py`
(crystal-flow bound), `bracket.py` (proven bracket per seed), `calibrate.py`,
`chain.py` (chained sub-goals), `replay_log.py` (turn-by-turn logs),
`plans.py` (saved plans), and `guide.py` (guided rooms).

### 5.2 The lower bound `h`, and how it got stronger

`h` = claims left + the building turns still needed. It is the largest of four
bounds, each admissible (never an overestimate):

| Bound | Idea | Per-turn ceiling |
|---|---|---|
| By caravan (step 4) | Value in "yellow-equivalents" (Y1 G2 B3 M4, optionally capped); no turn can add more than a full caravan is worth | 40 |
| **By potential** | Count row crystals as yours; then acquiring only *moves* crystals, and only card plays add value. Each card's best single-play gain is computed exactly, with the 10-crystal limit applied to the output | 10 (checked tight on 1,056,859 real turns) |
| **By engine** | Also charge for buying cards and forced Rests: you start with two weak cards, buying costs a turn, and a played card needs a Rest before reuse | — |
| **Board-aware pricing** | Only golems that can actually surface count: the 5 visible, plus one per claim | — |

Opening `h` went 8 → 11 → 14 → **15–18 per seed**.

Separately, `flow.py` is a **crystal-flow bound**: an integer program over card
plays and colour balances, solved with scipy. It's tighter (**16–19** at the
opening, exact on 65 of 70 late-game proven positions), but takes about 1
second per call, so it's used only for reporting, never inside the search.

### 5.3 Speed

| Change | Effect |
|---|---|
| Seen-state table (safe) | 44% fewer states on tiny boards |
| Claims first (safe) | Shorter plans found sooner, so `b` falls sooner |
| Per-card caching in `h` and `key()` | `h` 50 → 7.6 µs; `key` 14 → 3.8 µs |
| `fast_clone` (skip a fresh RNG per clone) | 11.7 → 2.2 µs per clone |
| **Yellow/green payment rule** (your rule; heuristic) | 21 → 12 moves per state. Held on 120+ tiny boards; not proven |
| **Full-upgrade rule** (your house rule) | Upgrade cards used in full; matches the client (§6.3) |

Overall, the late-game benchmark went from 244 s to about 35–45 s.

### 5.4 Why full-game optimality is out of reach

The work grows like (moves per turn) raised to the power (`b` − `h`). With
`b` ≈ 30 and `h` ≈ 16 at the opening, and each turn of slack costing about ×4–8,
proving one seed optimal would take **10¹⁰–10¹³ states: months to centuries**.
The search can prove optima only about 8 turns from the end.

A second opinion (`solver/HANDOFF_search_performance.md`, and the diagnosis PDF
now in `solver/`) found the same, and noted that Churchill & Buro never proved
whole StarCraft games either. Their goals were known in advance and solved in
time slices. So the result is reported as a **proven bracket**.

### 5.5 The bracket (`results/solver_bracket.md`)

For each seed: a **lower** bound, the larger of `h` and the flow bound (both
admissible); and an **upper** bound, the shortest plan found by the bots, by
beam search (width 3000) plus plan repair, or by chained sub-goals, replayed to
a real win. Seeds 0–9: lower 16–19, upper 29–38, **mean gap 14 turns**.

**Calibration** (`results/solver_calibration.md`): with the goal lowered to 2 golems,
all 10 seeds could be proven. There the beam was **0.1 turns** from the true optimum on
average, while the lower bounds were 5–6 turns short. So **the gap is almost all on the
lower-bound side**. The beam's plans are near-optimal, and it's the proofs that are hard.

**Chained sub-goals** (`chain.py`, the other chat's first recommendation): every
"fewest turns to the next golem" segment is proven in seconds, but the chained
plans are 5–19 turns *worse* than the beam. Racing to each golem starves the
card engine. It's kept as a tool, never used as the answer.

### 5.6 Plans and logs

- 500 seeds (0–499) have a saved best plan in `results/solver_study.json`, and seeds 0–9 also in `results/solver_bracket.json`. All of them follow the full-upgrade rule.
- `python -m solver.replay_log 15` writes `results/solver_logs/seed_015.md`: an at-a-glance move list, then every turn's full position (merchant row with crystals on it, golems, tokens, next draws, caravan, hand, played pile) and the move in plain words.
- **Fastest deals:** seeds 15, 35 and 320 at **24 turns**. **Slowest:** 44 turns. **Mean:** 33.1.

---

## 6. Guided TEST rooms: watch the best path in the game

### 6.1 Using it

Join through the normal **Join** form (not "Practice solo") with room code
**`TEST`** for seed 0, or **`TEST42`** for seed 42.

- A solo game on that deal starts immediately.
- The next move of the best plan is **outlined in pulsing red**: the hand card, merchant card, golem, or the Reset (Rest) button.
- A banner at the top reads, for example, *"Guided · seed 15 · Turn 7 of 24"*, with the move spelled out. For purchases it says which crystal to drag onto which card.
- When a move overflows the caravan, the plan's own discard is applied automatically and noted, because the client has no discard prompt.
- **Leaving the path:** the banner turns amber (*recalculating*), and a new plan from your actual position arrives a few seconds later (beam width 100). Re-planned paths are good, but not the saved best.
- A refresh reconnects to the same game. Joining again after the game ends starts a fresh one. Two people typing `TEST` each get their own game.

### 6.2 How it works

- `server/guided.py` attaches `state["guide"]` to every state it sends, and only in TEST rooms. `serialize.py` is untouched.
- `main.ws_room` routes TEST codes there first, and only for rooms joined by code, so practice mode is never affected.
- Guided rooms live in their own table, keyed by code *and* name.
- **Re-plans run in a separate process.** The solver temporarily swaps `bots.features.terminal_value` for a solo version. Doing that inside the server could affect a practice-mode bot moving at the same moment.
- `solver/guide.py` decides whether you're still on the plan by **comparing whole positions**, not clicks. Two different upgrade orders reaching the same caravan both count as following it.
- **Client:** `Board.jsx`, `MePanel.jsx` and `CenterBoard.jsx` take an optional `guideAction` prop that normal games never pass. There's a new `GuideBanner.jsx`, plus `guide-*` and `layout-opp-0` styles.
- **Verified live over a real websocket:** following every hint on seed 0 won in exactly the planned turns, and deviating on seed 7 re-planned and won. An ordinary code still gets a lobby with no guide field, and practice mode with the code TEST stays practice. **Not yet seen in a browser.**

### 6.3 The full-upgrade house rule

The engine and `HANDOVER.md` say an Upgrade card does "up to N" steps. The
client only confirms exactly N, and you confirmed that's the rule you play by.
So `search.uses_every_step` / `playable_moves` make the solver never propose a
partial upgrade, and saved plans that broke the rule were rejected and
re-solved (68 study seeds and 2 bracket seeds). The mean was unchanged at 33.1;
seed 15 went from 23 to 24 turns. **The engine was deliberately left as it is.**

---

## 7. Everything learned about playing Century

**From the bots** (vs opponents, `results/REPORT.md`): ignore your opponent;
ending the game beats scoring well; yellow is worth far more than it looks;
build production early and convert late; tokens don't change how to play.

**From the solver** (solo, near-optimal plans over 500 seeds, `results/solver_study.md`):

| | Near-optimal | Tuned bot |
|---|---|---|
| Turns to win | **33.1 ± 0.3** (range 24–44) | 43.3 (excluding one runaway game) |
| First golem | turn **12.0** | turn 7.9 |
| Cards bought before the first golem | **4.1** | 2.7 |
| Last purchase | turn **15.0** | turn 19.4 |
| Slot bought from (0 = free) | **0.94** | 0.54 |
| Card plays / Rests per game | **18.1 / 4.0** | 24.9 / 8.6 |

- **Build first, then claim fast.** Near-optimal play claims its first golem later, then one every 4–5 turns against the bot's 7. They're level by golem 3.
- **Same cards, different timing.** Both buy about 5 cards, and with ranges drawn over 500 seeds **no card is picked at a genuinely different rate**. The advantage is timing and economy, not card choice.
- **Crystal makers get picked most:** `+1B1Y`, `+2G`, `+1M`, `+1G2Y` at 66–78% when offered. The starting cards are the most-played cards in every plan.
- **Partial upgrades barely matter.** Forbidding them cost nothing on average.
- **The deal matters a lot:** the same near-optimal play takes 24 to 44 turns depending on the seed.

---

## 8. How to run things

All commands run from the repo root unless noted. Python 3.13.

```bash
# The game
cd server && python -m uvicorn main:app --port 8000     # server (pip install -r server/requirements.txt)
cd web && npm install && npm run dev                    # client; SERVER_URL is in web/src/config.js

# Tests (bots/tests and solver/tests)
python -m pytest -m "not slow"                          # ~690 tests, ~2 min
python -m pytest -m slow                                # thorough tiny boards and slow bot runs

# Bots
python -m bots.arena --bots tuned_split greedy --players 2 --games 1000 --workers 8
python -m bots.tune --generations 50 --games 200 --workers 18
python -m bots.make_report                              # regenerates results/REPORT.md

# Solver
python -m solver.solo                                   # show a solo board
python -m solver.search 0                               # DFBB on seed 0 for 60 s
python -m solver.bench baseline seen+claims             # benchmark configurations
python -m solver.tiny 20                                # tiny boards vs brute force
python -m solver.improve 10                             # beam and repair gap table
python -m solver.bracket 10 3000                        # proven bracket -> results/solver_bracket.md
python -m solver.calibrate 10 600                       # small-goal calibration
python -m solver.study 100 1000 16 [first seed]         # step-9 study (merges into existing)
python -m solver.replay_log 15 [more seeds]             # turn-by-turn log of a seed's best plan
```

**Resources:** the machine has 20 cores and about 16 GB of RAM. Beam width 1000
runs fine on 16–18 workers. **Width 3000 plus the flow bound ran out of memory
at 18 workers**; use at most 10 workers, with width 3000 on 2.

---

## 9. Repository map

```
engine/     rules engine, card data, tracer, card-art generators and mapping
server/     FastAPI server: main.py (rooms, lobby, practice), guided.py (TEST rooms),
            serialize.py, actions.py, bot_policy.py, engine_path.py, rooms.py
web/        React client: App.jsx, useGame.js, connection.js, components/*
bots/       interpretable bot track: sim, features, bots, arena, tune, screen,
            calibrate, make_report, weights/*.json, tests/
solver/     solo solver: solo, state, bound, flow, greedy, search, fastclone, tiny,
            bench, improve, bracket, calibrate, chain, study, replay_log, plans,
            guide, tests/, HANDOFF_search_performance.md, diagnosis PDF
results/    REPORT.md and its JSON (bots); arena/ tune/ screen/ runs;
            solver_bracket, solver_calibration, solver_study (.md + .json);
            solver_logs/ (generated, untracked)
mockups/    UI mockups
*.md        HANDOVER (engine), CONTRACT (wire format), CLAUDE (working rules),
            CARD_ART_HANDOVER, BOT_IMPLEMENTATION_PROMPT, BOT_RULES_REFERENCE,
            PROJECT_HANDOVER (this file)
```

---

## 10. Rules of the codebase

- **The engine is authoritative.** Every move goes through `apply_action`. There's no second rules implementation, not even a partial one for predicting a move's effect (`CLAUDE.md`).
- **Never trust the client.** The server rebuilds and validates every action and gates by turn.
- **Engine changes must be additive** and default to the old behaviour. Verify them with a before/after state trace: run the committed and changed engine side by side over dozens of random 2–5 player games, hash every field every turn, and require identical hashes.
- **The solver doesn't touch the multiplayer game.** The one approved exception is guided TEST rooms, and it's gated so that nothing runs for any other room.
- **Every speed-up is labelled** safe (the optimum survives) or heuristic (faster, might lose it), and checked against the tiny-board brute force and the benchmark.
- **Results that back a claim are tracked** as small files at the top of `results/`. `.gitignore` excludes subfolders apart from named patterns.
- Commits are small and titled by step, with the evidence in the message.

---

## 11. Known issues, gotchas and loose ends

**Uncommitted right now:**
- **Guided TEST rooms and the full-upgrade rule:**
  - new files: `server/guided.py`, `solver/guide.py`, `solver/plans.py`, `web/src/components/GuideBanner.jsx`
  - edits in `server/main.py`, `Board.jsx`, `MePanel.jsx`, `CenterBoard.jsx`, `styles.css`, `solver/*.py`
  - the re-solved `results/solver_study.*` and `results/solver_bracket.*`
- **Your own in-progress edits**, which are separate and should be committed (or not) by you:
  - `server/main.py`: tunnel robustness (`_push_state`, taking over half-open sockets, guarded lobby sends)
  - `web/src/config.js`: points at a Cloudflare tunnel
  - `StartScreen.jsx`: practice mode no longer needs a name or avatar
  - `engine/cards.csv`: a photo swap for golem 13
  - `web/package.json`: adds Playwright
- `results/tune/kappa000/` and `kappa030/` (untracked), plus the kappa sweep logs: see below.

**Rule mismatches:**
- **Upgrade cards:** the engine allows "up to N" steps, while the client and the house rule require exactly N. The solver follows the house rule. Consequence: with `Upgrade 2` and only one upgradable crystal left, the client can never confirm, so the card is unplayable there.
- **Discards:** the engine supports the choice, but the client has no discard prompt. Normal games use the old automatic cheapest-first drop; guided rooms resolve it server-side.

**Open threads:**
- **Kappa retune (bots):** the `best_target` fix is in (off by default). The κ=0.30 retune finished 25 generations (about 79.5% vs hand-set at generation 19). The κ=0 control run **crashed partway** (broken pipe). The head-to-head that would decide whether the fix helps was never run.
- **Seed 340 bot stall:** every bot (including practice mode's "hard") took 607 turns solo, making and discarding crystals about 390 times. It's a real pathology in solo play and hasn't been investigated.
- **The yellow/green payment rule** is evidence-backed but unproven. Plans use it, so a plan paying with blue is never considered.
- **Owed by a human** (`HANDOVER.md` §8): spot-check the four-colour golem costs (#10, #11, #20, #23, #36), and confirm merchant card #14 (`2G → 1M, 2Y`).

**Gotchas:**
- `century_cards.py` and `century_trace.py` import `century_engine` by filename. Keep the three engine files together with their names.
- `player.caravan` is **counts** `[Y, G, B, M]`, not a list of crystals. Blue is `Crystal.TURQUOISE`.
- Solver `key()` and `h` drop things that only matter for points (tokens, which golems were claimed). They are valid **only** for the solo fewest-turns question; `assert_goal_is_turns` guards this.
- Deck position in `key()` assumes nobody called `shuffle_hidden`. A determinized search (step 10) must key on deck contents instead.
- Tests that monkeypatch `bound.value` must also patch `g_play` and `engine_turns`, or cached per-card tables get built from the fake values.
- The engine's own starting cards are named `"Create 2"` / `"Upgrade 2"`; `century_cards` calls them `"Create 2 (+2Y)"` / `"Double upgrade"`. Match cards by mechanics (`card_id`), not name.
- **Playwright is now installed in `web/`**, so the client can be screenshot headlessly through Node. Nobody has done that yet for the guided mode.

---

## 12. What to do next

In rough priority order:

1. **Try the guided mode in a browser** (`TEST15` is the fastest deal), then commit it. Stage only the guided-mode changes, not your own in-progress edits.
2. **Solver step 10, the hidden deck.** Replan each turn using only visible cards, then determinization over sampled deck orders. Compare against the step-9 known-deck baseline (33.1 turns). This is what connects the solver to an AI that actually plays well.
3. **Finish the kappa experiment:** rerun the κ=0 control and play it head to head against the κ=0.30 run.
4. **A discard prompt in the client**, so normal games can use `discard_choice` too. `CONTRACT.md` already reserves `pending_decision` for it.
5. **The lower bound** (research): the one route to proving full-game optima. It has to capture why real turns add about 3–5 value when the bound allows 10.
6. Investigate the **seed 340** bot stall.

---

## 13. Document index

| Document | What's in it |
|---|---|
| `PROJECT_HANDOVER.md` | This overview |
| `HANDOVER.md` | Engine design, rules as implemented, API, open TODOs |
| `CONTRACT.md` | Client/server message contract, including practice mode |
| `CLAUDE.md` | Working rules for AI assistants on this repo |
| `CARD_ART_HANDOVER.md` | Card art pipeline and art↔card mapping |
| `BOT_IMPLEMENTATION_PROMPT.md`, `BOT_RULES_REFERENCE.md` | The bot track's brief and rules reference |
| `bots/API_NOTES.md` | Engine-API findings from bot Step 0 |
| `results/REPORT.md` | What the bots learned, with every number sourced |
| `results/solver_bracket.md` | Proven lower and upper bounds per seed |
| `results/solver_calibration.md` | Where the gap lies, measured on small goals |
| `results/solver_study.md` | What near-optimal solo plans do (500 seeds) |
| `solver/HANDOFF_search_performance.md` | Why DFBB stalls on Century: the question put to a second opinion |
| `solver/Why DFBB Stalls on Century — Diagnosis and Plan.pdf` | That second opinion's answer |
| "Century Solo Solver — Design Handover" (PDF, outside the repo) | The solver's original design and roadmap |

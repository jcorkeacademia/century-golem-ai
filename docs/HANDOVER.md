# Century: Golem Edition — Project Handover

**Project:** An online, multiplayer implementation of *Century: Golem Edition*, plus a solver to find optimal play.
**Status:** Rules engine complete and verified. Full card set transcribed. Ready for AI + multiplayer layers.
**Language/stack:** Python 3.13 (engine); web front-end + server TBD.

---

## 1. Goals

1. **Play online with friends** — invite people to a game on your own platform.
2. **Find the most optimal way to play** — a solver/AI that self-plays to surface the best strategies. *(This is the priority goal.)*

The whole project is built engine-first: one authoritative rules engine that both the multiplayer server and the AI sit on top of. This avoids two divergent rule implementations.

---

## 2. Current status

| Component | File | Status |
|---|---|---|
| Rules engine (game logic) | `century_engine.py` | ✅ Complete, verified end-to-end |
| Card compendium (all cards) | `century_cards.py` | ✅ 43 merchant + 36 golem transcribed & validated |
| Step-by-step tracer | `century_trace.py` | ✅ Working; prints full state per action |
| Optimal-play AI | — | ⬜ Not started (next major phase) |
| Multiplayer server + UI | — | ⬜ Not started |

A full 2-player game has been played through the engine start-to-finish (game-end trigger, round completion, token bonuses, and scoring all fire correctly).

---

## 3. File overview & how to run

All three files **must live in the same folder** — the tracer and compendium `import` the engine by filename.

> ⚠️ **Filename gotcha:** the code imports `century_engine`. If you rename `century_engine.py` to `engine.py`, the import breaks (`ModuleNotFoundError`). Either keep the `century_` names, or update the `from century_engine import ...` line at the top of `century_trace.py` and `century_cards.py`.

| File | What it is | Run it? |
|---|---|---|
| `century_engine.py` | The rules library. Everything imports this. | Optional — running it plays a tiny random self-test and prints final scores only. |
| `century_trace.py` | Plays a game and prints full board + player state after every action. Your "watch it play" tool. | **`python3 century_trace.py`** |
| `century_cards.py` | Data only: the full card lists + a validator + a crystal-frequency report. | `python3 century_cards.py` to validate transcriptions. |

**To play a traced game with the real cards** (the tracer currently uses the engine's tiny sample deck), either add these two lines to the top of `century_trace.py`, or run:

```python
import century_engine as E, century_cards as C
E.MERCHANT_DECK = C.MERCHANT_CARDS
E.POINT_DECK    = C.POINT_CARDS
import century_trace as TR
TR.run(names=("Alice", "Bob"), seed=11)
```

*(A clean next task is to make `century_trace.py` auto-load the compendium so `python3 century_trace.py` just uses the real cards.)*

---

## 4. Physical component inventory

For reference and for enforcing scarcity if you ever choose to (see §8, note 5).

**Crystals** (upgrade chain: Yellow → Green → Blue → Magenta)

| Color | Engine name | Physical count |
|---|---|---|
| Yellow (Y) | `Crystal.YELLOW` (0) | 35 |
| Green (G) | `Crystal.GREEN` (1) | 30 |
| Blue (B) | `Crystal.TURQUOISE` (2) | 20 |
| Magenta (M) | `Crystal.MAGENTA` (3) | 20 |

> **Naming note:** the physical "Blue" crystal is called **TURQUOISE** in the engine. Anywhere you see `TURQUOISE` in code, that's the blue crystal.

**Tokens**

| Token | Value | Physical count |
|---|---|---|
| Copper (bronze) | 3 points | 10 |
| Silver | 1 point | 10 |

At setup, copper tokens = (players × 2) sit above the leftmost point card, silver = (players × 2) above the second. With 5 players that's 10 each — the whole supply. The engine models this correctly.

**Cards**

- 43 merchant cards (in the deck) + 2 starting cards per player (`+2Y` "Create 2", double-upgrade "Upgrade 2").
- 36 golem/point cards.

---

## 5. Rules, as implemented

The engine is authoritative: every move goes through `apply_action`, which **rejects illegal moves**. The multiplayer server must never trust a client — it should reconstruct the action object and call `apply_action`.

**Crystals.** Four colors ordered by the upgrade chain Y→G→B→M. "Upgrade" moves one crystal one step up; Magenta can't upgrade. End-game value: each non-yellow crystal = 1 point; yellow = 0.

**Setup.** Shuffle golem deck, deal 5 to the point row. Copper tokens (players×2) above slot 0, silver above slot 1. Shuffle merchant deck, deal 6 to the merchant row (each row card can accumulate crystals). Every player starts with `Create 2` + `Upgrade 2` in hand, plus starting crystals by seat: P1 3Y · P2 4Y · P3 4Y · P4 3Y+1G · P5 3Y+1G.

**A turn = exactly one action**, then the caravan-limit check, then pass clockwise.

- **Play — Crystal card:** add its crystal bundle to your caravan. Card → your "played" pile.
- **Play — Upgrade card:** perform up to *N* single upgrade steps, each optional, each on a color you choose; chaining the same crystal twice is allowed. Card → played.
- **Play — Trade card:** pay cost → gain, repeatable any number of times while affordable. Card → played.
- **Acquire:** take merchant card at row index *j*; place exactly *j* crystals (your color choice) one on each card to its left (leftmost, j=0, is free). Any crystals already sitting on the taken card go to your caravan. Row slides left, refills from deck.
- **Rest:** move your whole played pile back to your hand.
- **Claim:** pay a golem card's exact crystal cost, take it. If it was in slot 0 or 1, take one token from that slot's pile; when the copper pile empties, silver slides up to slot 0. Row slides left, refills.

**Caravan limit:** max 10 crystals, enforced at end of each turn.

**Game end:** when a player claims their **6th** golem card (2–3 players) or **5th** (4–5 players), the end is flagged; the game actually ends after the current round completes (play returns to the first player). Then score.

**Scoring:** golem-card points + copper (3 each) + silver (1 each) + non-yellow crystals (1 each). Most points wins; ties break to the last player who took a turn.

---

## 6. Engine API reference

**Enums / cards**
- `Crystal` — `YELLOW=0, GREEN=1, TURQUOISE=2, MAGENTA=3`; `.can_upgrade` property.
- `CrystalCard(gain, name)`, `UpgradeCard(steps, name)`, `TradeCard(cost, gain, name)` — `cost`/`gain` are tuples of `(Crystal, count)`.
- `PointCard(cost, points, name)`.
- `Token` — `COPPER=3, SILVER=1`.

**Actions** (immutable descriptors passed to `apply_action`)
- `PlayCrystal(hand_index)`
- `PlayUpgrade(hand_index, upgrades)` — `upgrades` is a tuple of the colors you upgrade, in order (len ≤ card.steps).
- `PlayTrade(hand_index, times)` — number of repetitions (≥1).
- `Acquire(row_index, payment)` — `payment` is a tuple of one `Crystal` per card to the left; len == `row_index`.
- `Rest()`
- `Claim(row_index)`

**`Game`**
- `Game(player_names: list[str], seed=None)` — 2–5 players.
- `.legal_actions() -> list[Action]` — enumerates every legal move (incl. upgrade sequences, trade repetitions, acquire payment options). **This is the hook the AI plugs into.**
- `.apply_action(action)` — validates & applies; raises `IllegalAction` if illegal.
- `.scores() -> dict[name, int]`, `.winner() -> name | None`.
- State you can read: `.player` (current), `.players`, `.current`, `.game_over`, `.win_target`, `.point_row`, `.merchant_row`, `.row_crystals`, `.point_tokens`, `.point_deck`, `.merchant_deck`.

**`Player`**
- `.caravan` — `list[int]` length 4, indexed by `Crystal`.
- `.hand`, `.played`, `.point_cards`, `.tokens`.
- `.total_crystals()`, `.has(counter)`, `.add/.remove`, `.score()`.

**Data (in `century_cards.py`)**
- `MERCHANT_CARDS` (43), `POINT_CARDS` (36), `STARTING_CARDS` (2).
- `validate()` — prints counts vs expected + sanity checks.
- `crystal_frequency()` — how often each color appears across costs/gains/golem costs.

---

## 7. Design intelligence (for the AI phase)

From `crystal_frequency()` across the full deck:

- **Golem costs** are evenly heavy on G / B / M (46 each) and lighter on Y (37).
- **Merchant gains** skew toward Y / G, while high-value crystals (B, M) mostly come from **trading up** the chain.

This green→blue→magenta pressure is the core economic tension. An optimal agent must convert cheap yellow into expensive magenta efficiently (via upgrade and trade cards) while timing golem claims and token bonuses. Note the physical crystal caps (M and B only 20 each) if you later model scarcity — magenta can genuinely run tight.

---

## 8. Known simplifications & open TODOs

These are deliberate calls flagged for follow-up — read before extending.

1. **Caravan-limit discard is automated.** `_enforce_caravan_limit` auto-drops the *cheapest* crystals when over 10. The real rule lets the player choose. For the server/AI, surface this as a sub-decision instead of auto-resolving.
2. **`legal_actions()` can be combinatorially large.** Acquire-payment and upgrade-sequence enumeration grows with caravan size. Fine for correctness and small games; the AI's search may need pruning or a compressed action representation.
3. **End-of-round timing assumes player 0 starts each round.** True here (first player is index 0). If you ever change first-player handling, revisit `_advance_turn`.
4. **Card duplicates unconfirmed.** The engine treats all 43 merchant and 36 golem cards as distinct singles. Confirm the physical deck has no duplicated cards; if it does, add copies to the lists.
5. **Crystal supply is unlimited in the engine** (matches the rulebook: substitute if exhausted). Physical caps (Y35/G30/B20/M20) are documented but **not enforced**. Only add enforcement if you want scarcity as a design variant.
6. **Compendium not auto-loaded.** The tracer still defaults to the engine's tiny sample deck; plug in the compendium (see §3).

**Verification still owed by the human:**
- Spot-check the four-color golem costs (#10, #11, #20, #23, #36) — easiest place for a transcription miscount.
- Confirm merchant card **#14**: source text read `2G → 1M. 2Y`; transcribed as `2G → 1M, 2Y` (pay 2 green → get 1 magenta + 2 yellow).

---

## 9. Roadmap

**Phase 1 — Rules engine.** ✅ Done.

**Phase 2 — Verification.** Play traced games; hot-seat a real game against the physical rules; resolve the two open card questions above. A scripted/interactive mode (feed exact moves to test specific rules) is a small, useful add here.

**Phase 3 — Optimal-play AI (priority goal).**
- Start with a **heuristic bot** (value crystals by position in the upgrade chain; prioritize efficient golem claims and the copper/silver bonuses; learn to Rest at the right time — the current test bot hoards and never rests).
- Move to **search-based self-play**. MCTS fits this engine-building/economy game well, since `legal_actions()` + `apply_action` already give a clean simulate-and-rollout interface.
- Run large batches of self-play; log statistics to answer "what's the strongest opening and buying strategy."

**Phase 4 — Online multiplayer.**
- **Authoritative server** holds the one true `Game` state and validates every move via `apply_action`. Never trust the client.
- **Lobby/rooms** so you can invite friends; **WebSockets** for real-time turn sync.
- **Front-end UI:** point row, merchant row (with crystals on cards), your caravan, hand vs played pile, legal-action hints.
- **Persistence** so games survive disconnects; reconnect restores state.
- Surface the sub-decisions the engine exposes (caravan discard, acquire payment colors, upgrade choices) as UI prompts.

---

## 10. Quick-start for whoever picks this up

```bash
# 1. Put the three files in one folder.
# 2. Validate the card data:
python3 century_cards.py            # expect 43 merchant, 36 golem, CHECKS: OK

# 3. Watch a game play out:
python3 century_trace.py            # step-by-step trace (sample deck)

# 4. To trace with the real cards, see §3 (two-line plug-in).
```

Then read `century_engine.py` top-to-bottom — it's ~350 lines, heavily commented, and is the source of truth for every rule.

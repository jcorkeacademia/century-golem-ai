# CLAUDE.md — Century: Golem Edition (online multiplayer)

> Context file for Claude Code (the AI coding assistant used to build this
> project). Its status notes date from August 2026; for the current state see
> `README.md` and `docs/PROJECT_HANDOVER.md`.

Standing context for Claude Code. Read this before doing anything. `docs/HANDOVER.md`
is the authoritative design doc — consult it for rule details.

---

## What this project is

An online, multiplayer implementation of the board game *Century: Golem Edition*,
plus (later) a solver/AI for optimal play. Built **engine-first**: one authoritative
Python rules engine that both the multiplayer server and any future AI sit on top of.
Never fork the rules into a second implementation.

Two goals, in priority order:
1. **Optimal-play AI** (the long-term priority goal — not started yet).
2. **Online multiplayer** with friends (the current focus of this repo).

We are currently building **#2**.

---

## Stack

- **Engine:** Python 3.13 (already complete and verified — see `engine/`).
- **Server:** Python + FastAPI + **plain WebSockets** (no Socket.IO).
- **Front-end:** **React + Vite** (JavaScript). Plain WebSocket client, no Socket.IO.

---

## Folder layout

```
century/
  engine/     century_engine.py, century_cards.py, century_trace.py  (DONE, do not rewrite)
  server/     FastAPI + WebSocket server  (to build)
  web/        React + Vite front-end  (to build)
  docs/HANDOVER.md authoritative design doc
  CLAUDE.md   this file
```

---

## Non-negotiable rules (read before writing server code)

1. **The engine is authoritative.** Every move goes through `Game.apply_action(action)`,
   which validates and raises `IllegalAction` on anything illegal.
2. **Never trust the client.** The server reconstructs the action object from the
   client message and calls `apply_action` itself. The client never mutates game state;
   it sends an *intent*, the server validates and broadcasts the new state.
3. **Turn-gate every action.** Reject any action from a player who is not `game.current`.
4. **One `Game` instance per room**, held server-side, is the single source of truth.

---

## Engine gotchas (these have bitten before)

- **Filename imports.** `century_trace.py` and `century_cards.py` do
  `from century_engine import ...`. The three files must stay together and keep their
  `century_` names, or imports break with `ModuleNotFoundError`.
- **`player.caravan` is COUNTS, not a list of crystals.** It's a `list[int]` of length 4
  indexed by `Crystal` (0=YELLOW, 1=GREEN, 2=TURQUOISE, 3=MAGENTA). `[2,2,2,1]` means
  2 yellow, 2 green, 2 blue, 1 magenta. Expand to individual swatches in the UI yourself.
- **"Blue" is `TURQUOISE` in code.** The physical blue crystal is named `Crystal.TURQUOISE`.
- **"Golem points" and "total score" are both DERIVED, not stored fields.**
  Golem points = `sum(pc.points for pc in player.point_cards)`.
  Total score = `player.score()` (golem points + tokens + non-yellow crystals). They differ.
- **Crystal upgrade chain:** Yellow → Green → Turquoise(Blue) → Magenta. Magenta can't upgrade.
  Yellow is worth 0 at end-game; every non-yellow crystal is worth 1 point.

---

## Engine API (the surface the server/UI uses)

- `Game(player_names: list[str], seed=None)` — 2–5 players.
- `game.legal_actions() -> list[Action]` — enumerates every legal move (incl. upgrade
  sequences, trade repetitions, acquire-payment options). Use to validate/gray-out — NOT
  as a flat button list; it can be combinatorially large.
- `game.apply_action(action)` — validates & applies; raises `IllegalAction` if illegal.
- `game.scores() -> dict[name,int]`, `game.winner() -> name | None`.
- Readable state: `game.current`, `game.players`, `game.game_over`, `game.win_target`,
  `game.point_row`, `game.merchant_row`, `game.row_crystals`, `game.point_tokens`,
  `game.point_deck`, `game.merchant_deck`.
- Actions: `PlayCrystal(hand_index)`, `PlayUpgrade(hand_index, upgrades)`,
  `PlayTrade(hand_index, times)`, `Acquire(row_index, payment)`, `Rest()`, `Claim(row_index)`.
- `Player`: `.caravan`, `.hand`, `.played`, `.point_cards`, `.tokens`,
  `.total_crystals()`, `.score()`.

---

## Build order (smallest slice first — do NOT scaffold the whole app at once)

1. **State contract.** The outbound JSON shape of game state + inbound action message
   types. See `docs/CONTRACT.md`. Everything depends on this — lock it first.
2. **Server.** FastAPI + WebSockets: one `Game` per room, serialize-and-broadcast on
   change, receive-action → reconstruct → `apply_action` → catch `IllegalAction` →
   rebroadcast. Turn-gating.
3. **Single-client React.** One browser renders the full board and plays a whole game
   solo (user controls all seats). Proves rendering + the incremental action-builder
   (esp. Upgrade and Acquire flows) before adding networking noise.
4. **Multiplayer.** Lobby/rooms, seat assignment, multiple real clients on one game,
   "waiting for player" states.
5. **Robustness.** Reconnect (restore from server `Game`), persistence, then polish
   (animations, legal-move hints, sound).

At each step: build the slice, let the human run it, get their report, fix, move on.

---

## Two engine fixes owed BEFORE the UI needs them

1. **Surface the over-10 caravan discard as a sub-decision.** Currently
   `_enforce_caravan_limit` auto-drops the cheapest crystals when a caravan exceeds 10.
   The real rule lets the player choose. The UI needs this exposed as a prompt, not
   auto-resolved. (Handover §8 note 1.)
2. **Auto-load the compendium in the tracer / default decks.** The tracer still defaults
   to the engine's tiny sample deck. Wire in `century_cards.MERCHANT_CARDS` /
   `POINT_CARDS` so real cards are used by default. (Handover §3, §8 note 6.)

---

## Human-owned tasks (don't attempt these in code)

- Playtesting with real people.
- The two open card verifications (four-color golem costs #10/#11/#20/#23/#36, and
  merchant card #14) against the physical cards. (Handover §8.)
- Hosting/deployment, auth model (room link vs login), visual polish level.

---

## UI reference

The full board layout (5-player, one player's POV) and the element→engine-field mapping
were worked out separately. Key panels per seat: caravan (counts→swatches), hand,
played pile, claimed golems + golem points, tokens/coins, total score. Shared center:
golem row (5) + golem deck, play-card/merchant row (6, with crystals-on-cards) +
merchant deck, token piles (copper above leftmost golem/slot 0, silver above slot 1).
Global chrome: active-player highlight (`game.current`), first-player marker (seat 0),
win-target (`game.win_target`), game-over (`game.game_over`). Reserve a strip for
sub-decision prompts (acquire payment colors, upgrade targets, over-10 discard).

# Tutorial Handoff: Century: Golem Edition

*Written 30 Sep 2026 for a coding agent helping to build the game's tutorial.*

## Status, 1 Oct 2026: a working draft exists

The owner's spec is `docs/briefs/interactive-tutorial-script.pdf`. A first draft
of it is built and runs end to end:

- **Server:**
  - `server/tutorial.py` holds the steps and handles Next, the upgrade
    sandbox, the scene 6 check, the fast-forward and the Easy bot.
  - `server/tutorial_recording.json` is the recorded game: seed 9 plus 68
    moves, written by `server/make_tutorial_recording.py`.
  - `?tutorial=true` is routed in `main.py`.
- **Contract:** `docs/CONTRACT.md` §1e and the "Tutorial" part of §2.
- **Client:**
  - `web/src/components/TutorialOverlay.jsx`, with styles at the end of
    `styles.css`
  - the "How to play" link on `StartScreen`
  - the tutorial session in `App.jsx`
  - the target outline and Final Tally buttons in `Board.jsx` and
    `GameOverOverlay.jsx`
- **Tests:** `server/tests/test_tutorial.py`, with `server/tests` added to
  `pytest.ini`.

Still open: there's no rules page for "Read the rules" and the welcome text's
"here", and the board scenes are unusable at phone width (the board itself is
desktop-only).

## 0. What this is and how to use it

The project owner wants a **tutorial** for this online version of *Century:
Golem Edition*. They are writing the tutorial's own spec (content, steps and
format) in a **separate document** that they will give you with this one.

- **That document decides what the tutorial says and how it flows.** Where it
  conflicts with this one, it wins.
- **This document is the codebase context.** It covers the rules exactly as
  this app plays them, what's on screen and what everything is called, how
  each move is made in the UI, the pieces you can reuse, and the traps.

If the spec leaves something open that §10 lists, ask the owner. Don't guess.

**Read first, in this order:** `CLAUDE.md` (working rules),
`docs/PROJECT_HANDOVER.md` §1, §3 and §6 (the platform and the guided mode),
`docs/CONTRACT.md` §1a and §2 (the wire format). The rest of `docs/PROJECT_HANDOVER.md`
covers the AI and solver work. It's useful background, but you don't need it
to build a tutorial.

---

## 1. The project in brief

- `engine/century_engine.py` is the **only** rules implementation, in Python.
  Every move goes through `Game.apply_action`, which raises `IllegalAction`.
- `server/` runs FastAPI with plain WebSockets. It holds one `Game` per room,
  rebuilds each client intent into an engine action, validates it, and
  broadcasts a full `state` snapshot.
- `web/` is React 18 + Vite in plain JS, with **no router and no UI library**.
  `App.jsx` is a small state machine: `StartScreen` → `WaitingRoom` (lobby) →
  `Board` (game). The client never computes game state. It only renders what
  the server sends.
- Modes today:
  - **Multiplayer rooms:** create a room, or join one by code.
  - **Practice solo:** you against 1–4 bots at easy, medium or hard.
  - **Guided TEST rooms:** type room code `TEST` or `TEST<n>` to play seed *n*
    solo, with the solver's next best move outlined in red and explained in a
    banner. This is the closest thing to a tutorial that exists (§6.1).

---

## 2. The rules as this app plays them

Use this as the tutorial's source of truth for rules. It already includes the
places where the app differs from the printed rulebook, which are marked ⚠.

**Goal.** Collect crystals and spend them on golem cards. Golems are worth
points. The game ends once someone has enough golems, and the highest score
wins.

**Crystals.** Four colours make an upgrade chain: **Yellow → Green → Blue →
Magenta**. Magenta can't be upgraded. Your crystals are your **caravan**,
which holds at most **10**.
- In code, blue is `TURQUOISE`. On the wire and in the UI it's `B`/blue.

**Setup.**
- Face-up rows:
  - 5 golem cards in the golem row, with the rest in the golem deck.
  - 6 merchant cards in the merchant row, with the rest in the play-card deck.
- Token piles:
  - **Copper** (3 points each) sits above the leftmost golem.
  - **Silver** (1 point each) sits above the second golem.
  - Each pile starts with 2 × the number of players.
- Every player starts with two cards in hand:
  - **Create 2**, which gives +2 yellow.
  - **Upgrade 2**, a double upgrade.
- Starting crystals by seat: 1st 3Y · 2nd 4Y · 3rd 4Y · 4th 3Y+1G · 5th 3Y+1G.

**On your turn, do exactly one of these:**

| Action | What happens |
|---|---|
| **Play a crystal card** | Gain its crystals. The card goes to your played pile. |
| **Play an upgrade card** | Upgrade crystals one step at a time, up to the card's N steps. You can upgrade the same crystal more than once (Y→G→B). ⚠ The UI requires **exactly N** steps (the house rule the owner plays by). The engine allows "up to N". |
| **Play a trade card** | Pay the cost and get the gain, **repeated as many times as you can afford**. |
| **Acquire a merchant card** | Take the card in position *j* and put one crystal of your choice on each of the *j* cards to its left. The leftmost card is free. You also get any crystals already sitting on the card you take. The row slides left and refills. |
| **Rest** | Every card in your played pile goes back to your hand. ⚠ The button is labelled **"Reset"**. |
| **Claim a golem** | Pay its exact crystal cost and take it. Claiming from the 1st slot also takes a copper token, and the 2nd slot a silver one. When copper runs out, silver slides over to the 1st slot. The row slides left and refills. |

**Caravan limit.** After your action you may hold at most 10 crystals.
⚠ In normal games the engine automatically **discards the cheapest crystals
first** (yellow first). There's no prompt and no on-screen notice. The printed
rules let you choose. The engine can offer that choice (`discard_choice=True`)
but the client has no prompt for it yet.

**End of the game.** When someone claims their **6th** golem (2–3 players) or
**5th** golem (4–5 players), the current round is finished so that everyone
has had the same number of turns, and then the game ends. The goal is shown on
screen as golem slots: `win_target` in the state.

**Scoring.** Golem points + tokens (copper 3, silver 1) + **1 point for every
non-yellow crystal** left in your caravan. Yellow is worth 0. On a tie, the
player **later in turn order** wins.

**Hands are public.** You can open any player's full hand in this app, which
was a deliberate design decision.

### Card set (`engine/century_cards.py`)
- **43 merchant cards:**
  - 8 crystal cards, such as `+2G`, `+1B1Y`, `+4Y`
  - 1 upgrade card, `Triple upgrade`
  - 34 trade cards, such as `3Y->1M`, `2G->1B3Y`, `1M->2G2Y`
- **2 starting cards.** They're named differently in two places, so match
  cards by mechanics, not by name:
  - `Create 2 (+2Y)` in the compendium, `Create 2` in the engine
  - `Double upgrade` in the compendium, `Upgrade 2` in the engine
- **36 golems**, worth 6–20 points. Costs range from 2 colours to all 4.
- **Card art:** each card's cost and gain are **printed on its art**, so the UI
  shows no text for them. The name appears only as a hover tooltip. Art uses
  custom photos (`docs/CARD_ART_HANDOVER.md`). There's also a second, painted set
  in `gol/` (see §8).

---

## 3. What's on screen, and what everything is called

Match these labels in the tutorial text so that it points at what players
actually see.

| On screen | Label / look | Component |
|---|---|---|
| Start screen | "Hop in" / "Join a room". Fields: Name (max 14), Room code (max 8), Avatars (10 photos). Button: **Create room** / **Join room**. Below "or": **Bots** 1–4, **Skill** Easy / Medium / Hard (default Medium), **Practice solo** | `StartScreen.jsx` |
| Lobby | "Waiting for players", "N / 5 joined", host and you tags; only the host can start | `WaitingRoom.jsx` |
| Your mat (bottom centre) | **Your Turn** / **Waiting for other players…** banner. Three boxes: caravan (10-slot grid), **playable** and **played** card rows, **Golems** slots with token counts, **Points: N**, turn clock. **Reset** button below. | `MePanel.jsx`, `CaravanGrid.jsx`, `GolemSlots.jsx` |
| Centre board | Golem row (5) with the copper and silver piles above slots 1 and 2, plus **Golem deck** count. Merchant row (6), with any crystals sitting on the cards, plus **Play-card deck** count | `CenterBoard.jsx`, `TokenPile.jsx`, `DeckBox.jsx` |
| Opponents (around the table) | Avatar with a turn-order badge (1st, 2nd…), name, "Their turn" / "Waiting", **last played** card, hand count, caravan, golems N / target, played cards, **points**. Click to open a full read-only view | `OpponentPanel.jsx`, `PlayerDetailOverlay.jsx` |
| Dialogs | Trade: **Conversions** 1…N, **Updated caravan N / 10**, **Confirm**. Claim: **Claiming**, updated caravan, **Confirm**. Click outside or press Esc to cancel; Enter confirms | `TradeDialog.jsx`, `ClaimDialog.jsx` |
| Error strip | `[code] message ×` | `ActionStrip.jsx` |
| Game over | **Final Tally**: ranked rows with golem points, tokens and total score; "X wins!"; **View final board**, then a **View results** button to reopen it | `GameOverOverlay.jsx` |
| Top-right | **Leave game**, the only way back to the start screen (§8) | `Board.jsx` |

**About the points numbers:**
- Your "Points:" shows golem points + token points.
- An opponent's "points" shows **golem points only**, without tokens.
- Neither includes crystals, which only count at the end. The Final Tally
  shows the real total.

Mockups of the intended layout: `docs/mockups/full-board.png`, `docs/mockups/me-panel.png`
and `docs/mockups/middle-panel.png`.

---

## 4. How each move is made in the UI (the gestures to teach)

These all live in `web/src/components/Board.jsx`, with `MePanel.jsx`
handling the upgrade picker and `CenterBoard.jsx` the drag targets. Everything
is disabled when it isn't your turn.

- **Crystal card:** click it in **playable**. It plays at once, with no
  confirm step.
- **Upgrade card:** click it. A **Confirm** / **×** row appears above your
  caravan.
  - Click crystals in the caravan to upgrade them one step each. Click the
    same crystal again to keep upgrading it.
  - Click a crystal you've already upgraded as far as it can go to undo its
    last step.
  - Confirm only becomes clickable once **exactly N** steps are picked. So an
    Upgrade card can't be played at all when fewer than N steps are possible,
    for example when every crystal is magenta.
- **Trade card:**
  - If you can afford it only once, it plays at once.
  - If you can afford it more than once, a dialog opens with the maximum
    already selected. Pick a count (the number keys 1–9 also work), then
    Confirm.
  - Counts you can't afford are shown greyed out, not hidden.
- **Acquire:**
  - Leftmost card: just click it.
  - Any other card: **drag one crystal from your caravan onto each card to its
    left**, in any order, then **click the card you want**.
  - If a crystal is missing, the empty cards briefly flash.
  - To take a placed crystal back, click it.
  - *Which* crystal lands on *which* card matters: the next player picks it up.
  - The drag uses Pointer Events, not HTML5 drag-and-drop, so it works on
    touch screens.
- **Claim:** click a golem you can afford, then Confirm in the dialog.
  Clicking a golem you can't afford does nothing.
- **Rest:** click **Reset**. It's greyed out when your played pile is empty.
- **Reorder your hand:** drag cards within **playable**. This only changes
  your own display. It isn't sent to the server.
- **Look closer:**
  - Click one of your claimed golems to enlarge it.
  - Click an opponent's panel to see their full hand and played pile.
  - After the game, the full view shows how many times each card was played.

---

## 5. Strategy tips the tutorial could use (optional)

These come from the project's AI work: `results/REPORT.md` for the bots,
`results/solver_study.md` for the solver. Frame them as tendencies, not rules.
**Every bot result was measured against another bot**, and the owner beats
the "hard" bot easily.

- **Build first, then claim fast.** Near-optimal solo plans:
  - buy about 4 cards before their first golem
  - make their last purchase around turn 15
  - then claim a golem every 4–5 turns
- **Ending the game beats scoring big.** The game ends on a *count* of golems,
  so several cheaper golems are often better than one expensive one.
- **Yellow is worth more than it looks.** Measured values are Y 1.0, G 1.3,
  B 1.5, M 2.3, not 1/2/3/4. Yellow pays for acquisitions.
- **Crystal-making cards are the most-bought:** `+1B1Y`, `+2G`, `+1M`,
  `+1G2Y`. The two starting cards are the most-played cards in every plan.
- **Taking the free leftmost card is common.** The average near-optimal
  purchase slot is about 1.
- **Tokens and watching opponents mattered little** in the bot experiments.
  Fine to mention, but not worth teaching as a priority.
- **The deal matters a lot.** The same near-optimal play takes 24–44 turns
  depending on the shuffle. Seeds 15, 35 and 320 are the fastest known deals,
  at 24 turns.

---

## 6. Building blocks you can reuse

### 6.1 Guided TEST rooms: the existing "coach" pattern
This is the closest existing pattern for an interactive tutorial. Reuse its
*shape*.

- **Server** (`server/guided.py`):
  - `main.ws_room` routes a TEST code there before anything else, and only
    for rooms joined by code, not practice mode.
  - Guided games live in their own table (`GUIDED`), keyed by
    `CODE|name`.
  - Every state it sends carries an extra field:
    `state["guide"] = {seed, turn, planned_total, status, note, text, source, replans, action}`.
  - `action` is `{kind: "play"|"acquire"|"claim"|"rest"|"discard", hand_index?, row_index?, payment?, upgrades?, times?}`.
- **Client:**
  - `Board.jsx` reads `state.guide` and passes `guideAction` down.
  - `MePanel.jsx` and `CenterBoard.jsx` add the class `guide-target` to the
    matching hand card, merchant slot, golem slot or Reset button, which gives
    a pulsing red outline (`styles.css`, around line 2528).
  - `GuideBanner.jsx` shows the text above the board.
  - Normal games never get a `guide` field, so nothing changes for them.
- **Status:** **not committed yet** (see §9). It's been verified over a real
  websocket but **never viewed in a browser**.
- **Don't copy the dependency.** `guided.py` imports `solver/`, and
  the owner's standing rule is that the solver must not touch the
  multiplayer game; TEST rooms are the single approved exception. A scripted
  tutorial needs no solver. Write it as its own module with its own step
  list.

### 6.2 Controlling the deal
You can build a known board without touching the engine:

- `Game(names, seed=N)` gives a reproducible shuffle.
- `Game(names, merchant_deck=[...], point_deck=[...])` gives a hand-built
  deck. The row is dealt with `pop()` from the end of the shuffled list, so to
  get an exact row, pass the cards and control the shuffle, or build the game
  and then set `merchant_row`, `point_row` and `row_crystals` directly
  (server-side only).
- The card objects to use are in `century_cards.MERCHANT_CARDS` and
  `POINT_CARDS`. Real cards resolve to art. Cards you invent won't have any
  (`art: null`).
- `Game([name])` runs a **1-player** game (built for the solver, with a win
  target of 6). Guided rooms use it. If a tutorial game is solo, the
  opponent-panel layout collapses: `layout-opp-0` exists in `styles.css` for
  that case.

### 6.3 Components that render from plain props
`MerchantCard`, `GolemCard`, `CaravanGrid`, `CrystalDots`, `TokenPile` and
`GolemSlots` all take plain objects in the `docs/CONTRACT.md` §1a shapes. A static
tutorial page can show real-looking cards and caravans by passing mock data,
for example:

```js
{ kind: 'trade', name: '3Y->1M', cost: {Y:3,G:0,B:0,M:0}, trade_gain: {Y:0,G:0,B:0,M:1}, art: '/static/merchants/…png' }
```

However, **card art and crystal icons are loaded from the game server**
(`SERVER_HTTP_URL + art`, and `crystalIcons.js` → `/static/crystals/*.png`).
A static page shows blank cards unless the server is running, or unless you
copy a chosen few PNGs into `web/public/` and point `art` at them. The real
art filenames are in `server/card_art_index.py` or any live `state` message.

### 6.4 Dev helpers
- **Fast-forward a live room:** `POST /debug/simulate/{room}?max_actions=N`
  plays random legal moves, which is handy for mid-game screenshots.
- **Restart a room with the same seats:** `POST /debug/reset/{room}`.
- **Headless screenshots:** Playwright is installed in `web/` (`web/package.json`).
- **Turn-by-turn board positions:** `python -m solver.replay_log 15` writes
  `results/solver_logs/seed_015.md` with every position of seed 15's best
  plan. That's a good source for a worked example ("here's a strong opening").

---

## 7. Rules you must follow

These come from `CLAUDE.md` and `docs/PROJECT_HANDOVER.md` §10.

1. **One rules implementation.**
   - No JS copy of the rules, not even a partial one to "predict" a move for
     the tutorial.
   - If a tutorial step has to check or apply a move, the server does it
     through `apply_action`.
   - The existing client helpers (`trade.js`, `upgrade.js`) only preview
     dialogs. Don't grow them into a rules engine.
2. **Never trust the client.** A tutorial mode on the server still rebuilds
   actions with `server/actions.build_action` and validates them.
3. **Engine changes must be additive** and default to the old behaviour. Check
   them with a before-and-after state trace. You shouldn't need any engine
   change for a tutorial.
4. **The solver must not touch the multiplayer game** (§6.1).
5. **Don't change normal games.** Anything tutorial-only is gated the way
   `guide` is: an optional field or prop that ordinary rooms never send.
6. **Match the surrounding code.** Files carry dense "why" comments. Keep to
   that style, use plain CSS in `styles.css` with the existing `:root`
   tokens (§8), and **add no new npm or pip dependencies without asking**.
7. **Contract first.** Any new message or state field is written into
   `docs/CONTRACT.md` before it's implemented on both sides.

---

## 8. Gotchas that will bite a tutorial

- **Long room codes switch the card art.** Rooms with codes of **5 or more
  characters** use the painted `gol/` art set instead of the photo set
  (`server/card_art_index.py`, `GOL_MIN_CODE_LEN = 5`). So `TUTORIAL`
  would get painted art, and so does `TEST42`. Decide which set the tutorial
  should show, and gate on room code accordingly.
  - `gol/` is untracked, and its PNGs may be missing on a fresh checkout. The
    server falls back to the photo art when they are.
- **Reserved room codes.**
  - `TEST` / `TEST<digits>` are taken by the guided mode (regex
    `^TEST(\d{0,6})$`).
  - Random codes are 4 characters from `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`.
  - Codes are upper-cased on the client.
- **There's no router.** A tutorial page needs one of:
  - a new branch in `App.jsx`'s state machine, plus a button on `StartScreen`
  - a hash check such as `#tutorial`
  Either is fine. Don't add react-router without asking.
- **Refreshing auto-rejoins the last game.** The session is saved in
  `localStorage` under `century.session`. A refresh reconnects to the last
  room. **Leave game** is the only way back to the start screen. A tutorial
  flow needs to decide whether it wants this.
- **`web/src/config.js` has local edits** pointing at a Cloudflare tunnel.
  For local work you'll likely want `ws://localhost:8000`, but **don't commit
  that file**. It's the owner's in-progress edit.
- **Practice mode shuffles your seat.** Read your seat from `state.you`, never
  assume seat 0. Bots move one at a time, 0.45 s apart
  (`BOT_MOVE_DELAY_SECONDS`), and each move arrives as its own `state`.
- **Rows can shrink.** `golem_row` and `merchant_row` skip empty slots, so use
  each card's `slot` field rather than its array position.
- **Local UI state clears when the turn changes.** `Board.jsx` clears the
  upgrade picks, placed acquire crystals and open dialogs whenever
  `state.current` changes.
- **Discards are silent.** A tutorial step that overflows the caravan will
  drop crystals with no message, unless the tutorial either:
  - builds the game with `discard_choice=True` and resolves the discard
    server-side, as `solver/guide.py` `resolve_discards` does, or
  - avoids overflowing in its script.
- **Upgrade 2 can be stuck** (§4): if fewer than 2 steps are possible, the
  card can't be confirmed. Don't script a step that asks for it then.
- **The server must be running for any card image** (§6.3).
- **Style tokens** live in `styles.css` `:root`:
  - crystal colours `--y`, `--g`, `--b`, `--m`
  - walnut panels `--panel`, `--mat`
  - gold `--turn-gold`
  - dialogs `--dialog-*`
  - pale board background `--bg`
  - fonts: Georgia/serif for headings, system-ui elsewhere
- **Filenames:** keep the three engine files and their `century_` names
  together, or imports break. `player.caravan` is a list of four counts, not
  a list of crystals.

---

## 9. Running it and the state of the repository

```bash
# server (Python 3.13): pip install -r server/requirements.txt
cd server && python -m uvicorn main:app --port 8000
# client: SERVER_URL is in web/src/config.js
cd web && npm install && npm run dev
# tests (bots and solver): about 690 tests, about 2 minutes
python -m pytest -m "not slow"
```

Try `TEST15` on the start screen, using **Join room** rather than Practice
solo, to see the guided mode.

**Repository state as of 30 Sep 2026:**
- Branch `step0-orientation`; the main branch is `main`.
- There are many **uncommitted changes that belong to the owner or to earlier
  work**:
  - the guided mode: `server/guided.py`, `solver/guide.py`, `solver/plans.py`
    and `GuideBanner.jsx` are untracked, with edits in `Board.jsx`,
    `MePanel.jsx`, `CenterBoard.jsx` and `styles.css`
  - art changes, `config.js`, `StartScreen.jsx`, `main.py`, `serialize.py`,
    and others
- **Stage only your own files** when you commit. Commit only when the owner
  asks, in small commits titled by step, ending with the attribution line
  they use.
- `Board.jsx`, `MePanel.jsx`, `CenterBoard.jsx`, `styles.css` and
  `StartScreen.jsx` already have uncommitted edits. Read the current working
  copy before changing them, and keep your changes separable.

---

## 10. Questions to settle with the owner

Settle any of these that their tutorial document doesn't answer:

1. **Format:** a static illustrated rules page, an interactive guided game on
   a scripted deal, or both? If interactive, a new server mode such as
   `tutorial.py`, modelled on `guided.py` but with a fixed step list and no
   solver?
2. **Entry point:** a button on `StartScreen`, a special room code, a URL
   hash, or several of these?
3. **Art set:** the photo cards or the painted `gol/` cards?
4. **House rules:** should the tutorial teach "exactly N" upgrades and the
   automatic discard as they behave here, or mention the printed rules too?
5. **Player count** for an interactive tutorial: solo (no opponents on
   screen), or against a scripted or `easy` bot?
6. **Strategy content:** include §5's tips, and how firmly to state them?
7. **Mobile:** must the tutorial work on phones? The board is desktop-first;
   the drag works on touch.

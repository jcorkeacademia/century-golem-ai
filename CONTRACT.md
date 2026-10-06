# CONTRACT.md — client/server state & action contract

The single seam between the Python server and the React client. Both sides implement
exactly this. Change it here first, then update both sides. See `CLAUDE.md` for rules
and `HANDOVER.md` for engine details.

Transport: **WebSocket**, one connection per client, JSON text frames — one socket per
seat, period (a browser never opens more than one). One `Game` per room,
server-authoritative. The client sends *intents*; the server validates via
`apply_action` and broadcasts new state. The client never computes game state.

Connecting: `ws://<server>/ws/<room_id>?name=<name>&avatar=<avatar_id>`. A room is
created empty on its first connection — there is no upfront roster/`players` param.
`name` either reclaims a seat it already holds in that room (reconnect — `avatar` is
ignored in this case, it was already fixed at first join), or claims the next open
seat if the room hasn't started and has fewer than 5 players. Seat 0 is whoever
connects first (the **host**). `avatar_id` is any id from the client's own avatar
list (`web/src/avatars.js`) — the server stores and echoes it back verbatim in
`lobby`/`state`, it doesn't validate against that list itself. See §1d/§2 "Lobby" for
how a room fills and starts.

**Practice mode** (`server/main.py`'s `_run_solo`) adds three optional query
params and skips the lobby entirely — the game starts the instant the socket
connects, and every seat but yours is played server-side:

```
ws://<server>/ws/<room_id>?name=<name>&avatar=<avatar_id>
                          &solo=true&players=<2-5>&difficulty=<easy|medium|hard>
```

* `players` is the **total** seat count including you, clamped to 2-5.
* `difficulty` picks the opponent (`server/bot_policy.py`). `easy` is the
  original claim-or-random policy, `medium` is the rule-based GreedyBot, and
  `hard` is the tuned bot from `results/REPORT.md`. Anything unrecognised —
  including the param being absent — falls back to the server's default, so
  the client never needs to know what that default is.
* Which seat you get is shuffled at room creation, so read it off
  `state.you` like any other game. Nothing assumes seat 0.

The difficulty is fixed when the room is created and kept for the life of the
game, so a mid-game reconnect cannot silently change opponent.

**Interactive tutorial** (`server/tutorial.py`) is one more optional param, and
like practice mode it skips the lobby:

```
ws://<server>/ws/<room_id>?name=<name>&avatar=<avatar_id>&tutorial=true
```

You are always seat 0 of a 2-player game replayed from a recorded game
(`server/tutorial_recording.json`). Every `state` carries an extra
`tutorial` field (§1e); no other room ever does. The client uses a
6-character room code, which shows the painted card art (any code of 5 or
more characters does, see `server/card_art_index.py`). Tutorials are keyed by
room code and name, so a refresh resumes at the same step.

---

## Message envelope

Every message (both directions) is a JSON object with a `type` field.

```json
{ "type": "<message_type>", ... }
```

---

## 1. Server → client messages

### 1a. `state` — full game state (sent on join and after every applied action)

The client re-renders from this wholesale. It is a complete snapshot, not a diff.

```json
{
  "type": "state",
  "room": "abc123",
  "you": 0,                      // seat index of THIS client (0-based); null if spectator
  "current": 2,                  // seat index whose turn it is
  "first_player": 0,             // always 0 with current engine (see CLAUDE.md gotchas)
  "win_target": 5,              // golems needed to trigger end (5 for 4-5p, 6 for 2-3p)
  "game_over": false,
  "winner": null,                // player name string once game_over, else null

  "shared": {
    "golem_row": [               // game.point_row, left→right; slot 0 is leftmost
      { "slot": 0, "name": "…", "points": 15, "cost": {"Y":0,"G":0,"B":2,"M":2},
        "art": "/static/golems/golem_30_17pts.png" },
      { "slot": 1, "name": "…", "points": 20, "cost": {"Y":0,"G":0,"B":0,"M":4},
        "art": "/static/golems/golem_35_20pts.png" }
      // …up to 5
    ],
    "golem_deck_count": 27,       // len(game.point_deck) — count only, never contents

    "merchant_row": [            // game.merchant_row, left→right; slot 0 is leftmost
      {
        "slot": 0,
        "kind": "crystal",       // "crystal" | "upgrade" | "trade"
        "name": "…",
        "gain": {"Y":2,"G":0,"B":0,"M":0},         // crystal cards
        "steps": null,                              // upgrade cards: int, else null
        "cost": null, "trade_gain": null,           // trade cards: both set, else null
        "crystals_on_card": {"Y":1,"G":0,"B":0,"M":0}, // game.row_crystals[slot]
        "art": "/static/merchants/merchant_07_trade.png" // null if unmatched/unrendered
      }
      // …up to 6
    ],
    "merchant_deck_count": 31,    // len(game.merchant_deck)

    "tokens": {                   // game.point_tokens; piles sit above golem slots
      "copper": { "slot": 0, "count": 8, "value": 3 },
      "silver": { "slot": 1, "count": 10, "value": 1 }
      // when copper empties, silver slides to slot 0 — reflect the current slot here
    }
  },

  "players": [                    // one entry per seat, index == seat, in seating order
    {
      "seat": 0,
      "name": "Alice",
      "avatar": "gem",                         // the id they connected with (room.avatars[seat])
      "caravan": {"Y":2,"G":2,"B":2,"M":1},   // EXPANDED from player.caravan counts
      "caravan_total": 7,                      // player.total_crystals()
      "hand": [                                // hands are PUBLIC (design decision)
        { "hand_index": 0, "kind": "crystal", "name": "…",
          "gain": {"Y":2,"G":0,"B":0,"M":0}, "steps": null,
          "cost": null, "trade_gain": null, "art": "/static/merchants/start_44_crystal.png" }
        // …same card shape as merchant_row cards, minus slot/crystals_on_card
      ],
      "played": [ /* same card shape as hand */ ],
      "golem_count": 2,                        // len(player.point_cards)
      "golem_points": 25,                      // sum of points on claimed golems (DERIVED)
      "tokens": { "copper": 1, "silver": 0 },  // player.tokens
      "score": 30                              // player.score() — total (DERIVED)
    }
    // …one per player
  ],

  "pending_decision": null        // see §1b; null when no sub-decision is open
}
```

**Crystal keys are always `Y`, `G`, `B`, `M`.** `B` = the engine's `TURQUOISE`.
Include all four keys even when 0, so the client never guesses.

**`art`** is a server-relative URL (join with the HTTP origin the client already
derives from `SERVER_URL`) for the card's rendered artwork, or `null` if the
card has no matching art (see `CARD_ART_HANDOVER.md`). Present on every golem
and merchant/hand/played card. Resolved server-side via `card_art.art_for()`,
indexed once at startup — never null for cards in the shipped compendium.

### 1b. `pending_decision` — sub-decisions the acting player must resolve

When an action needs a follow-up choice, `pending_decision` on the state is non-null and
describes what the **current** player must answer. Only the current client acts on it.

```json
// caravan over 10 at end of turn — player chooses which to drop
{ "kind": "caravan_discard", "seat": 2, "over_by": 3,
  "caravan": {"Y":4,"G":3,"B":3,"M":3} }

// acquire payment — one crystal must be placed on each card left of the target
{ "kind": "acquire_payment", "seat": 2, "row_index": 3,
  "num_to_place": 3 }        // client picks a color per card-to-the-left

// upgrade targets — which crystals to bump, up to card.steps
{ "kind": "upgrade_targets", "seat": 2, "hand_index": 1, "max_steps": 2 }
```

> NOTE: `caravan_discard` requires the engine fix in `CLAUDE.md` (currently auto-resolved).
> Until that lands, the server never emits `caravan_discard` and the client won't see it.

### 1c. `error` — an action was rejected or malformed

```json
{ "type": "error", "code": "illegal_action",
  "message": "human-readable reason", "echo": { /* the action that failed */ } }
```

Codes: `illegal_action` (engine raised `IllegalAction`), `not_your_turn`,
`malformed`, `game_over`, `name_taken` (that seat's socket is already live),
`already_started` (a new name tried to join a room whose game has started),
`room_full` (room already has 5 players), `not_host` (non-seat-0 sent `start`),
`not_enough_players` (`start` sent with fewer than 2 or more than 5 names),
`tutorial` (tutorial rooms only: not what the current step asks for, see §2).

### 1d. `lobby` — pre-game room state (sent on connect and whenever the seat list
changes, until the game starts)

```json
{ "type": "lobby", "room": "abc123", "you": 1,
  "seats": [ { "seat": 0, "name": "Alice", "avatar": "gem", "connected": true },
             { "seat": 1, "name": "Bob", "avatar": "tide", "connected": true } ],
  "host": 0, "started": false }
```

`you` is this socket's own seat (same idea as `state.you`). `connected: false` means
that name joined earlier but its socket has since dropped — the seat is still theirs
(they can reconnect with the same name), it just isn't held open right now. `host` is
always `0`: only that seat may send `start`.

### 1e. `tutorial` — the tutorial's current step (tutorial rooms only)

An extra field on `state`, present only when connected with `?tutorial=true`.
Ordinary, practice and guided rooms never carry it.

```json
"tutorial": {
  "id": "pay",                    // the step's id in server/tutorial.py's STEPS
  "step": 8, "total": 14,         // "Step 8 of 14"
  "scene": 6,                     // scene number in the tutorial design doc
  "title": "Skipping ahead",
  "paragraphs": ["To take a card further along, …"],
  "instruction": "Try it: drag a yellow gem onto …",
                                  // the exact move a step wants, or null
  "refusal": "Not that one. Drag a yellow gem onto …",
                                  // what a wrong move is told (sent ahead, so the
                                  // box can hold room for the longer line), or null
  "earlier": [ <section> ],       // the step this one continues in the same box
  "later": [ <section> ],         // the step that will continue this one
  "stage": null,                  // null = the live board; otherwise a staged screen
                                  // drawn over it: "title" | "caravan" | "order"
                                  // | "upgrade" | "turn" | "cards"
  "stage_data": null,             // what that staged screen shows, see below
  "highlight": "merchant_card",   // null | "merchant_row" | "merchant_card" | "me_mat"
                                  // | "played" | "reset" | "golem_row"
  "highlight_slot": 2,            // merchant_card only: which slot to circle
  "anchor": "merchant_row",       // board steps: the part of the board the box is
                                  // placed against — "merchant_row" | "mat" |
                                  // "golem_row" — or null (centred)
  "wait": "action",               // what ends the step:
                                  //   "next"      the player clicks Next (tutorial_next)
                                  //   "action"    the player makes `target`, exactly
                                  //   "upgrade"   the upgrade exercise (play_upgrade)
                                  //   "busy"      the server is replaying moves; wait
                                  //   "free_play" ordinary play until game_over
  "target": { "kind": "acquire", "row_index": 2, "payment": ["Y","Y"] },
                                  // same shape as state.guide.action, or null
  "feedback": null                // or { "ok": false, "text": "Not quite …" }
}
```

A `<section>` is one step's words: `{ "id", "title", "paragraphs", "instruction", "refusal" }`.

**Shared boxes.** Some steps continue the step before them in the same box:
scenes 2-5 (caravan → gem order → upgrade → recap → one thing per turn),
merchant cards → skipping ahead, and played cards → reset. `earlier` holds the
step before (one step back only, so the oldest words drop off as the page moves
on); `[]` when a box starts. `later` holds the step that will follow in the
same box; it is never shown, but lets the client size the box for both steps
from the start, so nothing moves when the second step's words appear. Both are
sent with every state rather than remembered, so a refresh shows the same box.

`stage_data` by `stage`, with crystal bundles and cards in the §1a shapes:

| `stage` | `stage_data` |
|---|---|
| `title` | `null` |
| `caravan`, `turn` | `{ "caravan": {Y,G,B,M} }` |
| `order` | `{ "caravan": {…}, "card": <card> }` |
| `upgrade` | `{ "caravan": {…}, "card": <card>, "objectives": [{ "text": "…", "done": false }], "attempt": 0 }` — objectives can be done in any order; `attempt` goes up every time the caravan is reset, so the client can clear its picks |
| `cards` | `{ "cards": [{ "card": <card>, "heading": "Crystal", "text": "…" }] }` |

---

## 2. Client → server messages

The client sends the action the player is attempting. The server reconstructs the engine
`Action`, calls `apply_action`, and broadcasts new `state` (or returns `error`).
`hand_index` / `row_index` / `slot` refer to indices in the latest `state`.

```json
{ "type": "play_crystal", "hand_index": 0 }

{ "type": "play_upgrade", "hand_index": 1,
  "upgrades": ["Y","G"] }        // ordered colors to upgrade; len <= card.steps

{ "type": "play_trade", "hand_index": 2, "times": 3 }   // repetitions, >= 1

{ "type": "acquire", "row_index": 3,
  "payment": ["Y","Y","G"] }     // one color per card to the LEFT; len == row_index

{ "type": "rest" }

{ "type": "claim", "row_index": 1 }
```

### Resolving a `pending_decision`

The follow-up answer rides on the same action that opened it (the client gathers the
sub-choice in the UI, then sends the complete action). i.e. `acquire` already carries its
`payment`, `play_upgrade` already carries its `upgrades`. The separate `caravan_discard`
answer (once the engine supports it) will be:

```json
{ "type": "caravan_discard", "drop": {"Y":3,"G":0,"B":0,"M":0} }
```

### Lobby

There's no separate `join` message — joining *is* connecting the socket (see the
Connecting note above `?name=`). The only lobby action is:

```json
{ "type": "start" }
```

Only seat 0 (the host) may send it, and only while `room.started` is false with
2-5 names already joined; it constructs the `Game` and the room's normal `state`
broadcasts take over from there.

### Tutorial

```json
{ "type": "tutorial_next" }
```

Ends a step whose `wait` is `"next"`. During the upgrade exercise
(`wait: "upgrade"`), `play_upgrade` with `hand_index: 0` is checked against a
separate sandbox game holding the exercise caravan, never the recorded game.
Any other action is accepted only when it is the step's `target` (`wait:
"action"`) or during `"free_play"`; otherwise the reply is
`error` with code `tutorial` and a message saying what to do instead.

---

## 3. Mapping to the engine (server side)

| Contract field                  | Engine source                                   |
|---------------------------------|-------------------------------------------------|
| `current`                       | `game.current`                                  |
| `win_target`                    | `game.win_target`                               |
| `game_over` / `winner`          | `game.game_over` / `game.winner()`              |
| `shared.golem_row`              | `game.point_row` (PointCard.cost/points/name)   |
| `shared.golem_deck_count`       | `len(game.point_deck)`                          |
| `shared.merchant_row`           | `game.merchant_row` (+ branch on card type)     |
| `…crystals_on_card`             | `game.row_crystals[slot]`                       |
| `shared.merchant_deck_count`    | `len(game.merchant_deck)`                        |
| `shared.tokens`                 | `game.point_tokens`                             |
| `…art` (golem/merchant/hand/played) | `card_art_index.art_url_for(card)` — startup-built index over `card_art.art_for()` |
| `players[i].caravan`            | expand `player.caravan` (list[int] len 4)       |
| `players[i].caravan_total`      | `player.total_crystals()`                       |
| `players[i].hand/played`        | `player.hand` / `player.played`                 |
| `players[i].golem_count`        | `len(player.point_cards)`                       |
| `players[i].golem_points`       | `sum(pc.points for pc in player.point_cards)`   |
| `players[i].tokens`             | `player.tokens`                                 |
| `players[i].score`              | `player.score()`                                |
| `pending_decision` (payment/upgrade) | derived from `game.legal_actions()`        |

Action reconstruction (inbound → engine):

| Inbound `type`   | Engine action                              |
|------------------|--------------------------------------------|
| `play_crystal`   | `PlayCrystal(hand_index)`                   |
| `play_upgrade`   | `PlayUpgrade(hand_index, tuple(upgrades))`  |
| `play_trade`     | `PlayTrade(hand_index, times)`              |
| `acquire`        | `Acquire(row_index, tuple(payment))`        |
| `rest`           | `Rest()`                                     |
| `claim`          | `Claim(row_index)`                           |

Colors map `Y/G/B/M` → `Crystal.YELLOW/GREEN/TURQUOISE/MAGENTA`. Validate every inbound
message shape before constructing the action; on any mismatch send `error: malformed`.

---

## 4. Invariants the server must enforce

- Reject actions where the sender's seat != `current` → `error: not_your_turn`.
- Never send deck contents or order — counts only.
- Recompute and broadcast full `state` after every applied action; clients are stateless
  re-renderers.
- One source of truth: the server's `Game`. On reconnect, resend current `state`.

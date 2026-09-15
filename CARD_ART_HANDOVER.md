# Card Art Pipeline — Handover

**Scope:** custom card artwork for *Century: Golem Edition* (hockey-team faces
replacing the published art), plus a verified mapping from artwork to engine
card objects.
**Status:** complete and audited. Nothing here touches the server or web UI yet.
**Date:** 1 Sep 2026

---

## 1. What was built

| Thing | Where | Status |
|---|---|---|
| 36 golem card PNGs | `century/engine/out/` | done |
| 45 merchant card PNGs (43 deck + 2 starting) | `century/engine/out_merchants/` | done |
| Print PDFs (9-up, cut lines, actual size) | in the same two folders | done |
| Golem generator | `century/engine/make_cards.py` | done |
| Merchant generator | `century/engine/make_merchants.py` | done |
| Crystal icon set (4 PNGs, transparent) | `century/engine/crystals/` | done |
| Art→card mapping + audit | `century/engine/card_art.py` | done, passing |

Everything now lives under `C:\Users\jcork\century\engine\`. It used to be in
`OneDrive\Desktop\golem-cards`; that copy is stale, ignore it.

---

## 2. The one thing the server chat actually needs

**`card_art.py` exposes `art_for(card) -> Path | None`.**

```python
import century_cards as C, card_art
card_art.art_for(C.POINT_CARDS[0])
# -> WindowsPath('.../engine/out/golem_01_6pts.png')
```

It accepts any `PointCard`, `CrystalCard`, `UpgradeCard`, or `TradeCard` and
returns the image path for it. That is the whole integration surface.

Run `python card_art.py` for a self-audit. Exit code 0 = the artwork and
`century_cards.py` describe the same deck; 1 = they disagree, with details
printed. Worth wiring into CI.

---

## 3. How the mapping works (and why it is not by index)

The image slots are sorted **by value** — golems ascending by points, merchants
by net crystal gain. `century_cards.py` is in its own unrelated order. Joining
on list position would silently scramble the deck.

So the join is on card **content**, via a normalised signature:

- golem → `("golem", points, frozenset{(Crystal, count)})`
- crystal card → `("crystal", frozenset_of_gain)`
- trade card → `("trade", frozenset_of_cost, frozenset_of_gain)`
- upgrade card → `("upgrade", steps)` — distinguishes the deck's triple
  upgrade from the starting double

Frozensets make it order-independent, so tuple ordering inside
`century_cards.py` cannot break it.

> **Note:** `"B"` in all art code is the **blue** crystal, which the engine
> calls `Crystal.TURQUOISE`. `card_art.KEY` does that translation.

---

## 4. Bug found and fixed

The audit caught a real transcription error.

**Merchant card #37 was wrong in `century_cards.py`:** it read `5Y->3B`; the
authoritative card list says **`4Y → 3B`**. Fixed — the file in
`century/engine/century_cards.py` now has `TradeCard(((Y, 4),), ((B, 3),),
"4Y->3B")`.

This matters for the solver. On the Y=1/G=2/B=3/M=4 upgrade chain, `4Y→3B` is
net **+5**, the single most efficient trade in the deck; `5Y→3B` is net +4 and
unremarkable. An MCTS agent trained on the old data would have built strategy
around a card that does not exist.

**Also resolved:** merchant #14 is confirmed as `2G → 1M, 2Y` (pay 2 green, get
1 magenta + 2 yellow). This was flagged as an open question in `HANDOVER.md` §8.
The four-colour golem costs (#10, #11, #20, #23, #36) also all verified clean.

`HANDOVER.md` §8 should be updated to close both items.

---

## 5. What the server/UI still has to do

None of this is started.

1. **Serve the images.** They sit in `engine/out/` and `engine/out_merchants/`,
   which is not a public static directory. Copy or symlink into something like
   `web/static/cards/`, or add a static route.
2. **Send art references in game state.** The server currently sends card
   names/IDs (assumed). Add the image path or a stable card key, resolved
   server-side via `art_for()`.
3. **Render them.** Front-end draws `<img>` instead of whatever placeholder it
   uses now.

Suggested: resolve `art_for()` once at startup into a `{card_key: url}` dict
rather than calling it per request. The lookup is a dict hit, but building the
index touches the filesystem.

---

## 6. Card dimensions and formats

- 750 × 1050 px, 300 DPI, poker size (2.5" × 3.5")
- PNG, no bleed (`BLEED = 0` in `make_cards.py` if a printer needs it)
- Golem cards: navy border, photo, point value, crystal cost along the bottom
- Merchant cards: plum border, photo, cream effect strip hanging from the
  top-left corner (cost crystals → purple down arrow → gain crystals)
- Starting cards: purple border, filenames prefixed `start_` not `merchant_`

Filenames: `golem_NN_Ppts.png` and `merchant_NN_kind.png` / `start_NN_kind.png`,
where `NN` is the sorted slot number.

---

## 7. Regenerating

Photo assignment is driven by two CSVs in `engine/`:

- `cards.csv` — golems, 36 rows
- `merchants.csv` — merchants, 45 rows

Columns: `slot, ..., photo, player`. Put a filename in `photo` to pin a face to
a specific card; leave blank and it auto-fills from the pool. Extensions
optional. Source images live in `photos/` (golems) and `photos_merchants/`
(merchants) — the merchant generator excludes anything `cards.csv` already
claimed, so the two decks never share a face.

```powershell
cd "$HOME\century\engine"
python make_cards.py --check      # report missing photos, render nothing
python make_cards.py              # write out/
python make_merchants.py --check
python make_merchants.py          # write out_merchants/
python card_art.py                # re-audit after any change
```

---

## 8. Known gotchas

1. **`card_art.py` duplicates the card lists** from both generators
   (`GOLEM_SLOTS`, `MERCHANT_SLOTS`). This is deliberate — the duplication is
   what makes the audit a genuine cross-check rather than a tautology. **Do not
   "fix" it by importing one from the other.** If you edit a card, edit both
   places, or the audit reports a confusing orphan.
2. **Starting cards are one artwork each**, not five. The game wants one Create 2
   and one Upgrade 2 per player up to 5 — print physical duplicates.
3. **`merchants.csv` may still have stale rows 46–53** from an earlier 53-slot
   version. Harmless (the script reads only 1–45) but worth deleting.
4. **`LAST_SLOT` in `make_merchants.py`** controls how many merchant slots
   render. 45 = full deck + starting cards; 43 = deck only.
5. The old `OneDrive\Desktop\golem-cards\` folder is a stale duplicate.

---

## 9. Suggested next steps

**For the server chat:** §5 above. The integration surface is one function.

**Not started, still open from the main handover:** the optimal-play AI
(Phase 3, stated priority goal). The engine's `legal_actions()` +
`apply_action()` is ready for it. Recommended order is a heuristic bot first —
valuing crystals by upgrade-chain position and learning rest timing, since the
current test bot hoards and never rests — before moving to MCTS self-play.

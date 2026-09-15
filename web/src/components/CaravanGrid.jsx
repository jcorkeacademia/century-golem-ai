import { NEXT_COLOR, baseSlotColors } from '../upgrade.js'
import { crystalIconUrl } from '../crystalIcons.js'

const NOT_UPGRADABLE = 'M' // magenta is maxed out, per century_engine.Crystal.can_upgrade

// Opponent caravan: a fixed 10-slot 2-row grid (10 is the caravan cap),
// filled with the real gem icons (same PNGs printed on the cards) for owned
// crystals, empty outlined slots for the rest — mirrors the mockup's
// placeholder circle grid but driven by real per-color counts instead of a
// flat total.
//
// `picks` (optional): ordered list of slot indices clicked so far during an
// in-progress upgrade (see upgrade.js) — rendering is positional so the
// exact swatch you click is the one that visibly advances/sparkles, rather
// than "a same-colored slot somewhere" shifting around as counts change.
// `onSlotClick(index)` (optional) makes every upgradable slot clickable.
//
// `onCrystalPointerDown(index, color, event)` / `draggingIndex` (optional):
// acquire-payment dragging (MePanel.jsx/CenterBoard.jsx/Board.jsx) — a
// crystal is picked up from here and dropped onto a specific merchant-row
// card. This is a custom pointer-based drag (Board.jsx owns the actual
// pointermove/pointerup tracking), NOT the native HTML5 Drag and Drop API —
// that API's browser support turned out to be unreliable in at least one
// real environment this app runs in (an interrupted drag could leave the
// whole page's click handling stuck), where Pointer Events are a much more
// consistently implemented primitive. `draggingIndex` (which slot, if any,
// is the current drag's source) is therefore owned by the caller instead of
// tracked locally, so it stays in sync with the one real drag Board.jsx is
// tracking. Mutually exclusive with `onSlotClick` in practice (a caravan is
// only ever mid-upgrade or mid-acquire, never both), but nothing here
// enforces that — it's just whichever props the caller passes.
export default function CaravanGrid({ bundle, picks, onSlotClick, onCrystalPointerDown, draggingIndex }) {
  const base = baseSlotColors(bundle)
  const pickCounts = new Array(base.length).fill(0)
  if (picks) for (const idx of picks) pickCounts[idx] += 1

  return (
    <div className="caravan-grid">
      {base.map((baseColor, i) => {
        let color = baseColor
        for (let k = 0; k < pickCounts[i]; k++) color = NEXT_COLOR[color]
        const pending = pickCounts[i] > 0
        // A slot pending at magenta stays clickable — that's how a mis-click
        // gets undone (see Board.jsx's handleUpgradePick) — but a slot that
        // was *already* magenta before any picks stays inert, same as ever.
        const clickable = Boolean(onSlotClick && color && (color !== NOT_UPGRADABLE || pending))
        const draggableSlot = Boolean(onCrystalPointerDown && color)
        const classes = [color ? `slot filled slot-${color}` : 'slot empty']
        if (pending) classes.push('slot-pending')
        if (clickable) classes.push('slot-clickable')
        if (draggableSlot) classes.push('slot-draggable')
        if (draggingIndex === i) classes.push('slot-dragging')
        return (
          <span
            key={i}
            className={classes.join(' ')}
            onClick={clickable ? () => onSlotClick(i) : undefined}
            onPointerDown={
              draggableSlot
                ? (e) => {
                    // Only the primary button/touch starts a drag — and
                    // preventDefault here is what stops this from also
                    // being read as a text-selection or a touch-scroll.
                    if (e.button !== undefined && e.button !== 0) return
                    e.preventDefault()
                    onCrystalPointerDown(i, color, e)
                  }
                : undefined
            }
            style={draggableSlot ? { touchAction: 'none' } : undefined}
          >
            {color && <img className="gem-icon" src={crystalIconUrl(color)} alt="" draggable={false} />}
          </span>
        )
      })}
    </div>
  )
}

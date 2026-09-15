// Shared between CaravanGrid.jsx (rendering), MePanel.jsx (wiring the
// picker), and Board.jsx (validating clicks / building the final action).
//
// The caravan is counts-based (player.caravan = {Y,G,B,M}), but the picker
// needs to be positional: clicking the leftmost yellow should visibly
// upgrade *that* swatch in place, not "a yellow" wherever the render happens
// to shrink the group from. So `picks` here is an ordered list of *slot
// indices* (0-9, into the same fixed layout CaravanGrid renders), not
// colors — the color to send the engine is derived by replaying each pick.
export const NEXT_COLOR = { Y: 'G', G: 'B', B: 'M' }
const ORDER = ['Y', 'G', 'B', 'M']

// The stable 10-slot layout for a caravan bundle — same grouping order
// every render, independent of picks, so slots don't shuffle as you click.
export function baseSlotColors(bundle) {
  const colors = []
  for (const c of ORDER) {
    const n = bundle[c] ?? 0
    for (let i = 0; i < n; i++) colors.push(c)
  }
  while (colors.length < 10) colors.push(null)
  return colors.slice(0, 10)
}

// The color a given slot currently shows, after replaying however many
// times it's been picked so far (chaining: 2nd pick on the same slot
// advances from whatever the 1st pick left it at).
export function slotColorAfterPicks(bundle, picks, index) {
  let color = baseSlotColors(bundle)[index]
  for (const idx of picks) if (idx === index) color = NEXT_COLOR[color]
  return color
}

// Converts the index-based picks (click order) into the ordered color
// sequence century_engine.PlayUpgrade.upgrades expects.
export function picksToColors(bundle, picks) {
  const base = baseSlotColors(bundle)
  const timesSeen = new Array(base.length).fill(0)
  const colors = []
  for (const idx of picks) {
    let color = base[idx]
    for (let k = 0; k < timesSeen[idx]; k++) color = NEXT_COLOR[color]
    colors.push(color)
    timesSeen[idx] += 1
  }
  return colors
}

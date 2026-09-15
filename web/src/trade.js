// Shared between Board.jsx (deciding whether to open the dialog at all) and
// TradeDialog.jsx (rendering it) — one source of truth for trade math,
// mirroring century_engine._trade_options' own max_times formula.
export const ALL_COLORS = ['Y', 'G', 'B', 'M']

// The caravan's hard cap (_enforce_caravan_limit) — the real ceiling on how
// many times a trade could ever repeat, regardless of what's affordable
// this instant. Used so the dialog can show (and grey out) counts beyond
// what you can currently pay for, per trade_dialog_prompt.md: "Don't hide
// them — the player should see the ceiling."
const CARAVAN_CAP = 10

export function maxAffordableTradeTimes(caravan, cost) {
  const limits = ALL_COLORS.filter((c) => cost[c] > 0).map((c) => Math.floor(caravan[c] / cost[c]))
  return limits.length ? Math.min(...limits) : 0
}

export function tradeCeiling(cost) {
  const limits = ALL_COLORS.filter((c) => cost[c] > 0).map((c) => Math.floor(CARAVAN_CAP / cost[c]))
  return limits.length ? Math.min(...limits) : 0
}

export function applyTrade(caravan, cost, gain, times) {
  const out = { ...caravan }
  for (const c of ALL_COLORS) {
    out[c] = (out[c] || 0) - (cost[c] || 0) * times + (gain[c] || 0) * times
  }
  return out
}

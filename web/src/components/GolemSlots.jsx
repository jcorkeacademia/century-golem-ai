import GolemCard from './GolemCard.jsx'

// A faint humanoid-golem glyph for empty slots — "empty slots are artwork,"
// not a blank dashed box (see player_mat_prompt.md §3).
function GolemGlyph() {
  return (
    <svg viewBox="0 0 40 54" className="golem-glyph" aria-hidden="true">
      <circle cx="20" cy="15" r="7" />
      <path d="M11 26h18v16a4 4 0 0 1-4 4H15a4 4 0 0 1-4-4z" />
      <rect x="4" y="27" width="5" height="13" rx="2.5" />
      <rect x="31" y="27" width="5" height="13" rx="2.5" />
    </svg>
  )
}

// Real card-shaped slots for claimed golems — actual card art, not just a
// point value on a flat tile, so you can actually tell which golems are
// yours at a glance. `onSelect(card)` (optional) opens a closer look
// (GolemZoomOverlay via Board.jsx) — clicking a golem you've already
// claimed can't do anything else, so a click here only ever means "show me
// this bigger." `total` is state.win_target — the number of slots ends the
// game.
export default function GolemSlots({ golems, total, onSelect }) {
  const emptyCount = Math.max(0, total - golems.length)

  return (
    <div className="golem-slots">
      {golems.map((g, i) => (
        <div key={i} className="golem-slot filled">
          <GolemCard card={g} onClick={onSelect ? () => onSelect(g) : undefined} title={`View ${g.name}`} />
        </div>
      ))}
      {Array.from({ length: emptyCount }).map((_, i) => (
        <span key={`empty-${i}`} className="golem-slot-empty">
          <GolemGlyph />
        </span>
      ))}
    </div>
  )
}

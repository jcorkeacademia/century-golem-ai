import { crystalIconUrl } from '../crystalIcons.js'

const ORDER = ['Y', 'G', 'B', 'M']

// Renders a {Y,G,B,M} bundle as one small gem icon per unit (capped) — the
// same PNGs printed on the cards — for compact overlays on card art.
export default function CrystalDots({ bundle, cap = 6 }) {
  if (!bundle) return null

  const dots = []
  for (const color of ORDER) {
    const n = bundle[color] ?? 0
    for (let i = 0; i < n; i++) dots.push(color)
  }
  if (dots.length === 0) return null

  const shown = dots.slice(0, cap)
  const overflow = dots.length - shown.length

  return (
    <span className="crystal-dots">
      {shown.map((c, i) => (
        <span key={i} className={`dot dot-${c}`}>
          <img className="gem-icon" src={crystalIconUrl(c)} alt="" draggable={false} />
        </span>
      ))}
      {overflow > 0 && <span className="dot-overflow">+{overflow}</span>}
    </span>
  )
}

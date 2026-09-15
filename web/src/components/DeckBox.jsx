export default function DeckBox({ label, count }) {
  return (
    <div className="deck-box">
      <div className="deck-label">{label}</div>
      <div className="deck-count">{count}</div>
    </div>
  )
}

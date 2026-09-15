// Single token pile's dot-grid, floated above a specific golem card slot
// (see CenterBoard.jsx) instead of rendered as one shared row.
export default function TokenPile({ pile }) {
  return (
    <div
      className={`token-cluster token-${pile.kind} golem-token-pile`}
      title={`${pile.kind} (value ${pile.value} each): ${pile.count}`}
    >
      <div className="token-dots">
        {Array.from({ length: pile.count }).map((_, i) => (
          <span key={i} className="token-dot" />
        ))}
      </div>
      <span className="token-pile-count">{pile.count}</span>
    </div>
  )
}

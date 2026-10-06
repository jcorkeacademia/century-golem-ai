// Guided TEST rooms only (server/guided.py): the solver's next move, in
// words, above the board — the card/slot/button it refers to is outlined in
// red by Board.jsx's guide-target classes. `guide` is state.guide, which the
// server only ever sends for TEST rooms, so ordinary games never render this.
export default function GuideBanner({ guide }) {
  const { seed, turn, planned_total: total, status, text, note, source, replans } = guide

  let headline
  if (status === 'finished') headline = 'Game over'
  else if (status === 'replanning') headline = 'Recalculating the best path from your position…'
  else if (text) headline = text
  else headline = 'No planned move'

  return (
    <div className={`guide-banner guide-${status}`} role="status">
      <div className="guide-meta">
        <span className="guide-tag">Guided · seed {seed}</span>
        {status !== 'finished' && (
          <span>
            Turn {turn}
            {total ? ` of ${total}` : ''}
          </span>
        )}
        {replans > 0 && <span>re-planned {replans}×</span>}
      </div>
      <div className="guide-text">{headline}</div>
      {note && <div className="guide-note">{note}</div>}
      <div className="guide-source">{source}</div>
    </div>
  )
}

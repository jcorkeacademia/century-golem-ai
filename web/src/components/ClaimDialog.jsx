import { useEffect } from 'react'
import GolemCard from './GolemCard.jsx'
import CaravanGrid from './CaravanGrid.jsx'
import { applyTrade } from '../trade.js'

const NO_GAIN = { Y: 0, G: 0, B: 0, M: 0 }

// Centered dialog for claiming a golem — same family as TradeDialog.jsx
// (dialog-scrim, dialog-lbl, dialog-confirm) but a single centered column
// rather than a two-column layout: there's no repeat-count picker (a
// golem's cost is fixed, nothing to choose), and the card's own art
// already prints its name/cost/points, so nothing here repeats that as
// text — just the card, then what the caravan looks like after paying,
// then Confirm. Board.jsx only ever mounts this when the cost is actually
// affordable (see handleStartClaim), so there's no need to show a shortfall.
export default function ClaimDialog({ card, caravan, onConfirm, onCancel }) {
  useEffect(() => {
    function onKeyDown(e) {
      if (e.key === 'Escape') onCancel()
      else if (e.key === 'Enter') onConfirm()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onCancel, onConfirm])

  const resulting = applyTrade(caravan, card.cost, NO_GAIN, 1)
  const resultingTotal = resulting.Y + resulting.G + resulting.B + resulting.M

  return (
    <div className="dialog-scrim" onClick={onCancel}>
      <div className="claim-dialog" onClick={(e) => e.stopPropagation()}>
        <span className="dialog-lbl">Claiming</span>
        <div className="claim-dialog-card">
          <GolemCard card={card} />
        </div>

        <div className="trade-dialog-caravan">
          <div className="trade-dialog-caravan-header">
            <span className="dialog-lbl">Updated caravan</span>
            <span className="dialog-caravan-count">{resultingTotal} / 10</span>
          </div>
          <CaravanGrid bundle={resulting} />
        </div>

        <button type="button" className="dialog-confirm" onClick={onConfirm}>
          Confirm
        </button>
      </div>
    </div>
  )
}

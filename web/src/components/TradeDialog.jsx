import { useEffect, useState } from 'react'
import MerchantCard from './MerchantCard.jsx'
import CaravanGrid from './CaravanGrid.jsx'
import { maxAffordableTradeTimes, tradeCeiling, applyTrade } from '../trade.js'

// Centred dialog replacing the old bottom-strip trade prompt — see
// trade_dialog_prompt.md. Board.jsx only ever mounts this when at least 2
// repeat counts are legal; exactly 1 legal count is sent immediately
// without opening anything (see handleStartTrade), and 0 means the card
// wasn't actually playable, so this component can assume ceiling >= 2.
export default function TradeDialog({ card, caravan, onConfirm, onCancel }) {
  const cost = card.cost
  const gain = card.trade_gain
  const maxTimes = maxAffordableTradeTimes(caravan, cost)
  const ceiling = Math.max(tradeCeiling(cost), maxTimes)
  const [times, setTimes] = useState(maxTimes)

  function pick(n) {
    if (n < 1 || n > maxTimes) return
    setTimes(n)
  }

  useEffect(() => {
    function onKeyDown(e) {
      if (e.key === 'Escape') {
        onCancel()
        return
      }
      if (e.key === 'Enter') {
        onConfirm(times)
        return
      }
      const n = Number(e.key)
      if (Number.isInteger(n) && n >= 1 && n <= ceiling) pick(n)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [times, maxTimes, ceiling])

  const resulting = applyTrade(caravan, cost, gain, times)
  const resultingTotal = resulting.Y + resulting.G + resulting.B + resulting.M

  return (
    <div className="dialog-scrim" onClick={onCancel}>
      <div className="trade-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="dialog-top">
          <div className="trade-dialog-card">
            <MerchantCard card={card} />
          </div>
          <div className="trade-dialog-right">
            <span className="dialog-lbl">Conversions</span>
            <div className="conversion-grid">
              {Array.from({ length: ceiling }, (_, i) => i + 1).map((n, i, arr) => {
                const affordable = n <= maxTimes
                const isLastOdd = i === arr.length - 1 && arr.length % 2 === 1
                return (
                  <button
                    key={n}
                    type="button"
                    className={`conversion-btn${n === times ? ' selected' : ''}${isLastOdd ? ' span-full' : ''}`}
                    disabled={!affordable}
                    onClick={() => pick(n)}
                  >
                    {n}
                  </button>
                )
              })}
            </div>
          </div>
        </div>

        <div className="dialog-bottom">
          <div className="trade-dialog-caravan">
            <div className="trade-dialog-caravan-header">
              <span className="dialog-lbl">Updated caravan</span>
              <span className="dialog-caravan-count">{resultingTotal} / 10</span>
            </div>
            <CaravanGrid bundle={resulting} />
          </div>
          <button type="button" className="dialog-confirm" onClick={() => onConfirm(times)}>
            Confirm
          </button>
        </div>
      </div>
    </div>
  )
}

import { useEffect } from 'react'
import GolemCard from './GolemCard.jsx'

// A claimed golem's face is otherwise only ever shown small (60px in your
// own Golems box, similarly tiny in the detail overlay) — this is just a
// closer look, not a decision: no Confirm, nothing sent anywhere, dismiss
// however you like (scrim click, Escape, the × button).
export default function GolemZoomOverlay({ card, onClose }) {
  useEffect(() => {
    function onKeyDown(e) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  return (
    <div className="dialog-scrim" onClick={onClose}>
      <div className="golem-zoom-frame" onClick={(e) => e.stopPropagation()}>
        <button type="button" className="golem-zoom-close" onClick={onClose} aria-label="Close">
          ×
        </button>
        <div className="golem-zoom-card">
          <GolemCard card={card} title={card.name} />
        </div>
        <div className="golem-zoom-name">{card.name}</div>
      </div>
    </div>
  )
}

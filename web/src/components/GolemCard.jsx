import { SERVER_HTTP_URL } from '../config.js'

// Cost is already baked into the art (crystal row along the bottom of the
// rendered PNG — see CARD_ART_HANDOVER.md §6), so no separate CSS overlay
// duplicates it here.
export default function GolemCard({ card, onClick, showPoints = true, title }) {
  const clickable = typeof onClick === 'function'
  return (
    <div
      className={`card-visual golem-card${clickable ? ' clickable' : ''}`}
      onClick={onClick}
      title={title ?? (clickable ? `Claim ${card.name}` : card.name)}
    >
      <div className={`card-image-slot${card.art ? ' has-art' : ''}`}>
        {card.art && <img className="card-art-img" src={SERVER_HTTP_URL + card.art} alt="" />}
      </div>

      {showPoints && (
        <div className="card-overlay-topright">
          <span className="points-badge">{card.points}</span>
        </div>
      )}
    </div>
  )
}

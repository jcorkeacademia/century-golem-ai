import { SERVER_HTTP_URL } from '../config.js'
import { GolemFace } from './CardFace.jsx'

// With art, the cost is baked into the image (crystal row along the bottom
// of the rendered PNG — see docs/CARD_ART_HANDOVER.md §6). Without art the
// face is drawn from the card's data (CardFace.jsx).
export default function GolemCard({ card, onClick, showPoints = true, title }) {
  const clickable = typeof onClick === 'function'
  return (
    <div
      className={`card-visual golem-card${clickable ? ' clickable' : ''}`}
      onClick={onClick}
      title={title ?? (clickable ? `Claim ${card.name}` : card.name)}
    >
      <div className={`card-image-slot${card.art ? ' has-art' : ''}`}>
        {card.art
          ? <img className="card-art-img" src={SERVER_HTTP_URL + card.art} alt="" />
          : <GolemFace card={card} />}
      </div>

      {showPoints && (
        <div className="card-overlay-topright">
          <span className="points-badge">{card.points}</span>
        </div>
      )}
    </div>
  )
}

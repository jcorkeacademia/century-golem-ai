import { useState } from 'react'
import MerchantCard from './MerchantCard.jsx'
import CaravanGrid from './CaravanGrid.jsx'
import GolemCard from './GolemCard.jsx'
import GolemDots from './GolemDots.jsx'
import GolemZoomOverlay from './GolemZoomOverlay.jsx'
import { ordinal } from '../ordinal.js'

// Full-size, read-only blow-up of an opponent's panel, opened by clicking
// their (cramped) compact panel — see OpponentPanel.jsx. Purely a viewer:
// no click handlers on the cards, no server traffic, closes on backdrop
// click or the × button without affecting turn order. Carries everything
// the compact panel deliberately leaves out: the full hand/played piles,
// each claimed golem card face-up, and the raw copper/silver token counts.
export default function PlayerDetailOverlay({ player, seatLabel, winTarget, onClose }) {
  // Same closer-look golem zoom as MePanel's own Golems box — local state is
  // fine here too, it's just a viewer with nothing to coordinate.
  const [zoomedGolem, setZoomedGolem] = useState(null)
  const lastPlayedIndex = player.played.length - 1

  return (
    <div className="player-detail-backdrop" onClick={onClose}>
      <div className="player-detail-modal" onClick={(e) => e.stopPropagation()}>
        <div className="player-detail-header">
          <span className="seat-tag">{seatLabel}</span>
          <span className="player-detail-name">{player.name}</span>
          {/* Seat order = turn order — see OpponentPanel.jsx's own badge
              for why this is worth showing now that seating is shuffled. */}
          <span className="first-player-marker" title="Turn order">
            {ordinal(player.seat + 1)}
          </span>
          <button className="player-detail-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        <span className="detail-section-label">Caravan</span>
        <CaravanGrid bundle={player.caravan} />

        <div className="player-detail-cards">
          <div className="card-col">
            <span className="detail-section-label">Playable</span>
            <div className="card-row">
              {player.hand.map((card) => (
                <MerchantCard key={card.hand_index} card={card} showTimesPlayed />
              ))}
            </div>
          </div>
          <div className="card-col">
            <span className="detail-section-label">Played</span>
            <div className="card-row">
              {player.played.map((card, i) => (
                <div
                  key={i}
                  className={i === lastPlayedIndex ? 'last-played-wrap' : undefined}
                  title={i === lastPlayedIndex ? 'Last card played' : undefined}
                >
                  <MerchantCard card={card} showTimesPlayed />
                  {i === lastPlayedIndex && <span className="last-played-tag">Last</span>}
                </div>
              ))}
            </div>
          </div>
          <div className="card-col">
            <span className="detail-section-label">Golems</span>
            <div className="card-row">
              {player.golems.length > 0 ? (
                player.golems.map((card, i) => (
                  <GolemCard key={i} card={card} onClick={() => setZoomedGolem(card)} title={`View ${card.name}`} />
                ))
              ) : (
                <span className="empty-hint">None yet</span>
              )}
            </div>
          </div>
        </div>

        <div className="player-detail-stats">
          <span className="token-counts-readout">
            <span className="token-count token-copper">
              <span className="token-dot" /> {player.tokens.copper}
            </span>
            <span className="token-count token-silver">
              <span className="token-dot" /> {player.tokens.silver}
            </span>
          </span>
          {/* Golem points, not total score — see MePanel.jsx for why. */}
          <span className="points-readout">Points: {player.golem_points}</span>
          <GolemDots count={player.golem_count} total={winTarget} />
        </div>
      </div>
      {zoomedGolem && <GolemZoomOverlay card={zoomedGolem} onClose={() => setZoomedGolem(null)} />}
    </div>
  )
}

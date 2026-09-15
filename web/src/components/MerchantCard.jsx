import CrystalDots from './CrystalDots.jsx'
import { crystalIconUrl } from '../crystalIcons.js'
import { SERVER_HTTP_URL } from '../config.js'

// Cost/gain is already baked into the art (the cream effect strip in the
// top-left corner of the rendered PNG — see CARD_ART_HANDOVER.md §6), so no
// separate CSS overlay duplicates it. The name/code (e.g. "1G1Y->1M") is
// redundant with that same baked-in strip, so it isn't shown either — it
// still rides along as the `title` tooltip for hover/debugging.
//
// `stagedColor`/`onUnstage` (optional): a crystal the current player just
// dragged onto this card, not yet confirmed (see CenterBoard.jsx). It's
// rendered in the SAME row as the card's already-confirmed crystals rather
// than as a separate centered overlay — two overlays independently centered
// on the same card would sit exactly on top of each other, which used to
// make an already-paid card look like it only ever had one crystal on it
// no matter how many were really there. Folding it into one row keeps the
// count honest for the player doing the staging, not just everyone else.
//
// `showTimesPlayed` (optional): opts into the "played ×N" corner badge
// (same spot/style as a golem card's own points-badge) from `card.times_played`
// — the server only ever fills that field in once the game is over
// (see serialize.py's game_to_state), so passing this everywhere would be a
// harmless no-op during live play regardless, but PlayerDetailOverlay is the
// only caller that actually opts in: the badge is meant to be something you
// go looking for by opening a player's card at game end, not something that
// pops up unasked on the live board once the game happens to end under it.
export default function MerchantCard({
  card,
  onClick,
  showCrystalsOnCard = false,
  compact = false,
  stagedColor,
  onUnstage,
  showTimesPlayed = false,
}) {
  const clickable = typeof onClick === 'function'
  const hasOnCardCrystals = showCrystalsOnCard && card.crystals_on_card &&
    ['Y', 'G', 'B', 'M'].some((k) => (card.crystals_on_card[k] ?? 0) > 0)
  const hasOverlay = hasOnCardCrystals || Boolean(stagedColor)
  const timesPlayed = showTimesPlayed ? card.times_played : null
  const showBadge = typeof timesPlayed === 'number' && timesPlayed >= 1

  return (
    <div
      className={`card-visual merchant-card kind-${card.kind}${clickable ? ' clickable' : ''}${compact ? ' compact' : ''}`}
      onClick={clickable ? onClick : undefined}
      title={card.name}
    >
      {hasOverlay && (
        <div className="on-card-crystals">
          {hasOnCardCrystals && <CrystalDots bundle={card.crystals_on_card} />}
          {stagedColor && (
            <button
              type="button"
              className="staged-dot"
              title="Click to take this crystal back"
              onClick={(e) => {
                e.stopPropagation()
                onUnstage?.()
              }}
            >
              <img className="gem-icon" src={crystalIconUrl(stagedColor)} alt="" draggable={false} />
            </button>
          )}
        </div>
      )}

      {showBadge && (
        <div className="card-overlay-topright">
          <span className="points-badge" title={`Played ${timesPlayed} time${timesPlayed === 1 ? '' : 's'} this game`}>
            ×{timesPlayed}
          </span>
        </div>
      )}

      <div className={`card-image-slot${card.art ? ' has-art' : ''}`}>
        {card.art && <img className="card-art-img" src={SERVER_HTTP_URL + card.art} alt="" />}
      </div>
    </div>
  )
}

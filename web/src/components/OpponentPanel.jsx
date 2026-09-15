import CaravanGrid from './CaravanGrid.jsx'
import MerchantCard from './MerchantCard.jsx'
import GolemCard from './GolemCard.jsx'
import AvatarGlyph from './AvatarGlyph.jsx'
import TurnClock from './TurnClock.jsx'
import { avatarById } from '../avatars.js'
import { ordinal } from '../ordinal.js'

const PLAYED_CAP = 4

// Read-only — only the current seat (rendered via MePanel) can act, so
// opponents render a compact summary with no click handlers of their own;
// the one exception is the panel itself, which opens a bigger read-only view
// (see PlayerDetailOverlay) carrying the full hand detail this compact
// panel still leaves out.
export default function OpponentPanel({ player, avatarId, isCurrent, winTarget, onExpand, turnClock }) {
  const lastPlayed = player.played[player.played.length - 1]
  const avatar = avatarById(avatarId)

  const playedShown = player.played.slice(0, PLAYED_CAP)
  const playedOverflow = player.played.length - PLAYED_CAP
  const emptyGolemSlots = Math.max(0, winTarget - player.golems.length)

  return (
    <div
      className={isCurrent ? 'opponent-panel current-turn' : 'opponent-panel'}
      onClick={onExpand}
      title={`View ${player.name}'s hand`}
    >
      <div className="opponent-turnbar" />
      <div className="opponent-body">
        <div className="opponent-head">
          <div className="opponent-who">
            <div className="opponent-avatar-wrap">
              <div className="opponent-avatar" style={{ '--hue': avatar.hue }}>
                <AvatarGlyph avatar={avatar} className="opponent-avatar-glyph" />
              </div>
              {/* Seat order = turn order (seat 0 goes first, seat 1
                  second, ...) — worth spelling out now that solo mode
                  shuffles who actually sits where each game (main.py's
                  _run_solo), so "who goes when" isn't guessable from seat
                  position on screen alone. */}
              <span className="opponent-first-badge" title="Turn order">
                {ordinal(player.seat + 1)}
              </span>
            </div>
            <div className="opponent-name">{player.name}</div>
            <div className="opponent-state">{isCurrent ? 'Their turn' : 'Waiting'}</div>
          </div>

          <div className="opponent-lastcard">
            <div className="opponent-cardface">
              {lastPlayed ? (
                <MerchantCard key={player.played.length} card={lastPlayed} />
              ) : (
                <div className="opponent-cardface-empty" />
              )}
            </div>
            <div className="opponent-cardlabel">last played</div>
          </div>
        </div>

        <div className="opponent-meta">
          <span>hand {player.hand.length}</span>
        </div>
        <CaravanGrid bundle={player.caravan} />

        <div className="opponent-meta">
          <span>golems</span>
          <span>
            {player.golems.length} / {winTarget}
          </span>
        </div>
        <div className="opponent-golem-tiles">
          {player.golems.map((g, i) => (
            <GolemCard key={i} card={g} />
          ))}
          {Array.from({ length: emptyGolemSlots }).map((_, i) => (
            <div key={`empty-${i}`} className="golem-mini-tile empty" />
          ))}
        </div>

        <div className="opponent-meta">
          <span>played</span>
          <span>{player.played.length}</span>
        </div>
        <div className="opponent-played-tiles">
          {playedShown.map((card, i) => (
            <MerchantCard key={i} card={card} />
          ))}
          {playedOverflow > 0 && <div className="opponent-played-overflow">+{playedOverflow}</div>}
        </div>

        <div className="opponent-points-foot">
          <div>
            <div className="opponent-lbl">points</div>
            {/* Golem points, not total score — non-yellow crystals only
                count toward score at actual game end, not live off caravan
                state. */}
            <div className="opponent-points">{player.golem_points}</div>
          </div>
          {/* Bottom-right corner, quiet — accumulated thinking time, not a
              chess clock you're racing against (see TurnClock.jsx). */}
          {turnClock && <TurnClock {...turnClock} />}
        </div>
      </div>
    </div>
  )
}

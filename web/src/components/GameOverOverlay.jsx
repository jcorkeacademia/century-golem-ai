import { avatarById } from '../avatars.js'
import AvatarGlyph from './AvatarGlyph.jsx'

// Century has no natural "the board freezes here" cue of its own — without
// this, the last move just stops responding (every action becomes
// IllegalAction("game is over") the instant state.game_over flips true, see
// century_engine.apply_action) and nothing on screen ever explains why or
// says who won. Board.jsx mounts this the same way it mounts TradeDialog:
// a scrim overlay, dismissible, over the frozen final board underneath —
// and Board.jsx's own floating "View results" button (.gameover-reopen)
// brings it back after it's been closed, so closing it to look at the board
// is never a one-way trip.
// `actions` (optional): buttons shown in place of "View final board" — only
// the tutorial passes them (Board.jsx), for its "what next" choices.
export default function GameOverOverlay({ players, winner, resolveAvatar, onClose, onSelectPlayer, actions }) {
  const ranked = [...players].sort((a, b) => b.score - a.score)
  const winnerPlayer = players.find((p) => p.name === winner)
  const winnerAvatar = winnerPlayer && avatarById(resolveAvatar(winnerPlayer))

  return (
    <div className="dialog-scrim" onClick={onClose}>
      <div className="gameover-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="gameover-title">Final Tally</div>

        {/* The winner's own avatar in place of a generic trophy/crest — the
            actual person who won is a better focal point than heraldry. */}
        {winnerAvatar && (
          <div className="gameover-winner-avatar" style={{ '--hue': winnerAvatar.hue }}>
            <AvatarGlyph avatar={winnerAvatar} className="gameover-winner-avatar-glyph" />
          </div>
        )}
        <div className="gameover-subtitle">{winner ? `${winner} wins!` : 'No winner'}</div>

        <div className="gameover-table">
          {ranked.map((p, i) => {
            const avatar = avatarById(resolveAvatar(p))
            const isWinner = p.name === winner
            return (
              // Same read-only detail card OpponentPanel opens mid-game
              // (PlayerDetailOverlay, via Board.jsx's expandedSeat) — the
              // final tally is exactly when you want to go see what
              // someone's whole hand/played pile/golems actually looked
              // like, not just their score.
              <div
                key={p.seat}
                className={isWinner ? 'gameover-row gameover-row-winner' : 'gameover-row'}
                onClick={() => onSelectPlayer?.(p.seat)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') onSelectPlayer?.(p.seat)
                }}
              >
                <span className="gameover-rank">{i + 1}</span>
                <div className="gameover-avatar" style={{ '--hue': avatar.hue }}>
                  <AvatarGlyph avatar={avatar} className="gameover-avatar-glyph" />
                </div>
                <span className="gameover-name">
                  {p.name}
                  {isWinner && (
                    <svg className="gameover-crown" viewBox="0 0 24 24" aria-hidden="true" title="Winner">
                      <path d="M3 8l4.5 3.2L12 4l4.5 7.2L21 8l-2 10H5z" />
                    </svg>
                  )}
                </span>
                {/* Same points-badge circle a golem card's own corner uses,
                    and the same token-dot the Golems box uses — reusing
                    both here instead of "N golem" / "N tok" text ties this
                    screen's iconography back to the rest of the board. */}
                <span className="gameover-stat" title="Golem points">
                  <span className="points-badge">{p.golem_points}</span>
                </span>
                <span className="gameover-stat" title="Tokens">
                  <span className="gameover-token-dot" /> {p.tokens.copper + p.tokens.silver}
                </span>
                <span className="gameover-score" title="Total score">
                  {p.score}
                </span>
              </div>
            )
          })}
        </div>

        {actions ? (
          <div className="gameover-actions">
            {actions.map((a) => (
              <button
                key={a.label}
                type="button"
                className="gameover-close"
                onClick={a.onClick}
                disabled={a.disabled}
                title={a.title}
              >
                {a.label}
              </button>
            ))}
          </div>
        ) : (
          <button type="button" className="gameover-close" onClick={onClose}>
            View final board
          </button>
        )}
      </div>
    </div>
  )
}

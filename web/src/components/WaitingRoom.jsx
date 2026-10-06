import { avatarById } from '../avatars.js'
import AvatarGlyph from './AvatarGlyph.jsx'

const MAX_SEATS = 5

// Shown once a `lobby` message has arrived and before the game actually
// starts (docs/CONTRACT.md 1d) — lists whoever has joined so far and updates
// live as people come and go, since every connected socket gets a fresh
// `lobby` broadcast on any change (see main.py's _broadcast_lobby).
export default function WaitingRoom({ lobby, lastError, onStart, onDismissError, onLeave }) {
  const isHost = lobby.you === lobby.host
  const canStart = lobby.seats.length >= 2

  return (
    <div className="join-screen">
      <div className="join-card">
        <div className="join-eyebrow">room {lobby.room}</div>
        <h1 className="join-heading">Waiting for players</h1>

        <div className="join-field">
          <div className="waiting-count">
            {lobby.seats.length} / {MAX_SEATS} joined
          </div>
          <ul className="waiting-seats">
            {lobby.seats.map((seat) => {
              const avatar = avatarById(seat.avatar)
              return (
                <li key={seat.seat} className="waiting-seat">
                  <div className="waiting-seat-avatar" style={{ '--hue': avatar.hue }}>
                    <AvatarGlyph avatar={avatar} className="waiting-seat-avatar-glyph" />
                  </div>
                  <span className={seat.connected ? 'waiting-seat-dot' : 'waiting-seat-dot waiting-seat-dot-off'} />
                  <span className="waiting-seat-name">{seat.name}</span>
                  {seat.seat === lobby.you && <span className="waiting-seat-you">you</span>}
                  {seat.seat === lobby.host && <span className="waiting-seat-host">host</span>}
                </li>
              )
            })}
          </ul>
          {lastError && (
            <div className="join-error">
              {lastError.message}
              <button className="dismiss-error" onClick={onDismissError}>
                ×
              </button>
            </div>
          )}
        </div>

        <div className="join-foot">
          {isHost ? (
            <>
              <span className="join-note">
                {canStart ? 'Ready when you are.' : 'Need at least 2 players to start.'}
              </span>
              <button type="button" className="join-btn" disabled={!canStart} onClick={onStart}>
                Start game
              </button>
            </>
          ) : (
            <span className="join-note">Waiting for the host to start the game…</span>
          )}
        </div>

        {/* An accidental "Create room" (meant to hit Practice solo instead,
            say) used to be a dead end — no way back to StartScreen short of
            closing the tab, and a refresh just reconnects to this same
            lobby (session persists across reloads on purpose — see
            App.jsx). This is the escape hatch. */}
        <button type="button" className="join-btn join-btn-secondary waiting-leave-btn" onClick={onLeave}>
          Leave room
        </button>
      </div>
    </div>
  )
}

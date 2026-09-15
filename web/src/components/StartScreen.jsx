import { useEffect, useState } from 'react'
import { AVATARS } from '../avatars.js'
import AvatarGlyph from './AvatarGlyph.jsx'

const CHECK_PATH = 'M5 12.5 10 17.5 19 7'

// Replaces the old fixed-roster JoinScreen — real multiplayer means the
// roster isn't known ahead of time, so there's no "seated with Bob, Carol,
// ..." to show, but the avatar picker itself carries straight over: name +
// avatar, then either CREATE (room code left blank — App.jsx generates one)
// or JOIN (a typed code). The choice travels to the server as part of
// connecting (CONTRACT.md's `?avatar=`) and from there is just another
// field on that seat, same as `name` — every other client sees it too.
export default function StartScreen({ initialError, onSubmit, onSoloSubmit }) {
  const [name, setName] = useState('')
  const [roomCode, setRoomCode] = useState('')
  const [avatarId, setAvatarId] = useState(null)
  const [error, setError] = useState(initialError || null)
  const [soloBots, setSoloBots] = useState(4)

  const trimmedCode = roomCode.trim().toUpperCase()
  const canSubmit = name.trim().length > 0 && avatarId !== null

  function handleSubmit() {
    const trimmed = name.trim()
    if (!trimmed) {
      setError('Enter a name.')
      return
    }
    if (!avatarId) {
      setError('Choose an avatar.')
      return
    }
    onSubmit(trimmed, trimmedCode || null, avatarId)
  }

  // Practice mode (CLAUDE.md build-order step 3, brought back as an actual
  // toggle): control every seat yourself, no one else to invite, so it
  // skips the room-code field entirely — same name/avatar validation as a
  // real join, just routed to a solo room instead (see App.jsx).
  function handleSoloSubmit() {
    const trimmed = name.trim()
    if (!trimmed) {
      setError('Enter a name.')
      return
    }
    if (!avatarId) {
      setError('Choose an avatar.')
      return
    }
    onSoloSubmit(trimmed, avatarId, soloBots + 1)
  }

  // Ten real photos are a lot heavier than the old inline-SVG glyphs — kick
  // all ten off the moment this screen mounts so the grid below is already
  // warm by the time it paints, instead of each circle popping in as its
  // own lazy <img> request resolves.
  useEffect(() => {
    for (const av of AVATARS) {
      const img = new Image()
      img.src = av.src
    }
  }, [])

  return (
    <div className="join-screen">
      <div className="join-card">
        <div className="join-eyebrow">century: golem edition</div>
        <h1 className="join-heading">{trimmedCode ? 'Join a room' : 'Hop in'}</h1>

        <div className="join-field">
          <label className="join-label" htmlFor="join-name">
            Name
          </label>
          <div className="join-inputrow">
            <input
              id="join-name"
              className="join-input"
              type="text"
              maxLength={14}
              autoComplete="off"
              value={name}
              onChange={(e) => {
                setName(e.target.value)
                setError(null)
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && canSubmit) handleSubmit()
              }}
            />
            <span className="join-counter">{name.length} / 14</span>
          </div>
        </div>

        <div className="join-field">
          <label className="join-label" htmlFor="join-room">
            Room code
          </label>
          <input
            id="join-room"
            className="join-input"
            type="text"
            maxLength={8}
            autoComplete="off"
            style={{ textTransform: 'uppercase' }}
            value={roomCode}
            onChange={(e) => {
              setRoomCode(e.target.value)
              setError(null)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && canSubmit) handleSubmit()
            }}
          />
        </div>

        <div className="join-field" style={{ marginBottom: 0 }}>
          <label className="join-label" style={{ marginBottom: 12 }}>
            Avatars
          </label>
          <div className="join-grid">
            {AVATARS.map((av) => {
              const selected = avatarId === av.id
              return (
                <div className="join-avwrap" key={av.id}>
                  <button
                    type="button"
                    className={`join-av${selected ? ' join-av-selected' : ''}`}
                    style={{ '--hue': av.hue }}
                    aria-label={`Choose ${av.name}`}
                    onClick={() => {
                      setAvatarId(av.id)
                      setError(null)
                    }}
                  >
                    <AvatarGlyph avatar={av} className="join-glyph" />
                    {selected && (
                      <span className="join-check" aria-hidden="true">
                        <svg viewBox="0 0 24 24">
                          <path d={CHECK_PATH} fill="none" stroke="#FFF" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      </span>
                    )}
                  </button>
                </div>
              )
            })}
          </div>
          {error && <div className="join-error">{error}</div>}
        </div>

        <div className="join-foot">
          <button type="button" className="join-btn" disabled={!canSubmit} onClick={handleSubmit}>
            {trimmedCode ? 'Join room' : 'Create room'}
          </button>
        </div>

        <div className="join-solo">
          <div className="join-solo-divider">
            <span>or</span>
          </div>
          <div className="join-solo-row">
            <div className="join-solo-controls">
              <label className="join-solo-count-label" htmlFor="join-solo-count">
                Bots
              </label>
              <select
                id="join-solo-count"
                className="join-solo-count"
                value={soloBots}
                onChange={(e) => setSoloBots(Number(e.target.value))}
              >
                {[1, 2, 3, 4].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
              <button type="button" className="join-btn join-btn-secondary" disabled={!canSubmit} onClick={handleSoloSubmit}>
                Practice solo
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

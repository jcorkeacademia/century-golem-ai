import { useEffect, useState } from 'react'
import { useGame } from './useGame.js'
import Board from './components/Board.jsx'
import StartScreen from './components/StartScreen.jsx'
import WaitingRoom from './components/WaitingRoom.jsx'
import { SERVER_URL } from './config.js'
import { randomRoomCode } from './roomCode.js'

// Survives a refresh: without this, reloading the tab mid-game dropped you
// back to StartScreen even though the server-side Room/Game was still very
// much alive (rooms.py never deletes a started room just because its
// socket dropped — see main.py's ws_room/_run_solo finally blocks, which a
// reconnect with the same name+room_id/room_id just reattaches to). Only
// the fields needed to reconnect are kept — never `attempt`, which exists
// purely to force a fresh connection and would be stale the moment it's
// read back.
const SESSION_KEY = 'century.session'

function loadStoredSession() {
  try {
    const raw = localStorage.getItem(SESSION_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed.name !== 'string' || typeof parsed.roomId !== 'string') return null
    return { ...parsed, attempt: 0 }
  } catch {
    return null
  }
}

function storeSession(session) {
  try {
    if (!session) {
      localStorage.removeItem(SESSION_KEY)
      return
    }
    const { name, roomId, avatarId, solo, playerCount } = session
    localStorage.setItem(SESSION_KEY, JSON.stringify({ name, roomId, avatarId, solo, playerCount }))
  } catch {
    // Storage unavailable (private browsing, quota, etc.) — a refresh just
    // won't resume; nothing here needs to crash over it.
  }
}

// Real multiplayer: one browser opens exactly one socket, for its own seat
// (see connection.js/useGame.js). The room itself starts empty and fills up
// as people join by name — see server/main.py's _attach/_broadcast_lobby —
// so this component is a small state machine over what's arrived so far:
// no session yet -> StartScreen; session but rejected before ever reaching
// a room -> StartScreen again with the error shown; `lobby` arrived ->
// WaitingRoom; `state` arrived -> Board.
export default function App() {
  const [session, setSession] = useState(loadStoredSession) // { name, roomId, avatarId, solo, playerCount, attempt }

  const game = useGame({
    serverUrl: SERVER_URL,
    roomId: session?.roomId,
    name: session?.name,
    avatarId: session?.avatarId,
    solo: session?.solo,
    playerCount: session?.playerCount,
    attempt: session?.attempt,
    enabled: session !== null,
  })

  function handleSubmit(name, roomCode, avatarId) {
    setSession((prev) => {
      const next = { name, roomId: roomCode || randomRoomCode(), avatarId, solo: false, attempt: (prev?.attempt || 0) + 1 }
      storeSession(next)
      return next
    })
  }

  // Practice mode (StartScreen's "Practice solo" toggle): always a brand
  // new room, never a code someone typed in, since there's no one else to
  // share it with.
  function handleSoloSubmit(name, avatarId, playerCount) {
    setSession((prev) => {
      const next = { name, roomId: randomRoomCode(), avatarId, solo: true, playerCount, attempt: (prev?.attempt || 0) + 1 }
      storeSession(next)
      return next
    })
  }

  // The only way back to StartScreen once a session is stored — otherwise
  // a refresh would just reconnect you to the same room forever. Board.jsx
  // surfaces this as a small "Leave game" control.
  function handleLeave() {
    storeSession(null)
    setSession(null)
  }

  const rejectedBeforeRoom = session && !game.state && !game.lobby && game.lastError

  // A stored session that the server won't honor any more (bad name, full
  // room, already started without us, etc.) would otherwise keep coming
  // back on every refresh — clear it so the next attempt starts clean.
  useEffect(() => {
    if (rejectedBeforeRoom) storeSession(null)
  }, [rejectedBeforeRoom])

  // Rejected before ever getting a lobby or game state (bad name, full
  // room, already started, etc.) — let them fix it and try again rather
  // than getting stuck on a dead connection.
  if (rejectedBeforeRoom) {
    return <StartScreen initialError={game.lastError.message} onSubmit={handleSubmit} onSoloSubmit={handleSoloSubmit} />
  }

  if (!session) {
    return <StartScreen onSubmit={handleSubmit} onSoloSubmit={handleSoloSubmit} />
  }

  if (game.state) {
    return <Board game={game} onLeave={handleLeave} />
  }

  if (game.lobby) {
    return (
      <WaitingRoom
        lobby={game.lobby}
        lastError={game.lastError}
        onStart={game.sendStart}
        onDismissError={game.clearError}
        onLeave={handleLeave}
      />
    )
  }

  return (
    <div className="connecting-screen">
      <h1>Century: Golem Edition</h1>
      <p>
        Connecting to <code>{SERVER_URL}</code> — room <code>{session.roomId}</code>…
      </p>
      <button type="button" className="connecting-leave-btn" onClick={handleLeave}>
        Cancel
      </button>
    </div>
  )
}

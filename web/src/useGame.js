import { useEffect, useRef, useState, useCallback } from 'react'
import { createGameConnection } from './connection.js'

// One socket, for this browser's own seat (see connection.js). `state` is
// the full post-game-start snapshot (docs/CONTRACT.md 1a, never diffed); `lobby`
// is the pre-start seat list (1d) — the caller renders one or the other
// depending on which has arrived. `sendAction` no longer has to pick a
// socket by seat (there's only ever the one), so a click made on the wrong
// turn just rides this same socket to the server and comes back
// `not_your_turn`, same as any other rejected action.
export function useGame({ serverUrl, roomId, name, avatarId, solo = false, playerCount, difficulty, tutorial = false, attempt = 0, enabled = true }) {
  const [state, setState] = useState(null)
  // performance.now() the instant each `state` lands — TurnClock.jsx adds
  // its own elapsed-since-then on top of the server's last reported figure,
  // so the currently-acting seat's clock visibly ticks between broadcasts
  // instead of only updating in the discrete jumps a fresh state arrives in.
  const [stateReceivedAt, setStateReceivedAt] = useState(0)
  const [lobby, setLobby] = useState(null)
  const [status, setStatus] = useState('connecting')
  const [lastError, setLastError] = useState(null)
  const connRef = useRef(null)

  // `enabled` lets a caller construct this hook before it knows the room/name
  // (e.g. while the start screen is still up) without opening a socket yet —
  // hooks can't be called conditionally, so this is the no-op-until-ready
  // escape hatch instead.
  useEffect(() => {
    if (!enabled) return undefined
    setState(null)
    setLobby(null)
    setLastError(null)
    const conn = createGameConnection({
      serverUrl,
      roomId,
      name,
      avatarId,
      solo,
      playerCount,
      difficulty,
      tutorial,
      onState: (msg) => {
        setState(msg)
        setStateReceivedAt(performance.now())
      },
      onLobby: setLobby,
      onError: setLastError,
      onStatusChange: setStatus,
    })
    connRef.current = conn
    return () => conn.close()
    // `attempt` isn't used inside — it's here purely so a retry with the
    // exact same name/room (e.g. after a rejected join) still forces a
    // brand new connection instead of being a no-op dependency-wise.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverUrl, roomId, name, avatarId, solo, playerCount, difficulty, tutorial, attempt, enabled])

  const sendAction = useCallback((action) => {
    connRef.current?.send(action)
  }, [])

  const sendStart = useCallback(() => {
    connRef.current?.send({ type: 'start' })
  }, [])

  const clearError = useCallback(() => setLastError(null), [])

  return {
    state,
    stateReceivedAt,
    lobby,
    status,
    sendAction,
    sendStart,
    lastError,
    clearError,
  }
}

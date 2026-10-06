// One WebSocket, for this browser's own seat — per docs/CONTRACT.md, a browser
// never opens more than one connection. The server assigns the seat (the
// next open one, or an existing one this name already holds) based on
// `name` alone; there's no roster to send up front. `avatarId` only
// matters the first time this name joins a room (see docs/CONTRACT.md's
// Connecting note) — a reconnect just carries it along harmlessly.
//
// The socket is kept alive and re-established automatically: tunnels and
// flaky networks drop idle/half-open websockets, and without this a dropped
// client just sat on its last state ("Waiting for other players…") until
// the person refreshed. A reconnect with the same name reclaims the same
// seat and the server resends the current state (main.py's ws_room).

const PING_INTERVAL_MS = 20000
const RETRY_DELAYS_MS = [500, 1000, 2000, 4000]

export function createGameConnection({ serverUrl, roomId, name, avatarId, solo = false, playerCount, difficulty, tutorial = false, onState, onLobby, onError, onStatusChange }) {
  let url = `${serverUrl}/ws/${encodeURIComponent(roomId)}?name=${encodeURIComponent(name)}&avatar=${encodeURIComponent(avatarId)}`
  // Solo/practice mode (main.py's _run_solo): the game starts the instant
  // this socket connects, no lobby round-trip — `players` tells the server
  // how many total seats to fill; you play seat 0, the rest auto-play
  // themselves server-side.
  if (solo) {
    url += `&solo=true&players=${encodeURIComponent(playerCount)}`
    // Omitted rather than defaulted client-side: the server owns the
    // default (bot_policy.DEFAULT_DIFFICULTY) so the two cannot disagree.
    if (difficulty) url += `&difficulty=${encodeURIComponent(difficulty)}`
  }
  // The interactive tutorial (server/tutorial.py): a recorded 2-player game
  // with text at every step, no lobby — see docs/CONTRACT.md's tutorial note.
  if (tutorial) url += '&tutorial=true'

  let ws = null
  let closedByUs = false
  let everConnected = false // got a lobby/state at least once — only then is a drop worth retrying
  let rejected = false // the server sent an error and hung up on purpose (bad name, full room...)
  let retries = 0
  let pingTimer = null
  let retryTimer = null

  function stopPing() {
    clearInterval(pingTimer)
    pingTimer = null
  }

  function connect() {
    ws = new WebSocket(url)
    const sock = ws

    onStatusChange('connecting')
    sock.onopen = () => {
      retries = 0
      onStatusChange('open')
      stopPing()
      pingTimer = setInterval(() => {
        if (sock.readyState === WebSocket.OPEN) sock.send(JSON.stringify({ type: 'ping' }))
      }, PING_INTERVAL_MS)
    }
    sock.onclose = () => {
      stopPing()
      if (sock !== ws) return // a newer socket already replaced this one
      if (closedByUs || rejected || !everConnected) {
        onStatusChange('closed')
        return
      }
      onStatusChange('connecting')
      const delay = RETRY_DELAYS_MS[Math.min(retries, RETRY_DELAYS_MS.length - 1)]
      retries += 1
      retryTimer = setTimeout(connect, delay)
    }
    sock.onmessage = (ev) => {
      let msg
      try {
        msg = JSON.parse(ev.data)
      } catch {
        return
      }
      if (msg.type === 'state') {
        everConnected = true
        onState(msg)
      } else if (msg.type === 'lobby') {
        everConnected = true
        onLobby(msg)
      } else if (msg.type === 'error') {
        // Codes the server sends right before closing on purpose — retrying
        // would just get the same answer.
        if (['name_taken', 'room_full', 'already_started', 'malformed'].includes(msg.code) && !everConnected) rejected = true
        onError(msg)
      }
    }
  }

  connect()

  // Coming back to a backgrounded tab (phones and laptops suspend sockets)
  // is the most common moment for a silent drop — reconnect right away
  // instead of waiting out the retry timer.
  function handleVisible() {
    if (document.visibilityState !== 'visible' || closedByUs || rejected) return
    if (ws && ws.readyState !== WebSocket.OPEN && ws.readyState !== WebSocket.CONNECTING && everConnected) {
      clearTimeout(retryTimer)
      connect()
    }
  }
  document.addEventListener('visibilitychange', handleVisible)

  function send(action) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      onError({
        type: 'error',
        code: 'client_not_connected',
        message: 'socket is not open',
        echo: action,
      })
      return
    }
    ws.send(JSON.stringify(action))
  }

  function close() {
    closedByUs = true
    stopPing()
    clearTimeout(retryTimer)
    document.removeEventListener('visibilitychange', handleVisible)
    if (ws) ws.close()
  }

  return { send, close }
}

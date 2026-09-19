// One WebSocket, for this browser's own seat — per CONTRACT.md, a browser
// never opens more than one connection. The server assigns the seat (the
// next open one, or an existing one this name already holds) based on
// `name` alone; there's no roster to send up front. `avatarId` only
// matters the first time this name joins a room (see CONTRACT.md's
// Connecting note) — a reconnect just carries it along harmlessly.

export function createGameConnection({ serverUrl, roomId, name, avatarId, solo = false, playerCount, difficulty, onState, onLobby, onError, onStatusChange }) {
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
  const ws = new WebSocket(url)

  onStatusChange('connecting')
  ws.onopen = () => onStatusChange('open')
  ws.onclose = () => onStatusChange('closed')
  ws.onmessage = (ev) => {
    let msg
    try {
      msg = JSON.parse(ev.data)
    } catch {
      return
    }
    if (msg.type === 'state') onState(msg)
    else if (msg.type === 'lobby') onLobby(msg)
    else if (msg.type === 'error') onError(msg)
  }

  function send(action) {
    if (ws.readyState !== WebSocket.OPEN) {
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
    ws.close()
  }

  return { send, close }
}

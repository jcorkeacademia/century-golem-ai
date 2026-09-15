// Shared between StartScreen (picking) and the board panels (rendering) so
// an avatar looks identical everywhere it appears. The choice is made once,
// at join time (see StartScreen.jsx), sent to the server, and travels with
// that seat from then on (CONTRACT.md's `avatar` field on `lobby`/`state`)
// — it isn't re-derived client-side. `src` is a public/ path (Vite serves
// web/public/avatars/<id>.png at /avatars/<id>.png with no import needed);
// `name` still exists purely for the aria-label — there's no visible
// caption under the photo any more (see StartScreen.jsx).
export const AVATARS = [
  { id: 'aubin', name: 'aubin', hue: '#D9A441', src: '/avatars/aubin.png' },
  { id: 'matt', name: 'matt', hue: '#C15A3E', src: '/avatars/matt.png' },
  { id: 'excel', name: 'excel', hue: '#5B84C4', src: '/avatars/excel.png' },
  { id: 'justin', name: 'justin', hue: '#5E9E58', src: '/avatars/justin.png' },
  { id: 'firdaus', name: 'firdaus', hue: '#A45FA8', src: '/avatars/firdaus.png' },
  { id: 'andrew', name: 'andrew', hue: '#3FA0A0', src: '/avatars/andrew.png' },
  { id: 'davi', name: 'davi', hue: '#D4708F', src: '/avatars/davi.png' },
  { id: 'gong', name: 'gong', hue: '#8A6F4E', src: '/avatars/gong.png' },
  { id: 'aidan', name: 'aidan', hue: '#7A7FCF', src: '/avatars/aidan.png' },
  { id: 'lyford', name: 'lyford', hue: '#4F6B78', src: '/avatars/lyford.png' },
]

export const AVATAR_BY_ID = Object.fromEntries(AVATARS.map((a) => [a.id, a]))

export function avatarById(id) {
  return AVATAR_BY_ID[id] || AVATARS[0]
}

// Fallback only, for a seat whose chosen avatar somehow isn't known (e.g.
// a room whose `state`/`lobby` predates this field). The normal path is
// `player.avatar` straight off the server — see Board.jsx's resolveAvatar.
export function avatarIdForSeat(seat) {
  return AVATARS[seat % AVATARS.length].id
}

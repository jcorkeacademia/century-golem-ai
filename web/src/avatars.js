// Avatars are coloured letter circles. The original build used photos of
// friends; those stay out of the public repo. To use photos again, drop
// PNGs in web/public/avatars/ and set `src: '/avatars/<id>.png'` below.
//
// Shared between StartScreen (picking) and the board panels (rendering) so
// an avatar looks identical everywhere it appears. The choice is made once,
// at join time (see StartScreen.jsx), sent to the server, and travels with
// that seat from then on (docs/CONTRACT.md's `avatar` field on `lobby`/`state`)
// — it isn't re-derived client-side. `src` is a public/ path (Vite serves
// web/public/avatars/<id>.png at /avatars/<id>.png with no import needed);
// `name` still exists purely for the aria-label — there's no visible
// caption under the photo any more (see StartScreen.jsx).
export const AVATARS = [
  { id: 'amber', name: 'amber', hue: '#D9A441', src: null },
  { id: 'rust', name: 'rust', hue: '#C15A3E', src: null },
  { id: 'sky', name: 'sky', hue: '#5B84C4', src: null },
  { id: 'fern', name: 'fern', hue: '#5E9E58', src: null },
  { id: 'plum', name: 'plum', hue: '#A45FA8', src: null },
  { id: 'teal', name: 'teal', hue: '#3FA0A0', src: null },
  { id: 'rose', name: 'rose', hue: '#D4708F', src: null },
  { id: 'oak', name: 'oak', hue: '#8A6F4E', src: null },
  { id: 'iris', name: 'iris', hue: '#7A7FCF', src: null },
  { id: 'slate', name: 'slate', hue: '#4F6B78', src: null },
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

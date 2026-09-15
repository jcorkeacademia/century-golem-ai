// Excludes I/O/0/1 — characters easy to misread or confuse when a room code
// is read aloud or typed from memory.
const LETTERS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'

export function randomRoomCode(length = 4) {
  let out = ''
  for (let i = 0; i < length; i++) {
    out += LETTERS[Math.floor(Math.random() * LETTERS.length)]
  }
  return out
}

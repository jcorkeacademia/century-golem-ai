import { SERVER_HTTP_URL } from './config.js'

// Same 4 PNGs stamped onto the golem/merchant card art itself — served
// as-is by the server (see docs/CARD_ART_HANDOVER.md §1, server/main.py).
const FILE = { Y: 'yellow', G: 'green', B: 'blue', M: 'magenta' }

export function crystalIconUrl(color) {
  return `${SERVER_HTTP_URL}/static/crystals/${FILE[color]}.png`
}

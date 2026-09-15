// Local dev (default) — leave this as-is unless you're testing with someone
// on another network. To use a Cloudflare quick tunnel instead: replace the
// whole string below with the https:// URL cloudflared printed for your
// backend tunnel (port 8000), changing "https://" to "wss://" and dropping
// any trailing slash — e.g. 'wss://some-random-words.trycloudflare.com'.
// Swap it back to 'ws://localhost:8000' when you're done testing.
export const SERVER_URL = 'ws://localhost:8000'
// Card art (state's "art" field) is a server-relative URL — the WS and HTTP
// origins are the same server, so derive one from the other. This already
// turns a wss:// SERVER_URL into the matching https:// one, no edit needed.
export const SERVER_HTTP_URL = SERVER_URL.replace(/^ws/, 'http')

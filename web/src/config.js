// Where the game server lives. Local dev uses ws://localhost:8000. To play
// with friends on another network, expose the server (e.g. a Cloudflare quick
// tunnel on port 8000) and start the client with
//   VITE_SERVER_URL=wss://<your-tunnel-host> npm run dev
// (https:// -> wss://, no trailing slash).
export const SERVER_URL = import.meta.env.VITE_SERVER_URL || 'ws://localhost:8000'
// Card art (state's "art" field) is a server-relative URL — the WS and HTTP
// origins are the same server, so derive one from the other. This already
// turns a wss:// SERVER_URL into the matching https:// one, no edit needed.
export const SERVER_HTTP_URL = SERVER_URL.replace(/^ws/, 'http')

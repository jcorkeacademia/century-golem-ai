import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Vite normally rejects requests whose Host header isn't localhost (a
    // DNS-rebinding guard) — that blocks a Cloudflare quick tunnel's random
    // *.trycloudflare.com hostname outright. `true` accepts any host; fine
    // for a short-lived test tunnel, not something to leave on for a real
    // deployment.
    allowedHosts: true,
  },
})

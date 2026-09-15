import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './styles.css'

// No React.StrictMode here on purpose: its dev-mode double-invoke of effects
// would open+close+reopen all 5 seat WebSockets on mount, racing the
// server's seat-release (on WebSocketDisconnect) against the immediate
// reconnect and intermittently failing with "no open seat".
ReactDOM.createRoot(document.getElementById('root')).render(
  <App />
)

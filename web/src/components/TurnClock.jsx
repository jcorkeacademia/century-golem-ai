import { useEffect, useState } from 'react'

function formatClock(totalSeconds) {
  const s = Math.max(0, Math.floor(totalSeconds))
  const m = Math.floor(s / 60)
  const sec = s % 60
  return `${m}:${String(sec).padStart(2, '0')}`
}

// Accumulated thinking time for one seat, for the whole game so far — a
// quiet corner readout, not a chess clock you're meant to race against.
// `baseSeconds` is the server's last-known total *as of `anchor`*
// (already includes the current in-progress turn's elapsed-so-far, if this
// is the acting seat — see Board.jsx's turnClockProps); while `isTicking`,
// this re-renders every half second and adds (now - anchor) on top so the
// active seat's number visibly counts up between server broadcasts instead
// of only jumping when one arrives. A non-ticking seat just shows
// `baseSeconds` — a settled number, no timer running.
export default function TurnClock({ baseSeconds, isTicking, anchor }) {
  const [, setTick] = useState(0)

  useEffect(() => {
    if (!isTicking) return undefined
    const id = setInterval(() => setTick((n) => n + 1), 500)
    return () => clearInterval(id)
  }, [isTicking])

  const liveSeconds = isTicking ? baseSeconds + (performance.now() - anchor) / 1000 : baseSeconds

  return (
    <span className="turn-clock" title="Time spent on turns so far this game">
      {formatClock(liveSeconds)}
    </span>
  )
}

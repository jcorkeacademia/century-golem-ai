import { useState } from 'react'

// The photo (or, if there is none or it 404s, a same-hue circle with the id's first letter)
// that goes inside an avatar circle — shared across every context that
// renders one (StartScreen's picker, OpponentPanel, WaitingRoom,
// GameOverOverlay's winner + ranked rows) since the "try the photo, fall
// back on error" behavior is identical everywhere, not just similarly
// styled. The outer circle itself (sized/hued per context, button vs div)
// stays owned by each caller — this only ever renders what's inside it.
export default function AvatarGlyph({ avatar, className }) {
  const [failed, setFailed] = useState(false)

  if (failed || !avatar.src) {
    return <span className="avatar-fallback-letter">{avatar.id.charAt(0).toUpperCase()}</span>
  }

  return (
    <img
      className={className}
      src={avatar.src}
      alt=""
      draggable={false}
      onError={() => setFailed(true)}
    />
  )
}

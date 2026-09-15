// Compact golem-count readout for opponent panels — one dot per win_target
// slot, filled for each golem claimed. Distinct from MePanel's GolemSlots
// (which draws bigger star-card slots); this is the small dot-grid style.
export default function GolemDots({ count, total }) {
  const slots = Array.from({ length: total }, (_, i) => i < count)

  return (
    <div className="golem-dots">
      {slots.map((filled, i) => (
        <span key={i} className={filled ? 'golem-dot filled' : 'golem-dot'} />
      ))}
    </div>
  )
}

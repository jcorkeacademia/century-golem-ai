import CrystalDots from './CrystalDots.jsx'

// Drawn-from-data card face, used whenever a card has no art.
//
// Card art is not part of the public repo (the face deck uses personal
// photos; the painted set is the publisher's artwork), so on a fresh clone
// every card arrives with art === null. Everything a player needs is already
// in the card's data, so the face is rebuilt from it: a golem's cost along
// the bottom (its points badge is drawn by GolemCard), a merchant's effect
// across the top where the printed strip would be.
export function GolemFace({ card }) {
  return (
    <div className="card-face card-face-golem">
      <span className="card-face-label">Golem</span>
      <div className="card-face-cost">
        <CrystalDots bundle={card.cost} cap={10} />
      </div>
    </div>
  )
}

export function MerchantFace({ card }) {
  let effect
  if (card.kind === 'crystal') {
    effect = (
      <>
        <span className="card-face-sign">+</span>
        <CrystalDots bundle={card.gain} cap={10} />
      </>
    )
  } else if (card.kind === 'upgrade') {
    effect = <span className="card-face-upgrade">upgrade ×{card.steps}</span>
  } else {
    effect = (
      <>
        <CrystalDots bundle={card.cost} cap={10} />
        <span className="card-face-sign">→</span>
        <CrystalDots bundle={card.trade_gain} cap={10} />
      </>
    )
  }
  return (
    <div className="card-face card-face-merchant">
      <div className="card-face-effect">{effect}</div>
      <span className="card-face-label">{card.kind}</span>
    </div>
  )
}

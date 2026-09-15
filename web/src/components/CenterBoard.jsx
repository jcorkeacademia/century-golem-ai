import GolemCard from './GolemCard.jsx'
import MerchantCard from './MerchantCard.jsx'
import DeckBox from './DeckBox.jsx'
import TokenPile from './TokenPile.jsx'

export default function CenterBoard({
  state,
  onAcquire,
  onClaim,
  stagedPayments,
  isDraggingCrystal = false,
  hoverSlot = null,
  missingSlots,
  interactive = true,
}) {
  const { golem_row, golem_deck_count, merchant_row, merchant_deck_count, tokens } = state.shared

  // Sorted by slot (not by name) so whichever pile currently occupies slot 0
  // (silver, once copper empties — see CONTRACT.md) floats above the
  // leftmost golem card.
  const piles = [
    { kind: 'copper', ...tokens.copper },
    { kind: 'silver', ...tokens.silver },
  ].sort((a, b) => a.slot - b.slot)

  return (
    <div className="center-board">
      <div className="center-rows">
        <div className="deck-row golem-deck-row">
          <div className="card-row">
            {golem_row.map((card, i) => (
              <div className="golem-slot-wrap" key={card.slot}>
                {piles[i] && <TokenPile pile={piles[i]} />}
                <GolemCard card={card} onClick={interactive ? () => onClaim(card.slot, card) : undefined} showPoints={false} />
              </div>
            ))}
          </div>
          <DeckBox label="Golem deck" count={golem_deck_count} />
        </div>

        <div className="deck-row merchant-deck-row">
          <div className="card-row">
            {merchant_row.map((card) => {
              const stagedColor = stagedPayments[card.slot]
              const isMissing = missingSlots?.includes(card.slot)
              const wrapClasses = [
                'merchant-slot-wrap',
                isDraggingCrystal && 'acquire-dropzone',
                hoverSlot === card.slot && 'acquire-dropzone-hover',
                isMissing && 'acquire-missing',
              ]
                .filter(Boolean)
                .join(' ')
              return (
                // data-acquire-slot: Board.jsx's own pointermove/pointerup
                // tracking (see handleCrystalPointerDown) hit-tests against
                // this attribute via elementFromPoint to figure out which
                // card a dragged crystal is over/dropped on — a plain
                // Pointer Events implementation instead of the native HTML5
                // Drag and Drop API, whose browser support turned out to be
                // unreliable in at least one real environment this app runs
                // in (an interrupted drag could leave the whole page's click
                // handling stuck).
                <div key={card.slot} className={wrapClasses} data-acquire-slot={card.slot}>
                  <MerchantCard
                    card={card}
                    showCrystalsOnCard
                    stagedColor={stagedColor}
                    onUnstage={() => onStageClear(card.slot)}
                    onClick={interactive ? () => onAcquire(card.slot) : undefined}
                  />
                </div>
              )
            })}
          </div>
          <DeckBox label="Play-card deck" count={merchant_deck_count} />
        </div>
      </div>
    </div>
  )
}

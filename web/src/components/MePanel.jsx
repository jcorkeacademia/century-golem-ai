import { useEffect, useState } from 'react'
import MerchantCard from './MerchantCard.jsx'
import CaravanGrid from './CaravanGrid.jsx'
import GolemSlots from './GolemSlots.jsx'
import GolemZoomOverlay from './GolemZoomOverlay.jsx'
import TurnClock from './TurnClock.jsx'

// The bottom-center panel is always this browser's own seat (Board.jsx pins
// `player` to state.you), so `isCurrent` can be false here: in solo/practice
// mode that means the bots are taking their turns (main.py's _run_solo), in
// real multiplayer it means another person is — either way every click
// handler goes quiet until play comes back around. Layout matches
// mockups/me-panel.png: Caravan (left) | playable+played stacked (center) |
// Golems + tokens + Points (right).
export default function MePanel({
  player,
  isCurrent,
  winTarget,
  builder,
  stagedPayments,
  tokenValues = { copper: 3, silver: 1 }, // century_engine.Token's fixed point values — Board.jsx passes the real ones off state.shared.tokens
  onPlayCrystal,
  onStartTrade,
  onStartUpgrade,
  onUpgradePick,
  onConfirmUpgrade,
  onCancelUpgrade,
  onStartCrystalDrag,
  draggingCaravanIndex = null,
  onRest,
  turnClock,
}) {
  function handleHandCardClick(card) {
    if (!isCurrent) return
    if (card.kind === 'crystal') onPlayCrystal(card.hand_index)
    else if (card.kind === 'trade') onStartTrade(card.hand_index, card)
    else if (card.kind === 'upgrade') onStartUpgrade(card.hand_index, card)
  }

  // Purely a local display order — hand_index (what actions address) never
  // changes. Reordering is for planning your play order, so it isn't sent
  // to the server; it resets whenever this panel starts showing a different
  // seat's hand (MePanel always renders whoever's current, and Century is
  // one action per turn, so "same player, hand changed" never happens
  // without the seat changing too — resetting on seat is enough, and more
  // correct than a length check: it also catches a same-size hand that's
  // actually a totally different player's cards).
  const [order, setOrder] = useState(() => player.hand.map((_, i) => i))
  // Tracks the *card* being dragged (its hand_index), not a position — a
  // position would go stale the instant a live drag-over reorder fires.
  const [dragKey, setDragKey] = useState(null)
  // Which claimed golem (if any) is currently blown up in GolemZoomOverlay —
  // purely a closer look, no server round-trip, so plain local state is fine.
  const [zoomedGolem, setZoomedGolem] = useState(null)
  useEffect(() => {
    setOrder(player.hand.map((_, i) => i))
    setDragKey(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [player.seat])
  const orderedHand = order.length === player.hand.length ? order.map((i) => player.hand[i]).filter(Boolean) : player.hand

  // Reorders live as the drag crosses another card, instead of only on
  // drop — the hovered card immediately slides over to open a gap, so the
  // hand visibly rearranges itself while you're still holding the card.
  function handleDragEnterCard(overKey) {
    if (dragKey === null || dragKey === overKey) return
    setOrder((prev) => {
      const from = prev.indexOf(dragKey)
      const to = prev.indexOf(overKey)
      if (from === -1 || to === -1 || from === to) return prev
      const next = [...prev]
      next.splice(from, 1)
      next.splice(to, 0, dragKey)
      return next
    })
  }

  // Mid-upgrade: the caravan itself becomes the picker — clicking a specific
  // crystal stages one step on that exact slot (positional, so it's the one
  // that visibly advances/sparkles — see upgrade.js), not just "a" crystal
  // of that color.
  const upgrading = builder?.kind === 'upgrade'
  const canPickMore = upgrading && builder.picks.length < builder.maxSteps

  // The caravan is a live drag source for acquire payments the whole time
  // it's your turn (see Board.jsx's handleStageDrop) — no need to click a
  // target card first. A crystal physically leaves it and lands on a
  // merchant card (CenterBoard.jsx), so what's shown here is the real
  // caravan minus whatever's already staged on cards, not the full caravan
  // with something layered on top. That's also what stops you from staging
  // more of a color than you actually have — once they're all "picked up,"
  // there's nothing left to drag. Blocked only while the caravan is doing
  // something else that needs its clicks for a different meaning (the
  // upgrade picker) or is temporarily not yours to touch (the trade dialog).
  const draggingBlocked = upgrading || builder?.kind === 'trade' || !isCurrent
  const staged = { Y: 0, G: 0, B: 0, M: 0 }
  for (const c of stagedPayments) if (c) staged[c] += 1
  const displayCaravan = {
    Y: player.caravan.Y - staged.Y,
    G: player.caravan.G - staged.G,
    B: player.caravan.B - staged.B,
    M: player.caravan.M - staged.M,
  }

  return (
    <div className="me-panel">
      {!isCurrent && <div className="me-waiting-banner">Waiting for other players…</div>}
      {isCurrent && <div className="me-turn-banner">Your Turn</div>}
      <div className={isCurrent ? 'me-boxes current-turn' : 'me-boxes me-boxes-waiting'}>
        <div className="me-box me-box-caravan">
          <div className="caravan-block">
            {upgrading && (
              /* Lives right above the caravan instead of a separate strip
                 at the bottom of the screen — gray until every step is
                 spent, same threshold regardless of whether this is
                 Upgrade 2 or Upgrade 3 (builder.maxSteps drives it either
                 way). */
              <div className="upgrade-confirm-row">
                <button
                  type="button"
                  className="upgrade-confirm-btn"
                  disabled={builder.picks.length !== builder.maxSteps}
                  onClick={onConfirmUpgrade}
                >
                  Confirm
                </button>
                <button
                  type="button"
                  className="upgrade-cancel-btn"
                  onClick={onCancelUpgrade}
                  aria-label="Cancel upgrade"
                  title="Cancel"
                >
                  ×
                </button>
              </div>
            )}
            <div className="caravan-grid-wrap">
              <CaravanGrid
                bundle={displayCaravan}
                picks={upgrading ? builder.picks : undefined}
                // Stays wired even once every step is spent — a maxed-out
                // pending slot is still clickable (see CaravanGrid.jsx) to
                // walk it back, so the handler itself has to stay reachable
                // rather than being cut off by canPickMore.
                onSlotClick={upgrading ? onUpgradePick : undefined}
                onCrystalPointerDown={draggingBlocked ? undefined : onStartCrystalDrag}
                draggingIndex={draggingCaravanIndex}
              />
            </div>
            {upgrading && canPickMore && <span className="caravan-hint">Click crystals to upgrade</span>}
          </div>
        </div>

        <div className="me-box me-box-cards">
          <svg className="mat-crest" viewBox="0 0 100 100" aria-hidden="true">
            <circle cx="50" cy="50" r="47" fill="none" stroke="currentColor" strokeWidth="1.4" />
            <circle cx="50" cy="50" r="34" fill="none" stroke="currentColor" strokeWidth="0.9" />
            <path
              d="M50 5 L57.5 42.5 L95 50 L57.5 57.5 L50 95 L42.5 57.5 L5 50 L42.5 42.5 Z"
              fill="currentColor"
            />
            <circle cx="50" cy="50" r="9" fill="none" stroke="currentColor" strokeWidth="1.4" />
          </svg>
          <div className="cards-block">
            <div className="card-col">
              <span className="col-label">playable</span>
              <div className="card-row me-card-row">
                {orderedHand.map((card) => (
                  <div
                    key={card.hand_index}
                    className={`hand-card-slot${dragKey === card.hand_index ? ' dragging' : ''}`}
                    draggable
                    onDragStart={() => setDragKey(card.hand_index)}
                    onDragEnd={() => setDragKey(null)}
                    onDragEnter={() => handleDragEnterCard(card.hand_index)}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={(e) => e.preventDefault()}
                  >
                    <MerchantCard card={card} onClick={isCurrent ? () => handleHandCardClick(card) : undefined} />
                  </div>
                ))}
              </div>
              {/* TODO: once a row exceeds 10 cards, fan/overlap them with click-to-expand instead of overflowing */}
            </div>
            <div className="cards-divider" />
            <div className="card-col">
              <span className="col-label">played</span>
              <div className="card-row me-card-row">
                {player.played.map((card, i) => (
                  <MerchantCard key={i} card={card} />
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="me-golems-col">
          <div className="me-box me-box-golems">
            <span className="block-label">Golems</span>
            <div className="golem-slots-wrap">
              <GolemSlots golems={player.golems} total={winTarget} onSelect={setZoomedGolem} />
            </div>
            <div className="golems-meta">
              {/* Tokens get their own visible row instead of tiny dots
                  stacked on top of the golem cards (illegible, and easy to
                  miss entirely) — a token is permanent the moment you get
                  it, so unlike caravan crystals it's safe to fold straight
                  into Points below without that number jumping around. */}
              {(player.tokens.copper > 0 || player.tokens.silver > 0) && (
                <div className="token-counts-readout">
                  {player.tokens.copper > 0 && (
                    <span className="token-count token-copper" title={`${player.tokens.copper} copper token(s), worth ${tokenValues.copper} pts each`}>
                      <span className="token-dot" /> {player.tokens.copper}
                    </span>
                  )}
                  {player.tokens.silver > 0 && (
                    <span className="token-count token-silver" title={`${player.tokens.silver} silver token(s), worth ${tokenValues.silver} pt each`}>
                      <span className="token-dot" /> {player.tokens.silver}
                    </span>
                  )}
                </div>
              )}
              {/* Golem points + token points — non-yellow crystals still
                  aren't included here, since those only count toward score
                  at actual game end (century_engine.Player.score()) and
                  would make this number jump around with every caravan
                  change that isn't real yet. Tokens, unlike crystals, are
                  locked in the moment you get them. */}
              <div className="points-and-clock-row">
                <span className="points-readout">
                  Points: {player.golem_points + player.tokens.copper * tokenValues.copper + player.tokens.silver * tokenValues.silver}
                </span>
                {/* Bottom-right corner, quiet — accumulated thinking time,
                    not a chess clock you're racing against (TurnClock.jsx). */}
                {turnClock && <TurnClock {...turnClock} />}
              </div>
            </div>
          </div>
          {onRest && (
            <button className="rest-button-below" onClick={onRest} disabled={player.played.length === 0}>
              Reset
            </button>
          )}
        </div>
      </div>
      {zoomedGolem && <GolemZoomOverlay card={zoomedGolem} onClose={() => setZoomedGolem(null)} />}
    </div>
  )
}

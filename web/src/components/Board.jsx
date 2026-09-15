import { useEffect, useRef, useState } from 'react'
import CenterBoard from './CenterBoard.jsx'
import OpponentPanel from './OpponentPanel.jsx'
import MePanel from './MePanel.jsx'
import ActionStrip from './ActionStrip.jsx'
import PlayerDetailOverlay from './PlayerDetailOverlay.jsx'
import TradeDialog from './TradeDialog.jsx'
import ClaimDialog from './ClaimDialog.jsx'
import GameOverOverlay from './GameOverOverlay.jsx'
import { slotColorAfterPicks, picksToColors } from '../upgrade.js'
import { avatarIdForSeat } from '../avatars.js'
import { maxAffordableTradeTimes } from '../trade.js'
import { crystalIconUrl } from '../crystalIcons.js'

// Radial seating per mockup.png: bottom-center is always this browser's own
// seat (state.you) — the only panel with click handlers, since it's the
// only seat this client is ever allowed to act for. The other slots are
// fixed relative to that seat (seat+1, seat+2, ...), not to whoever's
// currently acting, so the layout doesn't reshuffle as turns pass.
//
// Which physical slots get used depends on how many opponents there are
// (2-5 total players => 1-4 opponents), not just "always the same 4-slot
// grid with empty gaps": a lone opponent (2p game) sits centered on the
// full left side rather than being squeezed into just the top or bottom
// half with a dead gap next to it, two opponents (3p) get a full-height
// side each, and three opponents (4p) get the normal stacked pair on one
// side plus a single centered one on the other — see the matching
// .table-layout.layout-opp-N / .area-leftFull/.area-rightFull rules in
// styles.css, which is where the actual centering/spanning happens.
const OPPONENT_SLOTS_BY_COUNT = {
  1: ['area-leftFull'],
  2: ['area-leftFull', 'area-rightFull'],
  3: ['area-seat1', 'area-seat2', 'area-rightFull'],
  4: ['area-seat1', 'area-seat2', 'area-seat3', 'area-seat4'],
}

const MERCHANT_ROW_SIZE = 6 // century_engine.Game.MERCHANT_ROW
const NO_STAGED_PAYMENTS = Array(MERCHANT_ROW_SIZE).fill(null)

// Each player's own choice, straight from the server (CONTRACT.md's
// `avatar` field) — avatarIdForSeat is only a fallback for the rare case a
// seat somehow doesn't have one.
function resolveAvatar(player) {
  return player.avatar || avatarIdForSeat(player.seat)
}

export default function Board({ game, onLeave }) {
  const { state, stateReceivedAt, sendAction, lastError, clearError } = game
  const [builder, setBuilder] = useState(null)
  const [expandedSeat, setExpandedSeat] = useState(null)
  const [gameOverDismissed, setGameOverDismissed] = useState(false)
  // A crystal staged on a merchant card by dragging, indexed by row
  // position — independent of `builder`, because staging no longer requires
  // picking a target first (see handleAcquire below). Lives here rather
  // than in CenterBoard so it isn't wiped out by that component just
  // re-rendering, and so MePanel can subtract it from the caravan it shows.
  const [stagedPayments, setStagedPayments] = useState(NO_STAGED_PAYMENTS)
  // Which merchant-row slots to briefly flash because they were still
  // missing a staged crystal when the player clicked the card to their
  // right — a moment's on-board feedback instead of a persistent bottom
  // strip (see handleStartAcquire).
  const [missingFlash, setMissingFlash] = useState([])
  const missingFlashTimer = useRef(null)
  // A crystal picked up off the caravan for acquire payment, tracked with
  // plain Pointer Events instead of the native HTML5 Drag and Drop API —
  // that API turned out to be unreliable in at least one real environment
  // this app runs in (an interrupted native drag left the whole page's
  // click handling stuck; see CenterBoard.jsx's git history), where Pointer
  // Events are a much more consistently implemented primitive. `sourceIndex`
  // is the caravan slot it came from (dims that slot while airborne, see
  // CaravanGrid.jsx); `hoverSlot` is whichever merchant card it's currently
  // over, recomputed on every move via elementFromPoint — same value both
  // drives the drop-target highlight and decides what a release lands on,
  // so those two can never disagree.
  const [crystalDrag, setCrystalDrag] = useState(null) // { color, sourceIndex, x, y, hoverSlot } | null
  const crystalDragRef = useRef(null)
  crystalDragRef.current = crystalDrag

  const n = state.players.length
  const current = state.current
  // This browser's own seat (CONTRACT.md 1a) — with real per-device
  // multiplayer, that can be any seat, not always 0, so this panel is
  // pinned to whichever seat the server says is "you" rather than a
  // hardcoded index. "Is it my turn" is a separate question
  // (state.current === mySeat) from "whose data am I looking at."
  const mySeat = state.you
  const me = state.players[mySeat]
  const myTurn = current === mySeat

  // A builder (trade/upgrade) only ever makes sense for whoever's turn it
  // was when it was opened — every action (including one taken without
  // going through a builder at all, like Acquire or Rest) advances
  // state.current, so this is the one signal that reliably fires no matter
  // which path ended the turn. Staged-row-crystal payments are the same
  // story — they're real only until confirmed, so a turn change discards
  // them exactly like an unconfirmed upgrade builder.
  useEffect(() => {
    setBuilder(null)
    setStagedPayments(NO_STAGED_PAYMENTS)
    setMissingFlash([])
    setCrystalDrag(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.current])

  // Only (re)subscribes when a drag starts or ends, not on every pixel of
  // movement within one — Boolean(crystalDrag) stays true for the whole
  // drag even though the object itself gets replaced on every move.
  useEffect(() => {
    if (!crystalDrag) return undefined

    function resolveSlotUnder(x, y) {
      const el = document.elementFromPoint(x, y)
      const dropEl = el?.closest?.('[data-acquire-slot]')
      return dropEl ? Number(dropEl.dataset.acquireSlot) : null
    }
    function handleMove(e) {
      const hoverSlot = resolveSlotUnder(e.clientX, e.clientY)
      setCrystalDrag((prev) => (prev ? { ...prev, x: e.clientX, y: e.clientY, hoverSlot } : prev))
    }
    function handleUp() {
      const current = crystalDragRef.current
      if (current && current.hoverSlot !== null) handleStageDrop(current.hoverSlot, current.color)
      setCrystalDrag(null)
    }
    function handleCancel() {
      setCrystalDrag(null)
    }
    document.body.style.cursor = 'grabbing'
    window.addEventListener('pointermove', handleMove)
    window.addEventListener('pointerup', handleUp)
    window.addEventListener('pointercancel', handleCancel)
    return () => {
      document.body.style.cursor = ''
      window.removeEventListener('pointermove', handleMove)
      window.removeEventListener('pointerup', handleUp)
      window.removeEventListener('pointercancel', handleCancel)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [Boolean(crystalDrag)])

  // Picking a crystal up off the caravan (CaravanGrid.jsx's onCrystalPointerDown)
  // starts the drag; MePanel only ever wires that callback when dragging is
  // actually allowed right now (your turn, not mid-upgrade/trade), so no
  // extra gating needed here.
  function handleStartCrystalDrag(index, color, e) {
    setCrystalDrag({ color, sourceIndex: index, x: e.clientX, y: e.clientY, hoverSlot: null })
  }

  // A fresh game (debug/reset, or a real rematch once that exists) flips
  // game_over back to false — re-arm the overlay for whenever THIS game
  // ends, rather than leaving it permanently dismissed from the last one.
  useEffect(() => {
    if (!state.game_over) setGameOverDismissed(false)
  }, [state.game_over])

  // Fixed seating around this browser's own seat, not rotated by whoever's
  // current — "who's sitting where" shouldn't reshuffle every time the turn
  // moves.
  const opponentOrder = []
  for (let i = 1; i < n; i++) opponentOrder.push(state.players[(mySeat + i) % n])
  const opponentSlots = OPPONENT_SLOTS_BY_COUNT[opponentOrder.length] || OPPONENT_SLOTS_BY_COUNT[4]

  // TurnClock.jsx's props for one player: a settled total for anyone not
  // currently up, or — for whoever state.current is — the server's last
  // reported total *including* their still-running turn, which TurnClock
  // then keeps ticking client-side past `anchor` (stateReceivedAt) until
  // the next broadcast supersedes it.
  function turnClockProps(player) {
    const isTicking = player.seat === current
    const baseSeconds = player.turn_seconds + (isTicking ? state.current_turn_elapsed_seconds : 0)
    return { baseSeconds, isTicking, anchor: stateReceivedAt }
  }

  // Opponents only, normally — but GameOverOverlay's results table lists
  // every seat including your own, and clicking your own row there should
  // still pull up the same detail card (there's no live MePanel to look at
  // any more once the game's over), so this also matches `mySeat`, not just
  // opponentOrder.
  const expandedIndex = opponentOrder.findIndex((p) => p.seat === expandedSeat)
  const expandedPlayer =
    expandedIndex >= 0 ? opponentOrder[expandedIndex] : expandedSeat === mySeat ? me : null
  const expandedLabel = expandedIndex >= 0 ? `user${expandedIndex + 1}` : expandedPlayer ? 'you' : ''

  function handlePlayCrystal(handIndex) {
    if (state.game_over || !myTurn) return
    setBuilder(null)
    setStagedPayments(NO_STAGED_PAYMENTS)
    sendAction({ type: 'play_crystal', hand_index: handIndex })
  }

  // A centred dialog (see TradeDialog.jsx / trade_dialog_prompt.md) rather
  // than the old bottom-strip prompt — but only when there's an actual
  // decision to make. Exactly one legal repeat count means the dialog would
  // open with a single enabled button and nothing to choose, which is pure
  // friction, so that case is just sent directly; zero legal counts means
  // the card wasn't really playable (shouldn't happen for a card the UI let
  // you click, but not this handler's job to explain why), so it's a no-op.
  function handleStartTrade(handIndex, card) {
    if (state.game_over || !myTurn) return
    const maxTimes = maxAffordableTradeTimes(me.caravan, card.cost)
    if (maxTimes <= 0) return
    if (maxTimes === 1) {
      sendAction({ type: 'play_trade', hand_index: handIndex, times: 1 })
      return
    }
    setBuilder({ kind: 'trade', handIndex, card })
  }

  function handleStartUpgrade(handIndex, card) {
    if (state.game_over || !myTurn) return
    setBuilder({ kind: 'upgrade', handIndex, cardName: card.name, maxSteps: card.steps, picks: [] })
  }

  // Clicking a crystal in the caravan (instead of an abstract "+Y" button)
  // stages one upgrade step on that exact slot — picks are slot indices, not
  // colors, so the swatch you click is the one that visibly advances in
  // place (see upgrade.js). Clicking the same slot again chains it further
  // (yellow->green->blue); a different slot of the same color stages
  // independently instead of the two blurring together.
  //
  // Once a slot can't take another step forward — either it's hit magenta,
  // or every step on the card is already spent — clicking it again walks
  // back its own most recent step instead of doing nothing. That's the
  // undo for a specific mis-click (e.g. double-upgrading the wrong crystal
  // when you meant to split the steps across two): click the overcommitted
  // gem back down, then click the one you actually meant. The Undo button
  // in ActionStrip still undoes the single most-recent pick overall; this
  // is the same idea aimed at one gem instead.
  function handleUpgradePick(slotIndex) {
    if (!builder || builder.kind !== 'upgrade') return
    const color = slotColorAfterPicks(me.caravan, builder.picks, slotIndex)
    const canAdvance = color && color !== 'M' && builder.picks.length < builder.maxSteps
    if (canAdvance) {
      setBuilder({ ...builder, picks: [...builder.picks, slotIndex] })
      return
    }
    const lastIdx = builder.picks.lastIndexOf(slotIndex)
    if (lastIdx === -1) return
    const picks = [...builder.picks]
    picks.splice(lastIdx, 1)
    setBuilder({ ...builder, picks })
  }

  // A crystal dragged off the caravan (CaravanGrid's draggable slots) lands
  // on WHICHEVER merchant card it's dropped on (CenterBoard.jsx) — staging
  // is always available, not gated behind first clicking a target, so
  // dragging never has to wait on a click. Positional because the engine's
  // own payment tuple is (century_engine._acquire: "for k, color in
  // enumerate(a.payment): ... self.row_crystals[k] +="), so which merchant
  // card ends up holding which crystal for the next player to find is a
  // real choice, not just picking a multiset of colors. Dropping on an
  // already-staged slot just replaces it.
  function handleStageDrop(slotIndex, color) {
    setStagedPayments((prev) => {
      const next = [...prev]
      next[slotIndex] = color
      return next
    })
  }

  // Clicking a crystal already staged on a card lifts it back off — the
  // undo for "oops, wrong card," independent of any target selection.
  function handleStageClear(slotIndex) {
    setStagedPayments((prev) => {
      const next = [...prev]
      next[slotIndex] = null
      return next
    })
  }

  // Clicking a merchant card is the *finishing* gesture, not the opening
  // one: row_index 0 is always free and goes through immediately; for
  // anything else, if every card to its left already has a staged crystal
  // (dragged there beforehand, in any order, no prior click required), the
  // purchase just goes through on this click. An incomplete payment doesn't
  // open any bottom-strip prompt — it just briefly flashes whichever of the
  // cards to the left are still missing a crystal, right where the player
  // needs to drop one, then fades. No modal, no persistent rectangle, no
  // extra Confirm step: the "take it back before it's spent" safety net is
  // the per-gem undo (click a staged crystal to lift it back off, see
  // handleStageClear) rather than a second click on the card itself.
  function handleStartAcquire(rowIndex) {
    if (state.game_over || !myTurn) return
    if (rowIndex === 0) {
      sendAction({ type: 'acquire', row_index: 0, payment: [] })
      return
    }
    const payment = stagedPayments.slice(0, rowIndex)
    if (payment.every(Boolean)) {
      sendAction({ type: 'acquire', row_index: rowIndex, payment })
      setStagedPayments(NO_STAGED_PAYMENTS)
      return
    }
    const missing = []
    for (let i = 0; i < rowIndex; i++) if (!payment[i]) missing.push(i)
    setMissingFlash(missing)
    clearTimeout(missingFlashTimer.current)
    missingFlashTimer.current = setTimeout(() => setMissingFlash([]), 600)
  }

  // Same shape as handleStartTrade: a centred dialog (ClaimDialog.jsx)
  // showing the golem and what the caravan looks like once its cost is
  // paid, rather than sending the instant it's clicked. A golem whose cost
  // isn't affordable at all doesn't open anything — same "nothing to
  // decide" no-op Trade already uses for a card you can't play at all.
  function handleStartClaim(rowIndex, card) {
    if (state.game_over || !myTurn) return
    if (maxAffordableTradeTimes(me.caravan, card.cost) < 1) return
    setBuilder({ kind: 'claim', rowIndex, card })
  }

  function handleRest() {
    if (state.game_over || !myTurn) return
    setBuilder(null)
    setStagedPayments(NO_STAGED_PAYMENTS)
    sendAction({ type: 'rest' })
  }

  function confirmBuilder() {
    if (!builder || builder.kind !== 'upgrade' || !myTurn) return
    sendAction({ type: 'play_upgrade', hand_index: builder.handIndex, upgrades: picksToColors(me.caravan, builder.picks) })
    setBuilder(null)
  }

  return (
    <div className="app-shell">
      <div className={`table-layout layout-opp-${opponentOrder.length}`}>
        {opponentOrder.map((player, i) => (
          <div key={player.seat} className={opponentSlots[i]}>
            <OpponentPanel
              player={player}
              avatarId={resolveAvatar(player)}
              isCurrent={player.seat === state.current}
              winTarget={state.win_target}
              onExpand={() => setExpandedSeat(player.seat)}
              turnClock={turnClockProps(player)}
            />
          </div>
        ))}

        <div className="area-center">
          <CenterBoard
            state={state}
            onAcquire={handleStartAcquire}
            onClaim={handleStartClaim}
            stagedPayments={stagedPayments}
            onStageClear={handleStageClear}
            isDraggingCrystal={Boolean(crystalDrag)}
            hoverSlot={crystalDrag?.hoverSlot ?? null}
            missingSlots={missingFlash}
            interactive={myTurn}
          />
        </div>

        <div className="area-me">
          <MePanel
            player={me}
            isCurrent={myTurn}
            winTarget={state.win_target}
            builder={builder}
            stagedPayments={stagedPayments}
            tokenValues={{ copper: state.shared.tokens.copper.value, silver: state.shared.tokens.silver.value }}
            onPlayCrystal={handlePlayCrystal}
            onStartTrade={handleStartTrade}
            onStartUpgrade={handleStartUpgrade}
            onUpgradePick={handleUpgradePick}
            onConfirmUpgrade={confirmBuilder}
            onCancelUpgrade={() => setBuilder(null)}
            onStartCrystalDrag={handleStartCrystalDrag}
            draggingCaravanIndex={crystalDrag?.sourceIndex ?? null}
            onRest={state.game_over || !myTurn ? undefined : handleRest}
            turnClock={turnClockProps(me)}
          />
        </div>

        <div className="area-strip">
          <ActionStrip state={state} lastError={lastError} onDismissError={clearError} />
        </div>
      </div>

      {/* Follows the pointer while a crystal is airborne (handleStartCrystalDrag)
          — pointer-events: none is load-bearing here, not just tidy: without
          it this element would be what elementFromPoint finds under the
          cursor instead of the merchant card underneath it, breaking the
          hover highlight and the drop itself. */}
      {crystalDrag && (
        <img
          className="crystal-drag-ghost"
          src={crystalIconUrl(crystalDrag.color)}
          alt=""
          style={{ left: crystalDrag.x, top: crystalDrag.y }}
        />
      )}

      {/* A refresh reconnects to this same room now (App.jsx persists the
          session) instead of dropping you back at StartScreen — so this is
          the only way out, not something a normal reload does for you. */}
      {onLeave && (
        <button type="button" className="leave-game-btn" onClick={onLeave}>
          Leave game
        </button>
      )}

      {expandedPlayer && (
        <PlayerDetailOverlay
          player={expandedPlayer}
          seatLabel={expandedLabel}
          winTarget={state.win_target}
          onClose={() => setExpandedSeat(null)}
        />
      )}

      {builder?.kind === 'trade' && (
        <TradeDialog
          card={builder.card}
          caravan={me.caravan}
          onConfirm={(times) => {
            sendAction({ type: 'play_trade', hand_index: builder.handIndex, times })
            setBuilder(null)
          }}
          onCancel={() => setBuilder(null)}
        />
      )}

      {builder?.kind === 'claim' && (
        <ClaimDialog
          card={builder.card}
          caravan={me.caravan}
          onConfirm={() => {
            sendAction({ type: 'claim', row_index: builder.rowIndex })
            setBuilder(null)
          }}
          onCancel={() => setBuilder(null)}
        />
      )}

      {state.game_over && !gameOverDismissed && (
        <GameOverOverlay
          players={state.players}
          winner={state.winner}
          resolveAvatar={resolveAvatar}
          onClose={() => setGameOverDismissed(true)}
          onSelectPlayer={setExpandedSeat}
        />
      )}

      {/* Closing the overlay to look at the frozen final board used to be a
          one-way trip — this brings it back. */}
      {state.game_over && gameOverDismissed && (
        <button type="button" className="gameover-reopen" onClick={() => setGameOverDismissed(false)}>
          View results
        </button>
      )}
    </div>
  )
}

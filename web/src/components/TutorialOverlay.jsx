import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import CaravanGrid from './CaravanGrid.jsx'
import MerchantCard from './MerchantCard.jsx'
import { slotColorAfterPicks, picksToColors } from '../upgrade.js'

// The interactive tutorial's text and staging (server/tutorial.py,
// docs/CONTRACT.md §1e). Everything it shows comes off `state.tutorial` — which
// step, its words, what to highlight — and everything the player does goes
// back to the server: Next is `tutorial_next`, the upgrade exercise is a
// `play_upgrade` the server judges on a sandbox game, and the scene 6
// purchase is an ordinary acquire made on the board itself (outlined by
// Board.jsx's guide-target classes, the same as a guided room's next move).
//
// Every step is the same kind of box (a page — see StepText), drawn one of
// two ways:
// - `stage` set (scenes 1-5 and 8): over the dimmed board, with the same
//   CaravanGrid/MerchantCard the board uses beside or inside it.
// - `stage` null: on the live board, with a highlight ring around the part
//   the text is about and the box placed next to it. While the step only wants
//   Next, a transparent blocker stops clicks reaching the board underneath —
//   the server would refuse them anyway (error code `tutorial`), this just
//   saves the round trip.

// Where each `highlight` lives on the board. Several elements are boxed
// together as one rectangle (the mat is the caravan plus the card columns).
// The centre rows are measured card by card: their .card-row wrapper is
// display: contents (styles.css), so it has no box of its own.
const HIGHLIGHT_TARGETS = {
  merchant_row: () => [...document.querySelectorAll('.merchant-deck-row .merchant-slot-wrap')],
  merchant_card: (slot) => [document.querySelector(`[data-acquire-slot="${slot}"]`)],
  me_mat: () => [document.querySelector('.me-box-caravan'), document.querySelector('.me-box-cards')],
  mat: () => [document.querySelector('.me-boxes')],
  played: () => [document.querySelectorAll('.me-box-cards .card-col')[1]],
  reset: () => [document.querySelector('.rest-button-below')],
  golem_row: () => [...document.querySelectorAll('.golem-deck-row .golem-slot-wrap')],
}
const RING_PAD = 8
const BUBBLE_GAP = 18
const EDGE = 12

function measureHighlight(kind, slot) {
  const els = (HIGHLIGHT_TARGETS[kind]?.(slot) || []).filter(Boolean)
  if (!els.length) return null
  const rects = els.map((el) => el.getBoundingClientRect())
  const top = Math.min(...rects.map((r) => r.top)) - RING_PAD
  const left = Math.min(...rects.map((r) => r.left)) - RING_PAD
  const bottom = Math.max(...rects.map((r) => r.bottom)) + RING_PAD
  const right = Math.max(...rects.map((r) => r.right)) + RING_PAD
  return { top: Math.round(top), left: Math.round(left), width: Math.round(right - left), height: Math.round(bottom - top) }
}

// Re-measured every frame rather than once: the board reflows as state
// arrives (cards slide, rows refill, the window resizes), and a ring left
// where the element used to be is worse than none. Only an actual change
// re-renders.
function useHighlightRect(kind, slot) {
  const [rect, setRect] = useState(null)
  useEffect(() => {
    if (!kind) {
      setRect(null)
      return undefined
    }
    let frame
    let last = null
    function tick() {
      const r = measureHighlight(kind, slot)
      const key = r ? `${r.top}|${r.left}|${r.width}|${r.height}` : ''
      if (key !== last) {
        last = key
        setRect(r)
      }
      frame = requestAnimationFrame(tick)
    }
    tick()
    return () => cancelAnimationFrame(frame)
  }, [kind, slot])
  return rect
}

// The live top edge of the board element `selector` (and of `ref`'s own
// element), re-measured every frame like useHighlightRect, so a box sized
// to end on it follows the board through resizes and reflows.
function useTopEdges(selector, ref) {
  const [edges, setEdges] = useState(null)
  useEffect(() => {
    let frame
    let last = null
    function tick() {
      const target = document.querySelector(selector)
      const own = ref.current
      const next = target && own ? { target: Math.round(target.getBoundingClientRect().top), own: Math.round(own.getBoundingClientRect().top) } : null
      const key = next ? `${next.target}|${next.own}` : ''
      if (key !== last) {
        last = key
        setEdges(next)
      }
      frame = requestAnimationFrame(tick)
    }
    tick()
    return () => cancelAnimationFrame(frame)
  }, [selector, ref])
  return edges
}

// Above the anchor if it fits, else below it, else pinned to the top;
// centred on the anchor horizontally. No anchor: centred on the screen.
// Above or below, never beside: that keeps the box off the merchant row the
// scene 6 purchase drops onto, and off the caravan it drags from.
function placeBubble(rect, w, h) {
  const vw = window.innerWidth
  const vh = window.innerHeight
  if (!rect) return { top: Math.max(EDGE, (vh - h) / 2), left: Math.max(EDGE, (vw - w) / 2) }
  const above = rect.top - BUBBLE_GAP - h
  const below = rect.top + rect.height + BUBBLE_GAP
  let top
  if (above >= EDGE) top = above
  else if (below + h <= vh - EDGE) top = below
  // Fits neither: the side with more room, against the screen's edge.
  else top = rect.top > vh - (rect.top + rect.height) ? EDGE : Math.max(EDGE, vh - EDGE - h)
  const left = Math.min(Math.max(EDGE, rect.left + rect.width / 2 - w / 2), Math.max(EDGE, vw - w - EDGE))
  return { top, left }
}

export default function TutorialOverlay({ tutorial, gameOver, lastError, onNext, onUpgrade, onSkip }) {
  const canNext = tutorial.wait === 'next'

  // Enter advances, like the Next button (design doc: "Next or Enter").
  useEffect(() => {
    if (!canNext) return undefined
    function onKeyDown(e) {
      if (e.key === 'Enter' && !e.repeat) onNext()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [canNext, onNext])

  // A refusal belongs to the step it was made on — remember whichever error
  // was already showing when this step began, and only show a newer one.
  const staleError = useRef(lastError)
  const [stepSeen, setStepSeen] = useState(tutorial.step)
  if (stepSeen !== tutorial.step) {
    staleError.current = lastError
    setStepSeen(tutorial.step)
  }
  const error = lastError && lastError !== staleError.current ? lastError.message : null

  if (gameOver) return null
  const shared = { tutorial, error, canNext, onNext, onSkip }
  if (tutorial.stage) return <StagedScreen {...shared} onUpgrade={onUpgrade} />
  return <BoardCoach {...shared} />
}

// Every step is drawn as the same kind of box — a "page": the game's name and
// Skip on one line at the top, the step's words, then a footer with "Step N
// of M" and Next. `body` (optional) replaces the title and words, for a box
// that shows more than one step's. `showFeedback` off: the caller shows
// tutorial.feedback (and any refusal) somewhere of its own.
function StepText({ tutorial, error, canNext, onNext, onSkip, extraButton, body, showFeedback = true }) {
  const { feedback } = tutorial
  return (
    <>
      <div className="tut-head">
        <span className="tut-eyebrow">century: golem edition</span>
        <button type="button" className="tut-skip" onClick={onSkip}>
          Skip tutorial
        </button>
      </div>
      {body ?? <PageSection section={tutorial} />}
      {showFeedback && feedback && (
        <div className={`tut-feedback ${feedback.ok ? 'tut-feedback-ok' : 'tut-feedback-bad'}`}>{feedback.text}</div>
      )}
      {showFeedback && error && <div className="tut-feedback tut-feedback-bad">{error}</div>}
      <div className="tut-foot">
        <span className="tut-step">
          Step {tutorial.step} of {tutorial.total}
        </span>
        <div className="tut-foot-buttons">
          {extraButton}
          {canNext && (
            <button type="button" className="tut-next" onClick={onNext}>
              Next
            </button>
          )}
          {tutorial.wait === 'busy' && (
            <button type="button" className="tut-next" disabled>
              One moment…
            </button>
          )}
          {/* A step that waits for a move has no button; an invisible one
              keeps the footer, and so the box, the same height. */}
          {!extraButton && !canNext && tutorial.wait !== 'busy' && (
            <span className="tut-next tut-reserve" aria-hidden="true">
              Next
            </span>
          )}
        </div>
      </div>
    </>
  )
}

// One step's heading and words, as a block of a page that holds several.
// `instruction` (a step that wants one exact move) is set apart under the
// words; a refusal (`error`) takes its place, so trying the wrong move never
// changes the box's size. `reserve` draws the block invisibly: it holds the
// room a later step's words will need, so the box is the right size from
// the start.
function PageSection({ section, className = '', error = null, reserve = false }) {
  return (
    <section className={`tut-section ${className}${reserve ? ' tut-reserve' : ''}`} aria-hidden={reserve || undefined}>
      <h2 className="tut-title">{section.title}</h2>
      <div className="tut-body">
        {section.paragraphs.map((p, i) => (
          <p key={i} className="tut-text">
            {p}
          </p>
        ))}
      </div>
      {section.instruction && (
        // The instruction and what a wrong move gets told share one spot,
        // sized to the longer of the two (the server sends both ahead).
        <div className="tut-instruction-stack">
          <p className={`tut-instruction${error ? ' tut-hidden' : ''}`}>{section.instruction}</p>
          <p className={`tut-instruction tut-instruction-bad${error ? '' : ' tut-hidden'}`}>
            {error ?? section.refusal ?? ''}
          </p>
        </div>
      )}
    </section>
  )
}

// A box's words as a page: the step before (`earlier`), this step's (popping
// in when it continues a box), and the step still to come (`later`, held
// invisibly). Each block is keyed by step, so as the page moves on, blocks
// already on screen stay put rather than remounting.
function pageSections(tutorial, error) {
  const current = { id: tutorial.id, title: tutorial.title, paragraphs: tutorial.paragraphs, instruction: tutorial.instruction, refusal: tutorial.refusal }
  const earlier = tutorial.earlier ?? []
  return [
    ...earlier.map((s) => <PageSection key={s.id} section={s} />),
    <PageSection key={current.id} section={current} error={error} className={earlier.length ? 'tut-pop' : ''} />,
    ...(tutorial.later ?? []).map((s) => <PageSection key={s.id} section={s} reserve />),
  ]
}

// Scenes 1-5, one page that builds up a piece per click: a big box high on
// the screen whose words move on a step at a time, with one caravan in it
// from scene 2 onward; the Double Upgrade arrives beside the box at scene 3,
// level with its middle and captioned with its name, and at scene 4 the
// upgrade exercise is played on that same caravan with that same card. The
// box and the card's place are one group, the card's space held open from
// scene 2, so the box never moves. Scene 5 ("one thing per turn") closes the
// page before the board.
const OPENING_STAGES = new Set(['title', 'caravan', 'order', 'upgrade', 'turn'])

// Scene 1 is the exception: just the welcome, in its own box in the middle
// of the screen, sized to its words. Scene 2 moves the box to the left and
// starts building — the key change remounts the box once there, so it pops
// into its new place instead of jumping; from then on the box keeps one key
// and only what's new pops in.
//
// The box shows this step's words and the step before's (`earlier`, sent by
// the server, so a refresh shows the same page). The caravan sits under
// scene 2's words ("seen below") while they're shown, and at the top once
// they've gone; the objectives sit under scene 4's.
//
// From scene 2 the box runs from near the top of the screen down to the top
// edge of the player's own mat (.me-boxes, the outlined band at the
// bottom), measured live, so it's as tall as the board allows for two
// steps' words. If the words still need more, it grows past that line
// rather than cut them off.
function OpeningScene({ onUpgrade, ...shared }) {
  const { tutorial } = shared
  const { stage, stage_data: data } = tutorial
  const welcome = stage === 'title'
  const exercise = stage === 'upgrade'
  const interactive = exercise && tutorial.wait === 'upgrade'

  const panelRef = useRef(null)
  const edges = useTopEdges('.me-boxes', panelRef)
  // Not on phones, where the box and card stack and the mat is far below.
  const stacked = window.innerWidth <= 640
  const reachMat = !welcome && !stacked && edges && edges.target > edges.own ? { minHeight: edges.target - edges.own } : undefined

  // Scene 4's picker: the same click-a-gem picker MePanel/Board use
  // mid-upgrade (picks are caravan slot indices — see upgrade.js). Nothing
  // is judged here: Confirm sends the upgrade, the server's sandbox game
  // decides whether it met an objective, and `attempt` going up (the
  // caravan was reset) clears the picks.
  const steps = data?.card?.steps ?? 2
  const [active, setActive] = useState(false)
  const [picks, setPicks] = useState([])
  useEffect(() => {
    setActive(false)
    setPicks([])
  }, [data?.attempt, tutorial.id])
  const picking = interactive && active

  // Same rule as Board.jsx's handleUpgradePick: advance the clicked gem one
  // level while steps remain; once it can't go further (magenta, or no
  // steps left), clicking it walks back its own last step instead.
  function handlePick(slotIndex) {
    const color = slotColorAfterPicks(data.caravan, picks, slotIndex)
    if (color && color !== 'M' && picks.length < steps) {
      setPicks([...picks, slotIndex])
      return
    }
    const last = picks.lastIndexOf(slotIndex)
    if (last === -1) return
    const next = [...picks]
    next.splice(last, 1)
    setPicks(next)
  }

  let body
  if (!welcome) {
    const current = { id: tutorial.id, title: tutorial.title, paragraphs: tutorial.paragraphs }
    const sections = [...(tutorial.earlier ?? data.earlier ?? []), current]
    const caravan = (
      <div className="tut-opening-caravan" key="caravan-grid">
        <div className="tut-pop">
          <CaravanGrid
            bundle={data.caravan}
            picks={picking ? picks : undefined}
            onSlotClick={picking ? handlePick : undefined}
          />
        </div>
        {/* Beside the caravan rather than above it, so starting to pick
            never moves anything. */}
        {interactive && (
          <div className="tut-caravan-controls">
            {picking && (
              <div className="tut-caravan-buttons">
                <button
                  type="button"
                  className="upgrade-confirm-btn"
                  disabled={picks.length !== steps}
                  onClick={() => onUpgrade(picksToColors(data.caravan, picks))}
                >
                  Confirm
                </button>
                <button
                  type="button"
                  className="upgrade-cancel-btn"
                  aria-label="Cancel upgrade"
                  title="Cancel"
                  onClick={() => {
                    setPicks([])
                    setActive(false)
                  }}
                >
                  ×
                </button>
              </div>
            )}
            <span className="caravan-hint tut-hint">
              {!active ? 'Click the Double Upgrade' : picks.length < steps ? 'Click gems to upgrade' : 'Now Confirm'}
            </span>
            {/* How the last try went, here beside the caravan it was made
                on, rather than as a strip that would grow the box. */}
            {tutorial.feedback && !active && (
              <span className={`tut-inline-feedback ${tutorial.feedback.ok ? 'tut-inline-ok' : 'tut-inline-bad'}`}>
                {tutorial.feedback.text}
              </span>
            )}
          </div>
        )}
      </div>
    )
    // Once they're all done and the page has moved on to the recap, the
    // three ticks fold into one line — the recap says the rest.
    const folded = tutorial.id !== 'upgrade' && data.objectives?.every((o) => o.done)
    const objectives = data.objectives && (
      <ul className="tut-objectives" key="objectives">
        {folded ? (
          <li className="tut-objective-done">All three done.</li>
        ) : (
          data.objectives.map((o) => (
            <li key={o.text} className={o.done ? 'tut-objective-done' : undefined}>
              {o.text}
            </li>
          ))
        )}
      </ul>
    )
    // The objectives go under scene 4's words; if no section says it's
    // scene 4's (a server from before `id` was sent), under the last one, so
    // they're never silently missing.
    const objectivesAfter = sections.some((s) => s.id === 'upgrade') ? 'upgrade' : sections[sections.length - 1].id
    const parts = []
    if (!sections.some((s) => s.id === 'caravan')) parts.push(caravan)
    for (const s of sections) {
      parts.push(<PageSection key={s.id ?? 'current'} section={s} className={s === current && sections.length > 1 ? 'tut-pop' : ''} />)
      if (s.id === 'caravan') parts.push(caravan)
      if (objectives && s.id === objectivesAfter) parts.push(objectives)
    }
    body = <>{parts}</>
  }

  const showCard = stage === 'order' || exercise
  return (
    <div className={`tut-stage tut-opening${welcome ? ' tut-opening-welcome' : ''}`}>
      <div className="tut-opening-row">
        <div
          key={welcome ? 'welcome' : 'building'}
          ref={panelRef}
          style={reachMat}
          className={`tut-stage-panel tut-page tut-opening-panel${welcome ? '' : ' tut-pop'}`}
        >
          <StepText {...shared} body={body} showFeedback={false} />
        </div>
        <div className="tut-opening-side">
          {showCard && (
            <figure className={`tut-opening-card tut-pop${interactive && !active ? ' tut-attention' : ''}`}>
              <MerchantCard card={data.card} onClick={interactive ? () => setActive(true) : undefined} />
              <figcaption>{data.card.name}</figcaption>
            </figure>
          )}
        </div>
      </div>
    </div>
  )
}

// Scene 8, laid out like the opening: the box where the opening box was,
// sized to its words — one short block per kind of card — and the three
// cards side by side to its right, each named underneath, in the same order
// as the blocks.
function CardsScene(shared) {
  const { tutorial } = shared
  const showcase = tutorial.stage_data.cards
  const body = (
    <>
      <PageSection section={{ title: tutorial.title, paragraphs: tutorial.paragraphs }} />
      <div className="tut-kinds">
        {showcase.map((c) => (
          <div key={c.heading} className="tut-kind">
            <h3 className="tut-subtitle">{c.heading}</h3>
            <p className="tut-text">{c.text}</p>
          </div>
        ))}
      </div>
    </>
  )
  return (
    <div className="tut-stage tut-opening tut-cards-scene">
      <div className="tut-opening-row">
        <div className="tut-stage-panel tut-page tut-opening-panel tut-cards-panel tut-pop">
          <StepText {...shared} body={body} />
        </div>
        <div className="tut-cards-side">
          {showcase.map((c, i) => (
            <figure key={c.heading} className="tut-opening-card tut-pop" style={{ animationDelay: `${i * 90}ms` }}>
              <MerchantCard card={c.card} />
              <figcaption>{c.heading}</figcaption>
            </figure>
          ))}
        </div>
      </div>
    </div>
  )
}

function StagedScreen({ onUpgrade, ...shared }) {
  const { stage } = shared.tutorial
  if (OPENING_STAGES.has(stage)) return <OpeningScene {...shared} onUpgrade={onUpgrade} />
  if (stage === 'cards') return <CardsScene {...shared} />
  return (
    <div className="tut-stage">
      <div className="tut-stage-panel tut-page">
        <StepText {...shared} />
      </div>
    </div>
  )
}

// The board steps: the live board, a ring around the part the words are
// about, and the same page box as the staged screens, placed against
// `anchor` — a fixed part of the board (the merchant row, the player's mat,
// the golem row) rather than the ring itself, so when two steps share a box
// the box holds still while the ring moves within its part of the board.
function BoardCoach(shared) {
  const { tutorial, error } = shared
  const rect = useHighlightRect(tutorial.highlight, tutorial.highlight_slot)
  const anchorRect = useHighlightRect(tutorial.anchor ?? null)
  const reading = tutorial.wait === 'next' || tutorial.wait === 'busy'
  const freePlay = tutorial.wait === 'free_play'

  // Scene 11 hands the board over — the box folds away into a pill so it
  // doesn't sit on top of the game, and comes back on a click.
  const [collapsed, setCollapsed] = useState(false)
  useEffect(() => setCollapsed(false), [tutorial.step])

  const bubbleRef = useRef(null)
  const [pos, setPos] = useState(null)
  useLayoutEffect(() => {
    function place() {
      const el = bubbleRef.current
      if (!el) return
      setPos(placeBubble(anchorRect, el.offsetWidth, el.offsetHeight))
    }
    place()
    window.addEventListener('resize', place)
    return () => window.removeEventListener('resize', place)
  }, [anchorRect, tutorial.step, tutorial.wait, collapsed])

  if (freePlay && collapsed) {
    return (
      <button type="button" className="tut-pill" onClick={() => setCollapsed(false)}>
        Tutorial · finish the game
      </button>
    )
  }

  // A refusal on the step that wants a move replaces its instruction; any
  // other shows as a strip.
  const inline = Boolean(tutorial.instruction)
  return (
    <>
      {reading && <div className="tut-blocker" />}
      {rect && (
        <div
          className={[
            'tut-ring',
            tutorial.highlight === 'merchant_card' && 'tut-ring-circle',
            reading && 'tut-ring-dim',
          ]
            .filter(Boolean)
            .join(' ')}
          style={rect}
        />
      )}
      <div
        ref={bubbleRef}
        className="tut-page tut-bubble"
        style={pos ? { top: pos.top, left: pos.left } : { visibility: 'hidden' }}
        role="dialog"
        aria-label={tutorial.title}
      >
        <StepText
          {...shared}
          error={inline ? null : error}
          body={<>{pageSections(tutorial, inline ? error : null)}</>}
          extraButton={
            freePlay ? (
              <button type="button" className="tut-next" onClick={() => setCollapsed(true)}>
                Let's go
              </button>
            ) : null
          }
        />
      </div>
    </>
  )
}

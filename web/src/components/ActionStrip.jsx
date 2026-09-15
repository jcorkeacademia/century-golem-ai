// The reserved strip for sub-decision prompts: errors and (if the server
// ever sends one) a pending server-side decision. The upgrade builder used
// to live here too (a "Playing upgrade ... Confirm/Undo/Cancel" bar), but
// that's now folded straight into the caravan box it actually refers to
// (see MePanel.jsx's .upgrade-confirm-row) instead of a separate strip down
// here — Trade/Claim already have their own centred dialogs, and acquire
// payments are staged by dragging onto the merchant row itself
// (CenterBoard.jsx), so this strip is down to error/pending-decision only.
export default function ActionStrip({ state, lastError, onDismissError }) {
  if (!lastError && !state.pending_decision) return null

  return (
    <div className="action-strip">
      {lastError && (
        <div className="error-banner">
          [{lastError.code}] {lastError.message}
          <button className="dismiss-error" onClick={onDismissError}>
            ×
          </button>
        </div>
      )}

      {state.pending_decision && (
        <div className="pending-decision-banner">
          Pending decision from server: {JSON.stringify(state.pending_decision)}
        </div>
      )}
    </div>
  )
}

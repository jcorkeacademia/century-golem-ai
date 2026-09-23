"""Solo solver for Century: Golem Edition.

One question: from a known board, with no opponent, what is the *fewest*
turns to claim `win_target` golems? See the solo-solver handover.

This is a separate track from `bots/`. `bots/` plays multiplayer games well
by heuristic; this package searches for a provably shortest line. The two
share the engine and nothing else — except `bots._engine`, which is the one
place in the repo that knows how to put `engine/` on `sys.path`.

Run from the repo root, e.g. `python -m solver.solo`.
"""

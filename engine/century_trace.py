"""
Century engine — step-by-step tracer
====================================

Plays a game through the engine and prints the FULL state after every action,
so you can read down the log and confirm each rule fires correctly.

Run:  python3 century_trace.py
Use a fixed seed for a reproducible trace; change the policy to script moves.
"""

from __future__ import annotations
from century_engine import (
    Game, Crystal, Player,
    CrystalCard, UpgradeCard, TradeCard, PointCard, Token,
    PlayCrystal, PlayUpgrade, PlayTrade, Acquire, Rest, Claim,
)

SYM = {Crystal.YELLOW: "Y", Crystal.GREEN: "G", Crystal.TURQUOISE: "T", Crystal.MAGENTA: "M"}


# ---------- readable formatting ----------
def fmt_caravan(car: list[int]) -> str:
    parts = [f"{n}{SYM[Crystal(i)]}" for i, n in enumerate(car) if n]
    return " ".join(parts) if parts else "(empty)"

def fmt_counter(counter) -> str:
    parts = [f"{n}{SYM[c]}" for c, n in counter.items() if n]
    return "+".join(parts) if parts else "-"

def card_name(card) -> str:
    if card is None:
        return "·"
    if card.name:
        return card.name
    if isinstance(card, CrystalCard):
        return "Crystal:" + fmt_counter(card.as_counter())
    if isinstance(card, UpgradeCard):
        return f"Upgrade{card.steps}"
    if isinstance(card, TradeCard):
        return f"{fmt_counter(card.cost_counter())}->{fmt_counter(card.gain_counter())}"
    if isinstance(card, PointCard):
        return f"[{fmt_counter(card.cost_counter())}={card.points}pt]"
    return "?"


def describe_action(g: Game, a) -> str:
    p = g.player
    if isinstance(a, PlayCrystal):
        c = p.hand[a.hand_index]
        return f"PLAY crystal '{card_name(c)}'"
    if isinstance(a, PlayUpgrade):
        c = p.hand[a.hand_index]
        steps = ", ".join(f"{SYM[u]}->{SYM[Crystal(u+1)]}" for u in a.upgrades) or "(none)"
        return f"PLAY '{card_name(c)}' upgrades: {steps}"
    if isinstance(a, PlayTrade):
        c = p.hand[a.hand_index]
        return f"PLAY trade '{card_name(c)}' x{a.times}"
    if isinstance(a, Acquire):
        c = g.merchant_row[a.row_index]
        pay = " ".join(SYM[x] for x in a.payment) or "FREE"
        return f"ACQUIRE row[{a.row_index}] '{card_name(c)}'  pay onto left: {pay}"
    if isinstance(a, Rest):
        return f"REST (recall {len(p.played)} card(s))"
    if isinstance(a, Claim):
        c = g.point_row[a.row_index]
        return f"CLAIM point[{a.row_index}] '{card_name(c)}'"
    return str(a)


def print_state(g: Game) -> None:
    # Board
    prow = "  ".join(f"[{i}]{card_name(c)}" for i, c in enumerate(g.point_row))
    toks = " ".join(
        f"slot{i}:{','.join(t.name[0] for t in pile)}"
        for i, pile in enumerate(g.point_tokens) if pile
    )
    mrow = "  ".join(
        f"[{i}]{card_name(c)}"
        + (f"{{{fmt_counter(cr)}}}" if cr else "")
        for i, (c, cr) in enumerate(zip(g.merchant_row, g.row_crystals))
    )
    print(f"    POINT ROW : {prow}")
    print(f"    TOKENS    : {toks or '(none)'}   (point deck: {len(g.point_deck)})")
    print(f"    MERCH ROW : {mrow}   (merch deck: {len(g.merchant_deck)})")
    # Players
    for idx, pl in enumerate(g.players):
        marker = ">" if idx == g.current else " "
        hand = ", ".join(card_name(c) for c in pl.hand) or "-"
        played = ", ".join(card_name(c) for c in pl.played) or "-"
        tk = f"{sum(1 for t in pl.tokens if t==Token.COPPER)}c/{sum(1 for t in pl.tokens if t==Token.SILVER)}s"
        print(f"   {marker}{pl.name:<6} caravan[{pl.total_crystals():2}/10]: {fmt_caravan(pl.caravan):<16}"
              f" pts:{len(pl.point_cards)} tok:{tk} score:{pl.score()}")
        print(f"       hand: {hand}")
        if pl.played:
            print(f"       played: {played}")


# ---------- a simple, legible greedy policy ----------
def greedy(g: Game):
    acts = g.legal_actions()
    # 1) claim the highest-value point card available
    claims = [a for a in acts if isinstance(a, Claim)]
    if claims:
        return max(claims, key=lambda a: g.point_row[a.row_index].points)
    # 2) if hand is empty of plays, rest
    plays = [a for a in acts if isinstance(a, (PlayCrystal, PlayUpgrade, PlayTrade))]
    rests = [a for a in acts if isinstance(a, Rest)]
    if not plays and rests:
        return rests[0]
    # 3) otherwise take a free/cheap acquire, else the first play, else anything
    acquires = sorted((a for a in acts if isinstance(a, Acquire)), key=lambda a: a.row_index)
    if acquires and g.rng.random() < 0.4:
        return acquires[0]
    if plays:
        return plays[0]
    return acts[0]


def run(names=("Alice", "Bob"), seed=7, max_turns=60):
    g = Game(list(names), seed=seed)
    print("=" * 78)
    print(f"NEW GAME  players={names}  seed={seed}  win_target={g.win_target}")
    print("=" * 78)
    print("INITIAL STATE")
    print_state(g)

    turn = 0
    while not g.game_over and turn < max_turns:
        turn += 1
        actor = g.player.name
        acts = g.legal_actions()
        if not acts:
            print(f"\n-- turn {turn}: {actor} has no legal actions; stopping.")
            break
        a = greedy(g)
        print(f"\n--- TURN {turn} | {actor} | legal moves: {len(acts)} ---")
        print(f"    ACTION: {describe_action(g, a)}")
        g.apply_action(a)
        print_state(g)

    print("\n" + "=" * 78)
    print(f"GAME OVER: {g.game_over}  (after {turn} turns)")
    print("FINAL SCORES:", g.scores())
    print("WINNER:", g.winner())
    print("=" * 78)


if __name__ == "__main__":
    run()
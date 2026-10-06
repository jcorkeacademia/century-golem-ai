"""
card_art.py -- join the generated card images to the engine's card objects.

The image slots are sorted by value; century_cards.py is in its own order.
So the join is on card CONTENT, never on list position. Any card that fails
to match is a transcription disagreement between the two sources, which is
exactly what verify() reports.

    import century_cards as C, card_art
    card_art.art_for(C.POINT_CARDS[0])
    -> WindowsPath('out/golem_01_6pts.png')

    python3 card_art.py          # run the audit
"""

from collections import Counter
from pathlib import Path

from century_engine import (
    Crystal, CrystalCard, UpgradeCard, TradeCard, PointCard,
)

# --------------------------------------------------------------------------
# Where the rendered cards live. Adjust if you moved them.
# --------------------------------------------------------------------------
ROOT       = Path(__file__).parent
GOLEM_DIR  = ROOT / "out"
MERCH_DIR  = ROOT / "out_merchants"
# Painted set for the DEFAULT room (make_cards.py / make_merchants.py
# --set gol) -- same filenames as GOLEM_DIR / MERCH_DIR.
GOL_GOLEM_DIR = ROOT.parent / "gol" / "out"
GOL_MERCH_DIR = ROOT.parent / "gol" / "out_merchants"

# Letter keys used by the art scripts -> engine crystals.
# NOTE: "B" is the physical blue crystal, which the engine calls TURQUOISE.
KEY = {"Y": Crystal.YELLOW, "G": Crystal.GREEN,
       "B": Crystal.TURQUOISE, "M": Crystal.MAGENTA}


def norm(d):
    """Letter dict -> frozen multiset of (Crystal, count), order-independent."""
    return frozenset((KEY[k], n) for k, n in d.items() if n)


def norm_tuples(pairs):
    """Engine (Crystal, count) tuples -> the same frozen multiset."""
    c = Counter()
    for crystal, n in pairs:
        c[crystal] += n
    return frozenset(c.items())


# --------------------------------------------------------------------------
# GOLEM SLOTS -- must stay identical to GOLEMS in make_cards.py
# (points, cost) in the sorted order the images were rendered in.
# --------------------------------------------------------------------------
GOLEM_SLOTS = [
    (6,  {"Y": 2, "G": 2}),   (7,  {"Y": 3, "G": 2}),
    (8,  {"Y": 2, "B": 2}),   (8,  {"Y": 2, "G": 3}),
    (8,  {"G": 4}),           (9,  {"Y": 2, "G": 1, "M": 1}),
    (9,  {"Y": 3, "B": 2}),   (10, {"Y": 2, "M": 2}),
    (10, {"G": 2, "B": 2}),   (10, {"G": 5}),
    (11, {"Y": 3, "M": 2}),   (11, {"Y": 2, "B": 3}),
    (12, {"Y": 1, "G": 1, "B": 1, "M": 1}),
    (12, {"G": 2, "M": 2}),   (12, {"Y": 1, "B": 2, "M": 1}),
    (12, {"G": 2, "B": 1, "M": 1}),
    (12, {"G": 3, "B": 2}),   (12, {"B": 4}),
    (13, {"Y": 2, "G": 2, "B": 2}), (13, {"G": 2, "B": 3}),
    (14, {"Y": 3, "G": 1, "B": 1, "M": 1}),
    (14, {"Y": 2, "M": 3}),   (14, {"B": 2, "M": 2}),
    (14, {"G": 3, "M": 2}),   (15, {"Y": 2, "G": 2, "M": 2}),
    (15, {"B": 5}),
    (16, {"Y": 1, "G": 3, "B": 1, "M": 1}),
    (16, {"G": 2, "M": 3}),   (16, {"M": 4}),
    (17, {"Y": 2, "B": 2, "M": 2}), (17, {"B": 3, "M": 2}),
    (18, {"Y": 1, "G": 1, "B": 3, "M": 1}),
    (18, {"B": 2, "M": 3}),   (19, {"G": 2, "B": 2, "M": 2}),
    (20, {"Y": 1, "G": 1, "B": 1, "M": 3}), (20, {"M": 5}),
]

# --------------------------------------------------------------------------
# MERCHANT SLOTS -- must stay identical to MERCHANTS in make_merchants.py
# (kind, cost, gain, steps)
# --------------------------------------------------------------------------
MERCHANT_SLOTS = [
    ("crystal", {}, {"B": 1}, 0),
    ("crystal", {}, {"Y": 1, "G": 1}, 0),
    ("crystal", {}, {"Y": 3}, 0),
    ("crystal", {}, {"M": 1}, 0),
    ("crystal", {}, {"Y": 1, "B": 1}, 0),
    ("crystal", {}, {"G": 2}, 0),
    ("crystal", {}, {"Y": 2, "G": 1}, 0),
    ("crystal", {}, {"Y": 4}, 0),
    ("upgrade", {}, {}, 3),
    ("trade", {"G": 1}, {"Y": 3}, 0),
    ("trade", {"Y": 2}, {"B": 1}, 0),
    ("trade", {"B": 1}, {"G": 2}, 0),
    ("trade", {"Y": 1, "G": 1}, {"M": 1}, 0),
    ("trade", {"Y": 3}, {"M": 1}, 0),
    ("trade", {"Y": 2}, {"G": 2}, 0),
    ("trade", {"B": 1}, {"Y": 1, "G": 2}, 0),
    ("trade", {"Y": 3}, {"G": 1, "B": 1}, 0),
    ("trade", {"M": 1}, {"Y": 1, "G": 1, "B": 1}, 0),
    ("trade", {"M": 1}, {"B": 2}, 0),
    ("trade", {"M": 1}, {"G": 3}, 0),
    ("trade", {"M": 1}, {"Y": 2, "G": 2}, 0),
    ("trade", {"M": 1}, {"Y": 3, "B": 1}, 0),
    ("trade", {"G": 2}, {"Y": 3, "B": 1}, 0),
    ("trade", {"G": 2}, {"Y": 2, "M": 1}, 0),
    ("trade", {"G": 2}, {"B": 2}, 0),
    ("trade", {"Y": 4}, {"B": 2}, 0),
    ("trade", {"B": 2}, {"M": 2}, 0),
    ("trade", {"B": 2}, {"Y": 2, "G": 1, "M": 1}, 0),
    ("trade", {"B": 2}, {"G": 2, "M": 1}, 0),
    ("trade", {"B": 2}, {"Y": 2, "G": 3}, 0),
    ("trade", {"G": 3}, {"M": 2}, 0),
    ("trade", {"G": 3}, {"Y": 1, "B": 1, "M": 1}, 0),
    ("trade", {"G": 3}, {"Y": 2, "B": 2}, 0),
    ("trade", {"B": 1}, {"Y": 4, "G": 1}, 0),
    ("trade", {"Y": 3}, {"G": 3}, 0),
    ("trade", {"Y": 4}, {"B": 1, "M": 1}, 0),
    ("trade", {"Y": 2, "B": 1}, {"M": 2}, 0),
    ("trade", {"Y": 5}, {"M": 2}, 0),
    ("trade", {"G": 3}, {"B": 3}, 0),
    ("trade", {"B": 3}, {"M": 3}, 0),
    ("trade", {"M": 2}, {"G": 3, "B": 2}, 0),
    ("trade", {"M": 2}, {"Y": 1, "G": 1, "B": 3}, 0),
    ("trade", {"Y": 5}, {"B": 3}, 0),
    ("crystal", {}, {"Y": 2}, 0),     # 44  Create 2  (starting card)
    ("upgrade", {}, {}, 2),           # 45  Upgrade 2 (starting card)
]


# --------------------------------------------------------------------------
# Signatures
# --------------------------------------------------------------------------
def slot_signature(kind, cost, gain, steps):
    if kind == "crystal":
        return ("crystal", norm(gain))
    if kind == "upgrade":
        return ("upgrade", steps)
    return ("trade", norm(cost), norm(gain))


def card_signature(card):
    if isinstance(card, CrystalCard):
        return ("crystal", norm_tuples(card.gain))
    if isinstance(card, UpgradeCard):
        return ("upgrade", card.steps)
    if isinstance(card, TradeCard):
        return ("trade", norm_tuples(card.cost), norm_tuples(card.gain))
    if isinstance(card, PointCard):
        return ("golem", card.points, norm_tuples(card.cost))
    raise TypeError(f"unknown card type: {type(card).__name__}")


def _find(directory, slot, patterns):
    for pat in patterns:
        hits = sorted(directory.glob(pat.format(slot=slot)))
        if hits:
            return hits[0]
    return None


def _build_index():
    """signature -> list of image paths. Lists, so duplicates stay visible."""
    idx = {}
    for i, (points, cost) in enumerate(GOLEM_SLOTS, 1):
        sig = ("golem", points, norm(cost))
        idx.setdefault(sig, []).append(
            _find(GOLEM_DIR, f"{i:02d}", ["golem_{slot}_*.png"]))
    for i, entry in enumerate(MERCHANT_SLOTS, 1):
        sig = slot_signature(*entry)
        idx.setdefault(sig, []).append(
            _find(MERCH_DIR, f"{i:02d}",
                  ["merchant_{slot}_*.png", "start_{slot}_*.png"]))
    return idx


ART = _build_index()


def art_for(card):
    """Image path for an engine card, or None if unmatched or unrendered."""
    hits = ART.get(card_signature(card))
    return hits[0] if hits else None


# --------------------------------------------------------------------------
def verify():
    import century_cards as C

    def describe(card):
        return getattr(card, "name", None) or repr(card)

    print("=" * 62)
    print("CARD ART AUDIT")
    print("=" * 62)

    problems = 0
    for label, cards in (("GOLEM", C.POINT_CARDS),
                         ("MERCHANT", C.MERCHANT_CARDS),
                         ("STARTING", C.STARTING_CARDS)):
        unmatched = [c for c in cards if card_signature(c) not in ART]
        norendered = [c for c in cards
                      if card_signature(c) in ART and art_for(c) is None]
        print(f"\n{label}: {len(cards)} card(s)")
        print(f"  matched to a slot : {len(cards) - len(unmatched)}")
        if unmatched:
            problems += len(unmatched)
            print("  NO MATCHING SLOT (transcription disagreement):")
            for c in unmatched:
                print(f"    - {describe(c)}")
        if norendered:
            print("  matched but image not found on disk:")
            for c in norendered:
                print(f"    - {describe(c)}")

    # slots with no engine card
    engine_sigs = Counter(card_signature(c) for c in
                          C.POINT_CARDS + C.MERCHANT_CARDS + C.STARTING_CARDS)
    orphans = []
    for i, (points, cost) in enumerate(GOLEM_SLOTS, 1):
        if ("golem", points, norm(cost)) not in engine_sigs:
            orphans.append(f"golem slot {i:02d}: {points} pts {cost}")
    for i, entry in enumerate(MERCHANT_SLOTS, 1):
        if slot_signature(*entry) not in engine_sigs:
            orphans.append(f"merchant slot {i:02d}: {entry[0]} {entry[1]}->{entry[2]}")
    if orphans:
        problems += len(orphans)
        print("\nIMAGE SLOTS WITH NO ENGINE CARD:")
        for o in orphans:
            print("  -", o)

    # duplicate signatures
    dups = {s: n for s, n in engine_sigs.items() if n > 1}
    if dups:
        print(f"\nDUPLICATE CARDS IN century_cards.py: {len(dups)} signature(s)")
        print("  (content join cannot tell these apart; they share one image)")

    print("\n" + "=" * 62)
    print("RESULT:", "OK -- both sources agree" if not problems
          else f"{problems} DISAGREEMENT(S) -- see above")
    print("=" * 62)
    return problems


if __name__ == "__main__":
    raise SystemExit(1 if verify() else 0)

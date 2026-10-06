"""
Century: Golem Edition — CARD COMPENDIUM  (fully transcribed)
============================================================
Source: user's card list. Blue (B) == the engine's TURQUOISE crystal.

Plug into the engine:
    import century_engine as E, century_cards as C
    E.MERCHANT_DECK = C.MERCHANT_CARDS
    E.POINT_DECK    = C.POINT_CARDS

Validate / see stats:  python3 century_cards.py

Crystals:  Y=Yellow  G=Green  B=Blue(=engine TURQUOISE)  M=Magenta
Starting cards (dealt at setup, NOT in the merchant deck): +2Y and double upgrade.
"""

from collections import Counter
from century_engine import (
    Crystal, CrystalCard, UpgradeCard, TradeCard, PointCard,
)

Y, G, B, M = Crystal.YELLOW, Crystal.GREEN, Crystal.TURQUOISE, Crystal.MAGENTA

# Each player starts with one of each of these (engine deals them at setup).
STARTING_CARDS = [
    CrystalCard(((Y, 2),), "Create 2 (+2Y)"),
    UpgradeCard(2, "Double upgrade"),
]

# ==========================================================================
# MERCHANT DECK — 43 cards
#   "+X"    -> CrystalCard (gain)
#   "A->B"  -> TradeCard (pay A, gain B, repeatable)
#   upgrade -> UpgradeCard
# ==========================================================================
MERCHANT_CARDS = [
    TradeCard(((Y, 3),), ((M, 1),), "3Y->1M"),                       # 1
    TradeCard(((G, 3),), ((M, 2),), "3G->2M"),                       # 2
    TradeCard(((G, 2),), ((B, 1), (Y, 3)), "2G->1B3Y"),              # 3
    TradeCard(((M, 1),), ((B, 1), (G, 1), (Y, 1)), "1M->1B1G1Y"),    # 4
    TradeCard(((G, 1),), ((Y, 3),), "1G->3Y"),                       # 5
    CrystalCard(((G, 2),), "+2G"),                                   # 6
    TradeCard(((M, 2),), ((B, 2), (G, 3)), "2M->2B3G"),              # 7
    CrystalCard(((B, 1), (Y, 1)), "+1B1Y"),                          # 8
    TradeCard(((Y, 4),), ((B, 2),), "4Y->2B"),                       # 9
    TradeCard(((Y, 3),), ((G, 3),), "3Y->3G"),                       # 10
    TradeCard(((M, 1),), ((B, 2),), "1M->2B"),                       # 11
    TradeCard(((M, 2),), ((B, 3), (G, 1), (Y, 1)), "2M->3B1G1Y"),    # 12
    UpgradeCard(3, "Triple upgrade"),                                # 13
    TradeCard(((G, 2),), ((M, 1), (Y, 2)), "2G->1M2Y"),              # 14
    TradeCard(((G, 3),), ((M, 1), (B, 1), (Y, 1)), "3G->1M1B1Y"),    # 15
    TradeCard(((Y, 2),), ((B, 1),), "2Y->1B"),                       # 16
    TradeCard(((B, 2),), ((M, 2),), "2B->2M"),                       # 17
    TradeCard(((B, 2),), ((M, 1), (G, 1), (Y, 2)), "2B->1M1G2Y"),    # 18
    TradeCard(((B, 2),), ((M, 1), (G, 2)), "2B->1M2G"),              # 19
    TradeCard(((B, 3),), ((M, 3),), "3B->3M"),                       # 20
    TradeCard(((G, 3),), ((B, 3),), "3G->3B"),                       # 21
    TradeCard(((B, 2),), ((G, 3), (Y, 2)), "2B->3G2Y"),              # 22
    TradeCard(((Y, 4),), ((M, 1), (B, 1)), "4Y->1M1B"),              # 23
    TradeCard(((M, 1),), ((G, 3),), "1M->3G"),                       # 24
    TradeCard(((M, 1),), ((G, 2), (Y, 2)), "1M->2G2Y"),              # 25
    TradeCard(((Y, 3),), ((G, 1), (B, 1)), "3Y->1G1B"),              # 26
    TradeCard(((B, 1),), ((G, 1), (Y, 4)), "1B->1G4Y"),              # 27
    CrystalCard(((M, 1),), "+1M"),                                   # 28
    TradeCard(((Y, 5),), ((M, 2),), "5Y->2M"),                       # 29
    TradeCard(((G, 2),), ((B, 2),), "2G->2B"),                       # 30
    TradeCard(((B, 1),), ((G, 2), (Y, 1)), "1B->2G1Y"),              # 31
    TradeCard(((G, 3),), ((B, 2), (Y, 2)), "3G->2B2Y"),              # 32
    TradeCard(((B, 1),), ((G, 2),), "1B->2G"),                       # 33
    TradeCard(((M, 1),), ((B, 1), (Y, 3)), "1M->1B3Y"),              # 34
    TradeCard(((G, 1), (Y, 1)), ((M, 1),), "1G1Y->1M"),              # 35
    CrystalCard(((Y, 3),), "+3Y"),                                   # 36
    TradeCard(((Y, 5),), ((B, 3),), "5Y->3B"),                       # 37
    CrystalCard(((Y, 4),), "+4Y"),                                   # 38
    TradeCard(((B, 1), (Y, 2)), ((M, 2),), "1B2Y->2M"),              # 39
    CrystalCard(((G, 1), (Y, 2)), "+1G2Y"),                          # 40
    TradeCard(((Y, 2),), ((G, 2),), "2Y->2G"),                       # 41
    CrystalCard(((G, 1), (Y, 1)), "+1G1Y"),                          # 42
    CrystalCard(((B, 1),), "+1B"),                                   # 43
]

# ==========================================================================
# POINT / GOLEM DECK — 36 cards   (points : crystal cost)
# ==========================================================================
POINT_CARDS = [
    PointCard(((Y, 2), (G, 2)), 6, "2Y2G=6"),                        # 1
    PointCard(((B, 4),), 12, "4B=12"),                               # 2
    PointCard(((Y, 2), (B, 2)), 8, "2Y2B=8"),                        # 3
    PointCard(((G, 2), (B, 3)), 13, "2G3B=13"),                      # 4
    PointCard(((Y, 3), (M, 2)), 11, "3Y2M=11"),                      # 5
    PointCard(((G, 2), (B, 2)), 10, "2G2B=10"),                      # 6
    PointCard(((G, 5),), 10, "5G=10"),                               # 7
    PointCard(((M, 5),), 20, "5M=20"),                               # 8
    PointCard(((M, 1), (B, 2), (Y, 1)), 12, "1M2B1Y=12"),            # 9
    PointCard(((Y, 3), (G, 1), (B, 1), (M, 1)), 14, "3Y1G1B1M=14"),  # 10
    PointCard(((Y, 1), (G, 3), (B, 1), (M, 1)), 16, "1Y3G1B1M=16"),  # 11
    PointCard(((G, 2), (B, 2), (M, 2)), 19, "2G2B2M=19"),            # 12
    PointCard(((G, 3), (M, 2)), 14, "3G2M=14"),                      # 13
    PointCard(((B, 2), (M, 3)), 18, "2B3M=18"),                      # 14
    PointCard(((G, 3), (B, 2)), 12, "3G2B=12"),                      # 15
    PointCard(((B, 5),), 15, "5B=15"),                               # 16
    PointCard(((Y, 2), (G, 1), (M, 1)), 9, "2Y1G1M=9"),              # 17
    PointCard(((B, 3), (M, 2)), 17, "3B2M=17"),                      # 18
    PointCard(((G, 2), (M, 2)), 12, "2G2M=12"),                      # 19
    PointCard(((Y, 1), (G, 1), (B, 1), (M, 3)), 20, "1Y1G1B3M=20"),  # 20
    PointCard(((Y, 2), (M, 3)), 14, "2Y3M=14"),                      # 21
    PointCard(((Y, 3), (G, 2)), 7, "3Y2G=7"),                        # 22
    PointCard(((Y, 1), (G, 1), (B, 3), (M, 1)), 18, "1Y1G3B1M=18"),  # 23
    PointCard(((M, 4),), 16, "4M=16"),                               # 24
    PointCard(((Y, 2), (G, 2), (B, 2)), 13, "2Y2G2B=13"),            # 25
    PointCard(((B, 2), (M, 2)), 14, "2B2M=14"),                      # 26
    PointCard(((Y, 2), (G, 2), (M, 2)), 15, "2Y2G2M=15"),            # 27
    PointCard(((Y, 3), (B, 2)), 9, "3Y2B=9"),                        # 28
    PointCard(((Y, 2), (M, 2)), 10, "2Y2M=10"),                      # 29
    PointCard(((G, 2), (B, 1), (M, 1)), 12, "2G1B1M=12"),            # 30
    PointCard(((G, 2), (M, 3)), 16, "2G3M=16"),                      # 31
    PointCard(((Y, 2), (B, 2), (M, 2)), 17, "2Y2B2M=17"),            # 32
    PointCard(((Y, 2), (G, 3)), 8, "2Y3G=8"),                        # 33
    PointCard(((G, 4),), 8, "4G=8"),                                 # 34
    PointCard(((Y, 2), (B, 3)), 11, "2Y3B=11"),                      # 35
    PointCard(((Y, 1), (G, 1), (B, 1), (M, 1)), 12, "1Y1G1B1M=12"),  # 36
]

EXPECTED_MERCHANT_COUNT = 43
EXPECTED_POINT_COUNT = 36


def _kind(card):
    return type(card).__name__.replace("Card", "")


def validate():
    print("MERCHANT DECK")
    kinds = Counter(_kind(c) for c in MERCHANT_CARDS)
    for k, v in sorted(kinds.items()):
        print(f"  {k:<8}: {v}")
    print(f"  TOTAL   : {len(MERCHANT_CARDS)}  (expected {EXPECTED_MERCHANT_COUNT})")

    print("\nPOINT / GOLEM DECK")
    pts = [c.points for c in POINT_CARDS]
    print(f"  TOTAL   : {len(POINT_CARDS)}  (expected {EXPECTED_POINT_COUNT})")
    print(f"  points  : min {min(pts)}  max {max(pts)}  avg {sum(pts)/len(pts):.1f}")

    problems = []
    if len(MERCHANT_CARDS) != EXPECTED_MERCHANT_COUNT:
        problems.append("merchant count mismatch")
    if len(POINT_CARDS) != EXPECTED_POINT_COUNT:
        problems.append("point count mismatch")
    for c in POINT_CARDS:
        if c.points <= 0 or not c.cost:
            problems.append(f"bad point card {c.name}")
    print("\nCHECKS:", "OK" if not problems else "PROBLEMS")
    for p in problems:
        print("  !!", p)


def crystal_frequency():
    """How often each color appears across card costs and gains — useful for
    balance intuition and later AI weighting."""
    sym = {Y: "Y", G: "G", B: "B(turq)", M: "M"}
    gains = Counter(); costs = Counter()
    for c in MERCHANT_CARDS:
        if isinstance(c, CrystalCard):
            gains.update(c.as_counter())
        elif isinstance(c, TradeCard):
            costs.update(c.cost_counter()); gains.update(c.gain_counter())
    golem = Counter()
    for c in POINT_CARDS:
        golem.update(c.cost_counter())

    print("\nCRYSTAL FREQUENCY (total across all cards)")
    print("  merchant trade/gain COSTS :", {sym[k]: costs[k] for k in (Y, G, B, M)})
    print("  merchant trade/gain GAINS :", {sym[k]: gains[k] for k in (Y, G, B, M)})
    print("  golem card COSTS          :", {sym[k]: golem[k] for k in (Y, G, B, M)})


if __name__ == "__main__":
    validate()
    crystal_frequency()

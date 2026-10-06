#!/usr/bin/env python3
"""
Cut merchant card art out of photos of the real cards, for the DEFAULT room.

Reads ../mer/*.jpeg (one card per photo, on any table), writes the bare
illustration -- no table, no grey frame, printed conversion strip painted
out -- to ../gol/merchant_backgrounds/, ready for

    python make_merchants.py --set gol

which stamps the conversions from MERCHANTS back on. Which photo is which
card lives in ../gol/merchants.csv; the conversions come from this repo,
never from the photo.

    python extract_merchants.py            all photos
    python extract_merchants.py IMG_1983   just these (stems)

Per photo:
  1. GrabCut finds the card roughly (the table is textured, so plain edge
     detection doesn't work).
  2. A fixed-aspect rectangle is snapped onto the illustration's printed
     edge, skipping the stretch where the strip's own edges would pull it off.
  3. Warp flat; landscape photos are turned upright (strip top-left).
  4. The printed strip is painted out. It's a fixed printed layout, so its
     length follows from what it prints (the "printed" column of
     merchants.csv -- the photo's own conversion, which can differ from the
     engine's). That length goes in strips.csv so the new strip can cover
     the same span.
Exact duplicate photos are skipped.
"""

import csv
import hashlib
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).parent
SRC = ROOT.parent / "mer"
OUT = ROOT.parent / "gol" / "merchant_backgrounds"
DEBUG = OUT / "_debug"
MAPPING = ROOT.parent / "gol" / "merchants.csv"

AR = 0.545            # illustration short/long side, measured on the cards
OUT_W = 1100
OUT_H = round(OUT_W / AR)
INSET_X = 0.02        # trims the hairline of silver frame the fit can leave
INSET_Y = 0.01
IMG_EXT = (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG")


# --------------------------------------------------------------------------
# 1. rough box
# --------------------------------------------------------------------------
def rough_box(im, k=6):
    sm = cv2.resize(im, (im.shape[1] // k, im.shape[0] // k), interpolation=cv2.INTER_AREA)
    H, W = sm.shape[:2]
    m = int(min(H, W) * 0.03)
    mask = np.zeros((H, W), np.uint8)
    cv2.grabCut(sm, mask, (m, m, W - 2 * m, H - 2 * m),
                np.zeros((1, 65)), np.zeros((1, 65)), 6, cv2.GC_INIT_WITH_RECT)
    fg = np.where((mask == 1) | (mask == 3), 255, 0).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(fg)
    i = 1 + np.argmax(st[1:, cv2.CC_STAT_AREA])
    cs, _ = cv2.findContours(np.where(lab == i, 255, 0).astype(np.uint8),
                             cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    (cx, cy), (bw, bh), a = cv2.minAreaRect(cv2.convexHull(cs[0]))
    return cx * k, cy * k, bw * k, bh * k, a


# --------------------------------------------------------------------------
# 2. snap a fixed-aspect rectangle onto the illustration edge
# --------------------------------------------------------------------------
K = 3
FULL = np.linspace(0.08, 0.92, 60)      # corners are rounded, skip them
# Sides in IMAGE coords: top, bottom, left, right (params left->right,
# top->bottom). The strip hangs from the card's top edge down its left edge;
# landscape photos hold the card turned 90 deg clockwise, so there its top is
# the image's right side and its left side the image's top.
SIDE_T = {
    True:  [np.linspace(0.30, 0.92, 60), FULL, np.linspace(0.82, 0.94, 60), FULL],
    False: [np.linspace(0.06, 0.18, 60), FULL, FULL, np.linspace(0.30, 0.92, 60)],
}


def edge_score(gx, gy, cx, cy, w, ang, portrait):
    """Vectorised over candidates: median normal-gradient along each side."""
    h = w / AR
    Wr, Hr = (w, h) if portrait else (h, w)
    c, s = np.cos(ang), np.sin(ang)
    Hh, Ww = gx.shape
    per = []
    for side in range(4):
        if side == 0:   ox, oy, L, d, n = -Wr / 2, -Hr / 2, Wr, (c, s), (-s, c)
        elif side == 1: ox, oy, L, d, n = -Wr / 2,  Hr / 2, Wr, (c, s), (-s, c)
        elif side == 2: ox, oy, L, d, n = -Wr / 2, -Hr / 2, Hr, (-s, c), (c, s)
        else:           ox, oy, L, d, n =  Wr / 2, -Hr / 2, Hr, (-s, c), (c, s)
        T = SIDE_T[portrait][side]
        sx = cx + ox * c - oy * s
        sy = cy + ox * s + oy * c
        px = sx[:, None] + (L[:, None] * T[None]) * np.atleast_1d(d[0])[:, None]
        py = sy[:, None] + (L[:, None] * T[None]) * np.atleast_1d(d[1])[:, None]
        xi = np.clip(px.round().astype(int), 0, Ww - 1)
        yi = np.clip(py.round().astype(int), 0, Hh - 1)
        v = np.abs(gx[yi, xi] * np.atleast_1d(n[0])[:, None] + gy[yi, xi] * np.atleast_1d(n[1])[:, None])
        per.append(np.median(v, axis=1))
    per = np.array(per)
    return per.mean(0) + per.min(0)


def snap(im, rough):
    sm = cv2.resize(im, (im.shape[1] // K, im.shape[0] // K), interpolation=cv2.INTER_AREA)
    g = cv2.GaussianBlur(cv2.cvtColor(sm, cv2.COLOR_BGR2GRAY).astype(np.float32), (3, 3), 0)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)

    cx, cy, bw, bh, a = rough
    cx, cy, bw, bh = cx / K, cy / K, bw / K, bh / K
    if a > 45: a -= 90; bw, bh = bh, bw
    if a < -45: a += 90; bw, bh = bh, bw
    portrait = bool(bh > bw)
    w0 = min(bw, bh) * 0.93                  # GrabCut boxes run a little large
    a0 = np.radians(a)

    # coarse grid over centre and size, then local descent incl. angle
    X, Y, S = np.meshgrid(np.linspace(-.15, .15, 31), np.linspace(-.15, .15, 31),
                          np.linspace(.75, 1.15, 41), indexing="ij")
    C = [cx + X.ravel() * w0, cy + Y.ravel() * w0, w0 * S.ravel()]
    sc = np.concatenate([
        edge_score(gx, gy, C[0][i:i + 4000], C[1][i:i + 4000], C[2][i:i + 4000],
                   np.full(len(C[0][i:i + 4000]), a0), portrait)
        for i in range(0, len(C[0]), 4000)])
    i = sc.argmax()
    best = np.array([C[0][i], C[1][i], C[2][i], a0]); best_sc = sc[i]
    step = np.array([0.01 * w0, 0.01 * w0, 0.006 * w0, np.radians(0.5)])
    grid = np.array(np.meshgrid(*[[-1, 0, 1]] * 4, indexing="ij")).reshape(4, -1).T
    while step[0] >= 0.3:
        P = best + grid * step
        sc = edge_score(gx, gy, P[:, 0], P[:, 1], P[:, 2], P[:, 3], portrait)
        i = sc.argmax()
        if sc[i] <= best_sc + 1e-6:
            step /= 2
        else:
            best, best_sc = P[i], sc[i]

    cx, cy, w, ang = best
    h = w / AR
    Wr, Hr = (w, h) if portrait else (h, w)
    c, s = np.cos(ang), np.sin(ang)
    q = np.array([(cx + x * c - y * s, cy + x * s + y * c)
                  for x, y in [(-Wr / 2, -Hr / 2), (Wr / 2, -Hr / 2), (Wr / 2, Hr / 2), (-Wr / 2, Hr / 2)]])
    return q * K, portrait


# --------------------------------------------------------------------------
# 3. warp upright
# --------------------------------------------------------------------------
def warp(im, q, portrait):
    q = np.float32(q)
    if not portrait:                         # card turned 90 CW: its TL is the image TR
        q = q[[1, 2, 3, 0]]
    M = cv2.getPerspectiveTransform(q, np.float32([[0, 0], [OUT_W, 0], [OUT_W, OUT_H], [0, OUT_H]]))
    art = cv2.warpPerspective(im, M, (OUT_W, OUT_H), flags=cv2.INTER_CUBIC)
    x0, y0 = round(OUT_W * INSET_X), round(OUT_H * INSET_Y)
    return art[y0:OUT_H - y0, x0:OUT_W - x0].copy()


# --------------------------------------------------------------------------
# 4. find and paint out the printed strip
# --------------------------------------------------------------------------
# The printed strip is a fixed layout, measured on the warped cards in units
# of the full illustration height: a top margin, one pitch per crystal, one
# slot for the trade arrow (the upgrade arrow is taller), then the chevron tip.
STRIP_RIGHT = 0.235         # of illustration width; the strip starts at the edge
STRIP_TOP = 0.055
STRIP_PITCH = 0.082
STRIP_ARROW = {"trade": 0.076, "upgrade": 0.120, "crystal": 0.0}
STRIP_PAD = 0.015


def printed_layout(label):
    """'2Y, 1B -> 2M' / '+4Y' / 'Upgrade 3' -> (kind, crystal count)."""
    if label.startswith("Upgrade"):
        return "upgrade", int(label.split()[1])
    kind = "trade" if "->" in label else "crystal"
    n = sum(int(tok.strip().lstrip("+")[:-1]) for side in label.split("->") for tok in side.split(","))
    return kind, n


def find_strip(art, label):
    """(left, right, tip) in px of the printed strip, from what it prints."""
    H, W = art.shape[:2]
    kind, n = printed_layout(label)
    tip = STRIP_TOP + n * STRIP_PITCH + STRIP_ARROW[kind] + STRIP_PAD     # of full height
    # the art was trimmed by INSET_X / INSET_Y after the warp
    tip = (tip - INSET_Y) / (1 - 2 * INSET_Y)
    right = (STRIP_RIGHT - INSET_X) / (1 - 2 * INSET_X)
    return 0, int(right * W), int(min(H - 1, tip * H))


def paint_out(art, left, right, tip):
    H, W = art.shape[:2]
    pad = max(4, int(W * 0.008))
    mask = np.zeros((H, W), np.uint8)
    mask[:tip + pad, max(0, left - pad):min(W, right + pad + 1)] = 255
    # inpaint at half size (smoother fill, much faster), then paste back
    half = cv2.resize(art, (W // 2, H // 2), interpolation=cv2.INTER_AREA)
    mh = cv2.resize(mask, (W // 2, H // 2), interpolation=cv2.INTER_NEAREST)
    filled = cv2.inpaint(half, mh, 9, cv2.INPAINT_TELEA)
    filled = cv2.resize(filled, (W, H), interpolation=cv2.INTER_CUBIC)
    soft = cv2.GaussianBlur(mask, (0, 0), 3).astype(np.float32)[..., None] / 255
    return (art * (1 - soft) + filled * soft).astype(np.uint8)


# --------------------------------------------------------------------------
def printed_labels():
    """photo stem -> what its printed strip shows, from ../gol/merchants.csv."""
    with open(MAPPING, newline="", encoding="utf-8-sig") as f:
        return {Path(r["photo"]).stem: (r.get("printed") or r["effect"]).strip()
                for r in csv.DictReader(f) if r.get("photo")}


def photos(only):
    seen, out = set(), []
    # "name (1).jpeg" copies sort after the original, so the original is kept
    for p in sorted(SRC.iterdir(), key=lambda p: (" (" in p.stem, p.name)):
        if p.suffix not in IMG_EXT or (only and p.stem not in only):
            continue
        digest = hashlib.md5(p.read_bytes()).hexdigest()
        if digest in seen:
            print(f"  skip {p.name} (duplicate)")
            continue
        seen.add(digest)
        out.append(p)
    return out


def main():
    only = set(sys.argv[1:])
    OUT.mkdir(parents=True, exist_ok=True)
    DEBUG.mkdir(exist_ok=True)
    strips_csv = OUT / "strips.csv"
    rows = {}
    if only and strips_csv.exists():
        with open(strips_csv, newline="", encoding="utf-8") as f:
            rows = {r["photo"]: r for r in csv.DictReader(f)}

    labels = printed_labels()
    for p in photos(only):
        if p.stem not in labels:
            print(f"  skip {p.name} (not in {MAPPING.name})")
            continue
        im = cv2.imread(str(p))
        q, portrait = snap(im, rough_box(im))
        art = warp(im, q, portrait)
        H, W = art.shape[:2]
        left, right, tip = find_strip(art, labels[p.stem])
        clean = paint_out(art, left, right, tip)
        name = p.stem + ".png"
        cv2.imwrite(str(OUT / name), clean)

        dbg = art.copy()
        cv2.rectangle(dbg, (left, 0), (right, tip), (0, 0, 255), 3)
        cv2.imwrite(str(DEBUG / name), cv2.resize(dbg, (W // 2, H // 2)))
        rows[name] = {"photo": name, "strip_left": f"{left / W:.4f}",
                      "strip_right": f"{right / W:.4f}", "strip_bottom": f"{tip / H:.4f}"}
        print(f"  {name:22s} strip x {left / W:.3f}-{right / W:.3f}  bottom {tip / H:.3f}")

    with open(strips_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["photo", "strip_left", "strip_right", "strip_bottom"])
        w.writeheader()
        w.writerows(rows[k] for k in sorted(rows))
    print(f"\nWrote {len(rows)} backgrounds to {OUT}/")


if __name__ == "__main__":
    main()

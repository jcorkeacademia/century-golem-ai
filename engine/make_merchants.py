#!/usr/bin/env python3
"""
Century: Golem Edition -- custom MERCHANT card generator.

Same folder layout as make_cards.py. Reads merchants.csv for the
photo mapping.

    python3 make_merchants.py --init     write merchants.csv template
    python3 make_merchants.py --check    report missing photos
    python3 make_merchants.py            render to out_merchants/

Three card types render differently:
    crystal   just the crystals you gain
    upgrade   the upgrade arrow, x3
    trade     cost crystals, arrow, gain crystals
"""

import sys
import csv
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

# --------------------------------------------------------------------------
# CARD DATA -- crystal cards, then the upgrade card, then trades sorted by
# net value gained (Y=1 G=2 B=3 M=4), cheapest cost first.
# (kind, cost, gain)
# --------------------------------------------------------------------------
MERCHANTS = [
    ("crystal", {}, {"B": 1}),                            # your #43
    ("crystal", {}, {"Y": 1, "G": 1}),                    # your #42
    ("crystal", {}, {"Y": 3}),                            # your #36
    ("crystal", {}, {"M": 1}),                            # your #28
    ("crystal", {}, {"Y": 1, "B": 1}),                    # your #8
    ("crystal", {}, {"G": 2}),                            # your #6
    ("crystal", {}, {"Y": 2, "G": 1}),                    # your #40
    ("crystal", {}, {"Y": 4}),                            # your #38
    ("upgrade", {}, {}),                                  # your #13
    ("trade", {"G": 1}, {"Y": 3}),                        # your #5
    ("trade", {"Y": 2}, {"B": 1}),                        # your #16
    ("trade", {"B": 1}, {"G": 2}),                        # your #33
    ("trade", {"Y": 1, "G": 1}, {"M": 1}),                # your #35
    ("trade", {"Y": 3}, {"M": 1}),                        # your #1
    ("trade", {"Y": 2}, {"G": 2}),                        # your #41
    ("trade", {"B": 1}, {"Y": 1, "G": 2}),                # your #31
    ("trade", {"Y": 3}, {"G": 1, "B": 1}),                # your #26
    ("trade", {"M": 1}, {"Y": 1, "G": 1, "B": 1}),        # your #4
    ("trade", {"M": 1}, {"B": 2}),                        # your #11
    ("trade", {"M": 1}, {"G": 3}),                        # your #24
    ("trade", {"M": 1}, {"Y": 2, "G": 2}),                # your #25
    ("trade", {"M": 1}, {"Y": 3, "B": 1}),                # your #34
    ("trade", {"G": 2}, {"Y": 3, "B": 1}),                # your #3
    ("trade", {"G": 2}, {"Y": 2, "M": 1}),                # your #14
    ("trade", {"G": 2}, {"B": 2}),                        # your #30
    ("trade", {"Y": 4}, {"B": 2}),                        # your #9
    ("trade", {"B": 2}, {"M": 2}),                        # your #17
    ("trade", {"B": 2}, {"Y": 2, "G": 1, "M": 1}),        # your #18
    ("trade", {"B": 2}, {"G": 2, "M": 1}),                # your #19
    ("trade", {"B": 2}, {"Y": 2, "G": 3}),                # your #22
    ("trade", {"G": 3}, {"M": 2}),                        # your #2
    ("trade", {"G": 3}, {"Y": 1, "B": 1, "M": 1}),        # your #15
    ("trade", {"G": 3}, {"Y": 2, "B": 2}),                # your #32
    ("trade", {"B": 1}, {"Y": 4, "G": 1}),                # your #27
    ("trade", {"Y": 3}, {"G": 3}),                        # your #10
    ("trade", {"Y": 4}, {"B": 1, "M": 1}),                # your #23
    ("trade", {"Y": 2, "B": 1}, {"M": 2}),                # your #39
    ("trade", {"Y": 5}, {"M": 2}),                        # your #29
    ("trade", {"G": 3}, {"B": 3}),                        # your #21
    ("trade", {"B": 3}, {"M": 3}),                        # your #20
    ("trade", {"M": 2}, {"G": 3, "B": 2}),                # your #7
    ("trade", {"M": 2}, {"Y": 1, "G": 1, "B": 3}),        # your #12
    ("trade", {"Y": 5}, {"B": 3}),                        # your #37

    # ---- starting cards (purple border, not in the merchant deck) ----
    # One artwork each; print as many copies as you have players.
    ("crystal", {}, {"Y": 2}),        # 44  Create 2
    ("upgrade", {}, {}, 2),           # 45  Upgrade 2
]

# Slots 44-45 are the starting cards. Set to 43 to render the deck only.
LAST_SLOT = 45
STARTING_FROM = 44                 # first starting-card slot
START_BORDER = (104, 62, 148)      # purple border for the starting cards

UPGRADE_STEPS = 3          # default; a card may override it

# --------------------------------------------------------------------------
# TUNE THESE
# --------------------------------------------------------------------------
DPI          = 300
CARD_W       = int(2.5 * DPI)
CARD_H       = int(3.5 * DPI)

CORNER       = 40
BORDER       = 18
BORDER_COLOR = (46, 30, 66)        # plum, to distinguish from the golem navy
PHOTO_ANCHOR = 0.15

# The effect strip runs vertically down the LEFT edge, as on the real cards:
# cost crystals on top, arrow, gain crystals below.
STRIP_W      = 150                 # strip width in px
STRIP_INSET  = 34                  # gap between the left card edge and the strip
STRIP_FILL   = (247, 243, 233, 232)   # cream panel, slightly translucent
STRIP_EDGE   = (120, 104, 138, 255)
STRIP_OVERHANG = 14                # how far past an old printed strip the new one reaches

CRYSTAL_SIZE = 82                  # icon size inside the strip
CRYSTAL_GAP  = 8                   # vertical gap between stacked crystals
ARROW_GAP    = 14                  # space around the arrow
ARROW_COLOR  = (118,  62, 158)     # purple, as printed
UPARROW_COLOR = (92, 104, 176)

LABEL_COLOR  = (255, 244, 214)
LABEL_SIZE   = 40
SHOW_LABEL   = False               # real cards carry no text; on = debug aid

FONT_PATH    = None
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\timesbd.ttf",
    r"C:\Windows\Fonts\georgiab.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
]

ORDER        = ["Y", "G", "B", "M"]
CRYSTAL_FILE = {"Y": "yellow", "G": "green", "B": "blue", "M": "magenta"}

# Keep merchant faces off the golem cards. If photos_merchants/ exists it is
# used exclusively; otherwise photos/ is used minus anything cards.csv claimed.
EXCLUDE_GOLEM_PHOTOS = True

ROOT     = Path(__file__).parent
CRYSTALS = ROOT / "crystals"
PHOTOS   = ROOT / "photos"
PHOTOS_M = ROOT / "photos_merchants"
GOLEM_MAP = ROOT / "cards.csv"
OUT      = ROOT / "out_merchants"
MAPPING  = ROOT / "merchants.csv"

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".PNG", ".JPG", ".JPEG", ".WEBP")

# --------------------------------------------------------------------------
# ART SETS -- pick one with --set NAME (default: photos), as in make_cards.py.
#   photos  the face deck: photos_merchants/ + merchants.csv -> out_merchants/
#   gol     card art cut from photos of the real cards for the DEFAULT room:
#           ../gol/merchant_backgrounds (made by extract_merchants.py from
#           ../mer) + ../gol/merchants.csv -> ../gol/out_merchants/
# The gol art has its printed strip painted out, which leaves a smear; the
# new strip sits where the printed one did (near the edge, a little wider)
# and stretches down to the old one's tip, read from strips.csv.
# --------------------------------------------------------------------------
GOL = ROOT.parent / "gol"
ART_SETS = {
    "photos": dict(PHOTOS_M=PHOTOS_M, MAPPING=MAPPING, OUT=OUT),
    "gol":    dict(PHOTOS_M=GOL / "merchant_backgrounds", MAPPING=GOL / "merchants.csv",
                   OUT=GOL / "out_merchants", PHOTO_ANCHOR=0.5,
                   STRIP_INSET=6, STRIP_W=160),
}


def load_strips():
    """photo filename -> how far down its painted-out strip reached."""
    p = PHOTOS_M / "strips.csv"
    if not p.exists():
        return {}
    with open(p, newline="", encoding="utf-8") as f:
        return {r["photo"]: float(r["strip_bottom"]) for r in csv.DictReader(f)}


def select_art_set():
    """Apply --set NAME from ART_SETS over the module-level settings."""
    name = "photos"
    if "--set" in sys.argv:
        i = sys.argv.index("--set")
        if i + 1 >= len(sys.argv) or sys.argv[i + 1] not in ART_SETS:
            sys.exit(f"--set takes one of: {', '.join(ART_SETS)}")
        name = sys.argv[i + 1]
    globals().update(ART_SETS[name])
    print(f"Art set: {name}")


# --------------------------------------------------------------------------
def find_asset(folder: Path, stem: str):
    for ext in IMG_EXT:
        p = folder / f"{stem}{ext}"
        if p.exists():
            return p
    return None


def load_font(size):
    paths = [FONT_PATH] if FONT_PATH else FONT_CANDIDATES
    for p in paths:
        if p and Path(p).exists():
            return ImageFont.truetype(p, size)
    print("No TrueType font found -- using the default bitmap font.")
    return ImageFont.load_default()


def load_crystals():
    icons, missing = {}, []
    for key, name in CRYSTAL_FILE.items():
        p = find_asset(CRYSTALS, name)
        if p is None:
            missing.append(f"crystals/{name}.png")
            continue
        im = Image.open(p).convert("RGBA")
        h = round(CRYSTAL_SIZE * im.height / im.width)
        icons[key] = im.resize((CRYSTAL_SIZE, h), Image.LANCZOS)
    if missing:
        sys.exit("Missing crystal icons:\n  " + "\n  ".join(missing))
    return icons


def fill_crop(im, w, h, anchor):
    im = im.convert("RGB")
    scale = max(w / im.width, h / im.height)
    im = im.resize((max(1, round(im.width * scale)),
                    max(1, round(im.height * scale))), Image.LANCZOS)
    left = (im.width - w) // 2
    top = max(0, min(round((im.height - h) * anchor), im.height - h))
    return im.crop((left, top, left + w, top + h))


def rounded_mask(w, h, r):
    m = Image.new("L", (w * 4, h * 4), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w * 4 - 1, h * 4 - 1],
                                        radius=r * 4, fill=255)
    return m.resize((w, h), Image.LANCZOS)


def seq_of(d):
    return [c for c in ORDER for _ in range(d.get(c, 0))]


def stack_height(seq, icons, gap=None):
    if not seq:
        return 0
    gap = CRYSTAL_GAP if gap is None else gap
    return sum(icons[c].height for c in seq) + gap * (len(seq) - 1)


def paste_stack(target, seq, icons, cx, y, gap=None):
    """Paste crystals in a vertical column centred on cx, starting at y."""
    gap = CRYSTAL_GAP if gap is None else gap
    for c in seq:
        ic = icons[c]
        target.paste(ic, (cx - ic.width // 2, round(y)), ic)
        y += ic.height + gap
    return y


def down_arrow(d, cx, y, w=52, h=46):
    """Purple arrow pointing down, as printed on trade cards."""
    shaft = w * 0.30
    d.polygon([(cx - shaft, y), (cx + shaft, y),
               (cx + shaft, y + h * 0.48),
               (cx + w / 2, y + h * 0.48),
               (cx, y + h),
               (cx - w / 2, y + h * 0.48),
               (cx - shaft, y + h * 0.48)], fill=ARROW_COLOR)
    return y + h


def up_arrow(d, cx, y, w=52, h=46):
    shaft = w * 0.30
    d.polygon([(cx, y), (cx + w / 2, y + h * 0.52),
               (cx + shaft, y + h * 0.52),
               (cx + shaft, y + h),
               (cx - shaft, y + h),
               (cx - shaft, y + h * 0.52),
               (cx - w / 2, y + h * 0.52)], fill=UPARROW_COLOR)
    return y + h


def build_card(kind, cost, gain, photo_path, icons, font, steps=None,
               border=None, strip_frac=None):
    """strip_frac: how far down the photo an old printed strip reaches (as a
    fraction of its height). The new strip then stretches to cover it."""
    steps = steps or UPGRADE_STEPS
    W, H = CARD_W, CARD_H
    card = Image.new("RGB", (W, H), border or BORDER_COLOR)

    iw, ih = W - 2 * BORDER, H - 2 * BORDER
    src = Image.open(photo_path) if photo_path else None
    photo = (fill_crop(src, iw, ih, PHOTO_ANCHOR)
             if src else Image.new("RGB", (iw, ih), (120, 118, 140)))
    inner = Image.new("RGB", (iw, ih), border or BORDER_COLOR)
    inner.paste(photo, (0, 0))
    card.paste(inner, (BORDER, BORDER),
               rounded_mask(iw, ih, max(2, CORNER - BORDER)))

    # ---- work out how tall the strip contents are ----
    cost_seq, gain_seq = seq_of(cost), seq_of(gain)
    gap, arrow_gap, pad = CRYSTAL_GAP, ARROW_GAP, 26

    def content_height():
        if kind == "upgrade":
            return steps * 46 + (steps - 1) * arrow_gap
        if cost_seq:
            return (stack_height(cost_seq, icons, gap) + arrow_gap + 46
                    + arrow_gap + stack_height(gain_seq, icons, gap))
        return stack_height(gain_seq, icons, gap)

    strip_x = BORDER + STRIP_INSET
    strip_y = BORDER                      # flush with the top of the art
    strip_h = content_height() + pad * 2

    if strip_frac and src:
        # where the old strip's tip lands on the card, via fill_crop's geometry
        scale = max(iw / src.width, ih / src.height)
        top = max(0, min(round((src.height * scale - ih) * PHOTO_ANCHOR),
                         round(src.height * scale) - ih))
        need = BORDER + strip_frac * src.height * scale - top + STRIP_OVERHANG - strip_y
        need = min(need, ih - 40)
        if need > strip_h:
            # spread the difference over every gap (and the two end pads)
            if kind == "upgrade":
                slots = steps - 1
            elif cost_seq:
                slots = len(cost_seq) - 1 + len(gain_seq) - 1 + 2
            else:
                slots = len(gain_seq) - 1
            extra = (need - strip_h) / (slots + 2)
            gap, arrow_gap, pad = gap + extra, arrow_gap + extra, pad + extra
            strip_h = content_height() + pad * 2

    # ---- the cream panel: hangs from the top edge like a bookmark, so only
    # the bottom corners are rounded (the top is drawn off-card and clipped) ----
    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(panel)
    pd.rounded_rectangle([strip_x, strip_y - 60,
                          strip_x + STRIP_W, strip_y + strip_h],
                         radius=26, fill=STRIP_FILL, outline=STRIP_EDGE, width=4)
    # erase everything above the card's inner top edge
    pd.rectangle([0, 0, W, strip_y - 1], fill=(0, 0, 0, 0))
    card = Image.alpha_composite(card.convert("RGBA"), panel).convert("RGB")

    d = ImageDraw.Draw(card)
    cx = strip_x + STRIP_W // 2
    y = strip_y + pad

    if kind == "upgrade":
        for i in range(steps):
            y = up_arrow(d, cx, y)
            y += arrow_gap
    elif cost_seq:
        y = paste_stack(card, cost_seq, icons, cx, y, gap)
        y += arrow_gap - gap
        y = down_arrow(d, cx, y)
        y += arrow_gap
        paste_stack(card, gain_seq, icons, cx, y, gap)
    else:
        paste_stack(card, gain_seq, icons, cx, y, gap)

    if SHOW_LABEL:
        txt = plain_label(kind, cost, gain, steps)
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(sh).text((W // 2, H - 70), txt, font=font,
                                fill=(0, 0, 0, 210), anchor="mm")
        card.paste(sh, (0, 0), sh.filter(ImageFilter.GaussianBlur(8)))
        ImageDraw.Draw(card).text((W // 2, H - 70), txt, font=font,
                                  fill=LABEL_COLOR, anchor="mm",
                                  stroke_width=3, stroke_fill=(28, 14, 38))

    out = Image.new("RGB", (W, H), (255, 255, 255))
    out.paste(card, (0, 0), rounded_mask(W, H, CORNER))
    return out


def plain_label(kind, cost, gain, steps=None):
    def lab(d):
        return ", ".join(f"{d[c]}{c}" for c in ORDER if c in d)
    if kind == "crystal":
        return "+" + lab(gain)
    if kind == "upgrade":
        return f"Upgrade {steps if steps else UPGRADE_STEPS}"
    return f"{lab(cost)} -> {lab(gain)}"


def unpack(entry):
    kind, cost, gain = entry[0], entry[1], entry[2]
    steps = entry[3] if len(entry) > 3 else UPGRADE_STEPS
    return kind, cost, gain, steps


def write_template():
    if MAPPING.exists():
        sys.exit(f"{MAPPING.name} already exists -- delete it first.")
    with open(MAPPING, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["slot", "type", "effect", "photo", "player"])
        for i, entry in enumerate(MERCHANTS[:LAST_SLOT], 1):
            kind, cost, gain, steps = unpack(entry)
            tag = "starting" if i >= STARTING_FROM else kind
            w.writerow([f"{i:02d}", tag,
                        plain_label(kind, cost, gain, steps), "", ""])
    print(f"Wrote {MAPPING.name} with all {len(MERCHANTS)} slots.")


def photo_dir():
    """photos_merchants/ if you made one, else the shared photos/ folder."""
    if PHOTOS_M.is_dir() and any(q.suffix in IMG_EXT for q in PHOTOS_M.glob("*")):
        return PHOTOS_M
    return PHOTOS


def golem_photo_stems():
    """Stems already used on golem cards, read from cards.csv."""
    if not (EXCLUDE_GOLEM_PHOTOS and GOLEM_MAP.exists()):
        return set()
    out = set()
    with open(GOLEM_MAP, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = (row.get("photo") or "").strip()
            if name:
                out.add(Path(name).stem.lower())
    return out


def all_photos():
    """Candidate merchant photos, sorted, deduped, golem faces removed."""
    folder = photo_dir()
    used = golem_photo_stems() if folder == PHOTOS else set()
    seen, out = set(), []
    for p in sorted(folder.glob("*")):
        k = p.stem.lower()
        if p.suffix in IMG_EXT and k not in seen and k not in used:
            seen.add(k)
            out.append(p)
    return out


def load_mapping():
    if not MAPPING.exists():
        return {}
    out = {}
    with open(MAPPING, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            slot = (row.get("slot") or "").strip()
            photo = (row.get("photo") or "").strip()
            if slot and photo:
                out[slot.zfill(2)] = (photo, (row.get("player") or "").strip())
    return out


def make_pdf(paths, pdf_path):
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas as rl_canvas
    PW, PH = letter
    cw, ch = 2.5 * 72, 3.5 * 72
    cols, rows = 3, 3
    mx, my = (PW - cols * cw) / 2, (PH - rows * ch) / 2
    c = rl_canvas.Canvas(str(pdf_path), pagesize=letter)
    for i, p in enumerate(paths):
        slot = i % (cols * rows)
        if i and slot == 0:
            c.showPage()
        x = mx + (slot % cols) * cw
        y = PH - my - (slot // cols + 1) * ch
        c.drawImage(str(p), x, y, cw, ch)
        c.setStrokeColorRGB(0.75, 0.75, 0.75)
        c.setLineWidth(0.3)
        c.rect(x, y, cw, ch, stroke=1, fill=0)
    c.save()


def main():
    select_art_set()
    if "--init" in sys.argv:
        write_template()
        return
    check_only = "--check" in sys.argv

    OUT.mkdir(exist_ok=True)
    icons = load_crystals()
    font = load_font(LABEL_SIZE)
    mapping = load_mapping()
    if mapping:
        print(f"Using {MAPPING.name} ({len(mapping)} slots assigned).")
    src = photo_dir()
    print(f"Photo source: {src.name}/")

    missing_named = []

    # Slots you named explicitly win; everything else is filled automatically
    # from whatever photos are left over, cycling if there aren't enough.
    pool = all_photos()
    if not pool:
        sys.exit("No merchant photos available. Either add images to "
                 "photos_merchants/, or set EXCLUDE_GOLEM_PHOTOS = False.")
    claimed = set()
    resolved = {}
    folder = photo_dir()
    for slot, (fname, _player) in mapping.items():
        p = folder / fname
        if not p.exists():
            p = find_asset(folder, Path(fname).stem)
        if p is None or not p.exists():
            p = find_asset(PHOTOS, Path(fname).stem)
        if p is None or not p.exists():
            missing_named.append(f"photos/{fname}  (slot {slot})")
            continue
        resolved[slot] = p
        claimed.add(p.stem.lower())

    strips = load_strips()
    leftovers = [p for p in pool if p.stem.lower() not in claimed]
    if not leftovers:
        leftovers = pool
    k = 0

    paths, rows = [], []
    for i, entry in enumerate(MERCHANTS[:LAST_SLOT], 1):
        kind, cost, gain, steps = unpack(entry)
        stem = f"{i:02d}"
        player = mapping.get(stem, ("", ""))[1]
        photo = resolved.get(stem)
        auto = ""
        if photo is None and leftovers:
            photo = leftovers[k % len(leftovers)]
            k += 1
            auto = "auto"

        starting = i >= STARTING_FROM
        rows.append([stem, "starting" if starting else kind,
                     plain_label(kind, cost, gain, steps),
                     photo.name if photo else "MISSING", player, auto])
        if check_only:
            continue
        card = build_card(kind, cost, gain, photo, icons, font, steps,
                          START_BORDER if starting else None,
                          strips.get(photo.name) if photo else None)
        p = OUT / (f"start_{stem}_{kind}.png" if starting
                   else f"merchant_{stem}_{kind}.png")
        card.save(p, dpi=(DPI, DPI))
        paths.append(p)

    with open(OUT / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["slot", "type", "effect", "photo", "player", "auto"])
        w.writerows(rows)

    if missing_named:
        print(f"\n{len(missing_named)} named photo(s) not found:\n")
        for m in missing_named:
            print("  " + m)

    n = len(MERCHANTS[:LAST_SLOT])
    n_auto = sum(1 for r in rows if r[5] == "auto")
    pool_n = len(all_photos())
    if n_auto > pool_n:
        print(f"\nOnly {pool_n} distinct photo(s) available for {n_auto} "
              f"auto-filled slot(s) -- {n_auto - pool_n} face(s) will repeat.")
    if check_only:
        print(f"\n{n - n_auto} slot(s) assigned by name, {n_auto} auto-filled.")
        return
    print(f"{n_auto} slot(s) auto-filled from leftover photos.")

    make_pdf(paths, OUT / "merchant_cards_print.pdf")
    print(f"\nWrote {len(paths)} cards to {OUT}/")


if __name__ == "__main__":
    main()

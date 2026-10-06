#!/usr/bin/env python3
"""
Century: Golem Edition -- custom golem card generator.

Reads the 36 golem cards, drops in a photo per card, stamps the crystal
costs along the bottom and the point value in the corner, and writes
print-ready PNGs plus a cut-sheet PDF.

USAGE
-----
    python3 make_cards.py

FOLDER LAYOUT (put make_cards.py at the top)
--------------------------------------------
    make_cards.py
    crystals/
        yellow.png
        green.png
        blue.png
        magenta.png
    photos/
        01.png   02.png   03.png   ...   36.png
    out/                      <- created for you

The number on each photo filename is the card's rank in the sorted list
below (01 = the 6-point card, 36 = the 20-point 5M card). Extensions
.png .jpg .jpeg .webp all work. Photos are cropped to fill, centred on
the top of the frame so faces don't get cut off.

Run with --check to see which photos are missing before you commit.
"""

import sys
import csv
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

# --------------------------------------------------------------------------
# CARD DATA -- sorted low to high, ties broken by cheaper crystal cost.
# (points, {colour: count})  colours: Y G B M
# --------------------------------------------------------------------------
GOLEMS = [
    (6,  {"Y": 2, "G": 2}),
    (7,  {"Y": 3, "G": 2}),
    (8,  {"Y": 2, "B": 2}),
    (8,  {"Y": 2, "G": 3}),
    (8,  {"G": 4}),
    (9,  {"Y": 2, "G": 1, "M": 1}),
    (9,  {"Y": 3, "B": 2}),
    (10, {"Y": 2, "M": 2}),
    (10, {"G": 2, "B": 2}),
    (10, {"G": 5}),
    (11, {"Y": 3, "M": 2}),
    (11, {"Y": 2, "B": 3}),
    (12, {"Y": 1, "G": 1, "B": 1, "M": 1}),
    (12, {"G": 2, "M": 2}),
    (12, {"Y": 1, "B": 2, "M": 1}),
    (12, {"G": 2, "B": 1, "M": 1}),
    (12, {"G": 3, "B": 2}),
    (12, {"B": 4}),
    (13, {"Y": 2, "G": 2, "B": 2}),
    (13, {"G": 2, "B": 3}),
    (14, {"Y": 3, "G": 1, "B": 1, "M": 1}),
    (14, {"Y": 2, "M": 3}),
    (14, {"B": 2, "M": 2}),
    (14, {"G": 3, "M": 2}),
    (15, {"Y": 2, "G": 2, "M": 2}),
    (15, {"B": 5}),
    (16, {"Y": 1, "G": 3, "B": 1, "M": 1}),
    (16, {"G": 2, "M": 3}),
    (16, {"M": 4}),
    (17, {"Y": 2, "B": 2, "M": 2}),
    (17, {"B": 3, "M": 2}),
    (18, {"Y": 1, "G": 1, "B": 3, "M": 1}),
    (18, {"B": 2, "M": 3}),
    (19, {"G": 2, "B": 2, "M": 2}),
    (20, {"Y": 1, "G": 1, "B": 1, "M": 3}),
    (20, {"M": 5}),
]

# --------------------------------------------------------------------------
# TUNE THESE
# --------------------------------------------------------------------------
DPI          = 300
CARD_W       = int(2.5 * DPI)      # 750 px  -- poker size
CARD_H       = int(3.5 * DPI)      # 1050 px
BLEED        = 0                   # set to int(0.125 * DPI) if your printer wants bleed

CORNER       = 40                  # rounded-corner radius
BORDER       = 18                  # dark frame thickness
BORDER_COLOR = (20, 26, 48)        # navy, matches your mockup
PHOTO_ANCHOR = 0.30                # 0 = top of photo, 0.5 = centre. Faces sit high.

CRYSTAL_SIZE = 88                  # width of each crystal icon in px
CRYSTAL_GAP  = 8                   # px between crystals
CRYSTAL_Y    = 0.90                # vertical position, fraction of card height
BAND_HEIGHT  = 150                 # dark band behind the crystals (0 to disable)
BAND_OPACITY = 165                 # 0-255

SHOW_POINTS  = True
POINT_SIZE   = 96
POINT_XY     = (0.50, 0.775)       # fraction of card w/h, centre of the number

# Leave as None to auto-detect a bold serif on Windows / Mac / Linux.
# Set a path yourself to use a specific font.
FONT_PATH    = None

ORDER        = ["Y", "G", "B", "M"]
CRYSTAL_FILE = {"Y": "yellow", "G": "green", "B": "blue", "M": "magenta"}

ROOT     = Path(__file__).parent
CRYSTALS = ROOT / "crystals"
PHOTOS   = ROOT / "photos"
OUT      = ROOT / "out"

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".PNG", ".JPG", ".JPEG")

# --------------------------------------------------------------------------
# ART SETS -- pick one with --set NAME (default: photos).
#   photos  the face deck: photos/ + cards.csv -> out/
#   gol     painted backgrounds for the DEFAULT room (server/card_art_index.py):
#           ../gol/backgrounds + ../gol/cards.csv -> ../gol/out/
# The gol paintings still show faint smudges where their original crystal
# row was painted out, so that set crops from the bottom and spaces the
# crystals at the original pitch to land the new ones right on top of them.
# --------------------------------------------------------------------------
GOL = ROOT.parent / "gol"
ART_SETS = {
    "photos": dict(PHOTOS=PHOTOS, MAPPING=ROOT / "cards.csv", OUT=OUT),
    "gol":    dict(PHOTOS=GOL / "backgrounds", MAPPING=GOL / "cards.csv",
                   OUT=GOL / "out", PHOTO_ANCHOR=1.0, CRYSTAL_GAP=34,
                   CRYSTAL_Y=0.91),
}


# --------------------------------------------------------------------------
def find_asset(folder: Path, stem: str):
    """Return the first file in folder matching stem + any image extension."""
    for ext in IMG_EXT:
        p = folder / f"{stem}{ext}"
        if p.exists():
            return p
    return None


def resolve_font():
    """Find a bold serif font on Windows, Mac or Linux."""
    if FONT_PATH:
        return FONT_PATH
    candidates = [
        r"C:\Windows\Fonts\timesbd.ttf",            # Windows, Times New Roman Bold
        r"C:\Windows\Fonts\georgiab.ttf",           # Windows, Georgia Bold
        r"C:\Windows\Fonts\arialbd.ttf",            # Windows fallback
        "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
        "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    return None


def load_font(size):
    p = resolve_font()
    if p is None:
        print("No TrueType font found -- point numbers will use a small "
              "default font. Set FONT_PATH near the top of this script.")
        return ImageFont.load_default()
    return ImageFont.truetype(p, size)


def load_crystals():
    icons = {}
    missing = []
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


def fill_crop(im: Image.Image, w: int, h: int, anchor: float) -> Image.Image:
    """Scale to cover w x h, then crop. anchor picks the vertical slice."""
    im = im.convert("RGB")
    scale = max(w / im.width, h / im.height)
    new = (max(1, round(im.width * scale)), max(1, round(im.height * scale)))
    im = im.resize(new, Image.LANCZOS)
    left = (im.width - w) // 2
    top = round((im.height - h) * anchor)
    top = max(0, min(top, im.height - h))
    return im.crop((left, top, left + w, top + h))


def rounded_mask(w: int, h: int, r: int) -> Image.Image:
    m = Image.new("L", (w * 4, h * 4), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w * 4 - 1, h * 4 - 1],
                                        radius=r * 4, fill=255)
    return m.resize((w, h), Image.LANCZOS)


def build_card(points: int, cost: dict, photo_path, icons, font) -> Image.Image:
    W, H = CARD_W, CARD_H
    card = Image.new("RGB", (W, H), BORDER_COLOR)

    # --- photo, inset by the border, rounded ---
    iw, ih = W - 2 * BORDER, H - 2 * BORDER
    if photo_path:
        photo = fill_crop(Image.open(photo_path), iw, ih, PHOTO_ANCHOR)
    else:
        photo = Image.new("RGB", (iw, ih), (120, 128, 150))
    inner = Image.new("RGB", (iw, ih), BORDER_COLOR)
    inner.paste(photo, (0, 0))
    card.paste(inner, (BORDER, BORDER),
               rounded_mask(iw, ih, max(2, CORNER - BORDER)))

    # --- darkened band so icons and the number stay readable ---
    if BAND_HEIGHT > 0:
        band = Image.new("RGBA", (W, BAND_HEIGHT), (0, 0, 0, 0))
        bd = ImageDraw.Draw(band)
        for y in range(BAND_HEIGHT):
            a = round(BAND_OPACITY * (y / BAND_HEIGHT) ** 0.65)
            bd.line([(0, y), (W, y)], fill=(8, 12, 28, a))
        card.paste(band, (0, H - BAND_HEIGHT), band)

    # --- point value ---
    if SHOW_POINTS:
        d = ImageDraw.Draw(card)
        txt = str(points)
        cx, cy = round(W * POINT_XY[0]), round(H * POINT_XY[1])
        # soft shadow for legibility over any photo
        shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).text((cx, cy), txt, font=font,
                                    fill=(0, 0, 0, 210), anchor="mm")
        card.paste(shadow, (0, 0), shadow.filter(ImageFilter.GaussianBlur(9)))
        d.text((cx, cy), txt, font=font, fill=(255, 246, 214), anchor="mm",
               stroke_width=4, stroke_fill=(30, 22, 8))

    # --- crystal row ---
    seq = [c for c in ORDER for _ in range(cost.get(c, 0))]
    total = sum(icons[c].width for c in seq) + CRYSTAL_GAP * (len(seq) - 1)
    x = (W - total) // 2
    ymid = round(H * CRYSTAL_Y)
    for c in seq:
        ic = icons[c]
        card.paste(ic, (x, ymid - ic.height // 2), ic)
        x += ic.width + CRYSTAL_GAP

    # --- final rounded corners on the whole card ---
    out = Image.new("RGB", (W, H), (255, 255, 255))
    out.paste(card, (0, 0), rounded_mask(W, H, CORNER))
    return out


def cost_label(cost: dict) -> str:
    return ", ".join(f"{cost[c]}{c}" for c in ORDER if c in cost)


def make_pdf(paths, pdf_path):
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas as rl_canvas

    PW, PH = letter
    cw, ch = 2.5 * 72, 3.5 * 72
    cols, rows = 3, 3
    mx = (PW - cols * cw) / 2
    my = (PH - rows * ch) / 2

    c = rl_canvas.Canvas(str(pdf_path), pagesize=letter)
    for i, p in enumerate(paths):
        slot = i % (cols * rows)
        if i and slot == 0:
            c.showPage()
        col, row = slot % cols, slot // cols
        x = mx + col * cw
        y = PH - my - (row + 1) * ch
        c.drawImage(str(p), x, y, cw, ch)
        c.setStrokeColorRGB(0.75, 0.75, 0.75)
        c.setLineWidth(0.3)
        c.rect(x, y, cw, ch, stroke=1, fill=0)
    c.save()


MAPPING = ROOT / "cards.csv"


def write_template():
    """Create cards.csv listing all 36 slots, ready for you to fill in."""
    if MAPPING.exists():
        sys.exit(f"{MAPPING.name} already exists -- delete it first if you "
                 "want a fresh template.")
    with open(MAPPING, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["slot", "points", "cost", "photo", "player"])
        for i, (points, cost) in enumerate(GOLEMS, start=1):
            w.writerow([f"{i:02d}", points, cost_label(cost), "", ""])
    print(f"Wrote {MAPPING.name} with all 36 slots.")
    print("Put the photo filename in the 'photo' column for each card.")
    print("Leave rows blank to skip them for now.")


def load_mapping():
    """Return {slot: (photo_filename, player_name)} from cards.csv, if present."""
    if not MAPPING.exists():
        return {}
    out = {}
    with open(MAPPING, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            slot = (row.get("slot") or "").strip()
            photo = (row.get("photo") or "").strip()
            player = (row.get("player") or "").strip()
            if slot and photo:
                out[slot.zfill(2)] = (photo, player)
    return out


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


def main():
    select_art_set()
    check_only = "--check" in sys.argv
    if "--init" in sys.argv:
        write_template()
        return

    OUT.mkdir(exist_ok=True)
    icons = load_crystals()
    font = load_font(POINT_SIZE)

    mapping = load_mapping()
    if mapping:
        print(f"Using cards.csv ({len(mapping)} slots assigned).")

    missing = []
    paths = []
    rows = []

    for i, (points, cost) in enumerate(GOLEMS, start=1):
        stem = f"{i:02d}"
        player = ""

        if stem in mapping:
            fname, player = mapping[stem]
            photo = PHOTOS / fname
            if not photo.exists():                 # tolerate a missing extension
                photo = find_asset(PHOTOS, Path(fname).stem)
            if photo is None or not photo.exists():
                missing.append(f"photos/{fname}  (slot {stem})  ->  "
                               f"{points} pts: {cost_label(cost)}")
                photo = None
        else:
            photo = find_asset(PHOTOS, stem)
            if photo is None:
                where = "cards.csv" if mapping else f"photos/{stem}.png"
                missing.append(f"{where}  (slot {stem})  ->  "
                               f"{points} pts: {cost_label(cost)}")

        rows.append([stem, points, cost_label(cost),
                     photo.name if photo else "MISSING", player])

        if check_only:
            continue

        card = build_card(points, cost, photo, icons, font)
        out_path = OUT / f"golem_{stem}_{points}pts.png"
        card.save(out_path, dpi=(DPI, DPI))
        paths.append(out_path)

    with open(OUT / "manifest.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["slot", "points", "cost", "photo", "player"])
        w.writerows(rows)

    if missing:
        print(f"\n{len(missing)} photo(s) not found — placeholder used:\n")
        for m in missing:
            print("  " + m)

    if check_only:
        print(f"\nCheck only. {36 - len(missing)}/36 photos present.")
        return

    make_pdf(paths, OUT / "golem_cards_print.pdf")
    print(f"\nWrote {len(paths)} cards to {OUT}/")
    print(f"  golem_cards_print.pdf   9 per page, cut lines, actual size")
    print(f"  manifest.csv            which photo went on which card")





if __name__ == "__main__":
    main()

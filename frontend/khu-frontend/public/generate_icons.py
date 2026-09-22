"""
generate_icons.py — Regenerate the browser favicon and the PWA app icons
from the real KHU logo (khu-logo.png in this folder).

Usage (from anywhere):
    python generate_icons.py

Requires Pillow: pip install pillow

ABOUT THE BACKGROUND
    khu-logo.png is a print/photo-style asset: the crest sits on a light
    textured background whose luminance measures 157-221, while the crest
    itself is black (<150), white (>240) and red. This script knocks that
    background out so the marks can float on whatever is behind them:

        favicon.ico     transparent background — the crest shows on the
                        browser's own tab-bar colour (16/32/48 in one
                        file, so browsers pick a real resolution instead
                        of rescaling one bitmap)
        icon-192.png    crest centred on the app's dark tile (matches the
        icon-512.png    shell + manifest theme colour) — home-screen
                        icons need an opaque background: iOS composites
                        transparency onto black, Android masks it
        icon-preview.png  QA sheet showing the cut-out crest on a light
                        and a dark background — check this before shipping

    The knock-out is a flood fill from the image border over a luminance
    band (BG_LOW..BG_HIGH), NOT a global colour key: only background that
    actually connects to the edge disappears, so white/grey detail INSIDE
    the crest stays opaque. If a future logo needs a different band, tune
    the two constants above and re-run. Delete icon-preview.png if you
    don't want it shipped.
"""

from pathlib import Path

from PIL import Image, ImageDraw

BASE_DIR = Path(__file__).resolve().parent
SOURCE = BASE_DIR / "khu-logo.png"

PWA_SIZES = [192, 512]
FAVICON_SIZES = [16, 32, 48]

# Matches the app's background (and manifest theme_color).
CANVAS_BG = (13, 17, 23, 255)
TRANSPARENT = (0, 0, 0, 0)

# Measured luminance band of the logo's own background (157-221), with a
# little headroom on each side. Crest ink is either below or above it.
BG_LOW = 150
BG_HIGH = 238

# Small breathing room around the crest in the favicon, so round mask
# shapes in some browser UIs can't clip it.
FAVICON_MARGIN = 0.05


def strip_background(img: Image.Image) -> Image.Image:
    """Make the logo's light background transparent and return the
    cropped-down crest (RGBA).

    Implementation: build a mask of every pixel whose luminance falls in
    the background band, then flood-fill from the image border — the fill
    spreads only through connected band pixels, so the background is
    removed while enclosed light detail inside the crest is kept. The
    fill runs on the mask via Pillow's own C implementation, so it is
    fast despite operating on a 1200x892 image.
    """
    work = img.convert("RGBA")
    width, height = work.size

    band = work.convert("L").point(
        lambda p: 255 if BG_LOW <= p <= BG_HIGH else 0
    )

    sentinel = 128  # mask values are only 0/255, so 128 is safe
    border_seeds = (
        [(x, y) for x in range(width) for y in (0, height - 1)]
        + [(x, y) for y in range(height) for x in (0, width - 1)]
    )
    for seed in border_seeds:
        if band.getpixel(seed) == 255:  # still an unclaimed background pixel
            ImageDraw.floodfill(band, seed, sentinel, thresh=0)

    work.putalpha(band.point(lambda p: 0 if p == sentinel else 255))

    removed = sum(1 for p in band.tobytes() if p == sentinel)
    print(
        f"Background removed: {removed / (width * height):.1%} of the image "
        f"(band {BG_LOW}-{BG_HIGH}, border-connected only)"
    )

    # Crop to the visible crest so it is centred in the icon regardless
    # of how much empty margin the source file has.
    alpha_bbox = work.getchannel("A").getbbox()
    if alpha_bbox:
        work = work.crop(alpha_bbox)
        print(f"Crest bounds in original: {alpha_bbox} — cropped to {work.size}")
    return work


def square_icon(img: Image.Image, size: int, background, margin: float = 0.0) -> Image.Image:
    """Resize keeping aspect ratio, then centre on a square canvas (use
    TRANSPARENT for a see-through background, CANVAS_BG for the app tile)."""
    inner = max(1, int(size * (1 - 2 * margin)))
    resized = img.copy()
    resized.thumbnail((inner, inner), Image.LANCZOS)

    canvas = Image.new("RGBA", (size, size), background)
    canvas.paste(
        resized,
        ((size - resized.width) // 2, (size - resized.height) // 2),
        resized,
    )
    return canvas


def save_preview(crest: Image.Image, size: int = 128) -> None:
    """QA sheet: the cut-out crest on a light and a dark background, so
    the transparent version can be judged in both browser themes."""
    sheet = Image.new("RGB", (size * 2, size), (255, 255, 255))
    sheet.paste(Image.new("RGB", (size, size), CANVAS_BG[:3]), (size, 0))
    icon = square_icon(crest, size, TRANSPARENT, margin=FAVICON_MARGIN)
    sheet.paste(icon, (0, 0), icon)
    sheet.paste(icon, (size, 0), icon)
    out_path = BASE_DIR / "icon-preview.png"
    sheet.save(out_path)
    print(f"Saved {out_path.name} (light | dark preview) — check this file!")


def generate():
    try:
        raw = Image.open(SOURCE).convert("RGBA")
    except FileNotFoundError:
        print(f"ERROR: '{SOURCE.name}' not found in {BASE_DIR}.")
        print("Save the real KHU logo here first, named exactly 'khu-logo.png'.")
        return

    crest = strip_background(raw)

    # ── Favicon: transparent background ──
    frames = [square_icon(crest, size, TRANSPARENT, margin=FAVICON_MARGIN)
              for size in FAVICON_SIZES]
    frames[-1].save(
        BASE_DIR / "favicon.ico",
        format="ICO",
        sizes=[(size, size) for size in FAVICON_SIZES],
        append_images=frames[:-1],
    )
    print(f"Saved favicon.ico ({', '.join(f'{s}x{s}' for s in FAVICON_SIZES)}) — transparent")

    # ── PWA icons: crest on the app's dark tile ──
    for size in PWA_SIZES:
        out_path = BASE_DIR / f"icon-{size}.png"
        square_icon(crest, size, CANVAS_BG).save(out_path)
        print(f"Saved {out_path.name} ({size}x{size}) — crest on app tile")

    save_preview(crest)

    print("\nDone. Check icon-preview.png, then hard-refresh the browser tab")
    print("(favicons are cached aggressively) to see the new favicon.")


if __name__ == "__main__":
    generate()

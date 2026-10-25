"""
generate_icons.py — Regenerate the favicon and the PWA / store app icons from
khu-crest.png (the crest with a REAL transparent background) in this folder.

    python generate_icons.py        (needs: pip install pillow)

History: icons used to be cut from khu-logo.png, which is a screenshot of a
transparent image — it has the grey/white "transparency checkerboard" baked into
its pixels, so the installed home-screen icon showed a checkerboard. khu-crest.png
has genuine alpha, so no knock-out is needed.

Outputs
    favicon.ico          16/32/48, transparent background
    icon-192.png         crest on the app's dark tile (home-screen icons need an
    icon-512.png         opaque background: iOS composites alpha onto black)
    icon-maskable-512.png  same, with extra padding — Android may crop it to a
                         circle/squircle, so the crest stays inside the safe zone
    apple-touch-icon.png 180px, iOS home screen
"""
from pathlib import Path
from PIL import Image

BASE = Path(__file__).resolve().parent
CREST = Image.open(BASE / "khu-crest.png").convert("RGBA")
TILE = (13, 17, 23, 255)


def tile(size, fill_ratio):
    canvas = Image.new("RGBA", (size, size), TILE)
    w = int(size * fill_ratio)
    h = int(w * CREST.height / CREST.width)
    crest = CREST.resize((w, h), Image.LANCZOS)
    canvas.alpha_composite(crest, ((size - w) // 2, (size - h) // 2))
    return canvas.convert("RGB")


tile(192, 0.78).save(BASE / "icon-192.png", optimize=True)
tile(512, 0.78).save(BASE / "icon-512.png", optimize=True)
tile(512, 0.58).save(BASE / "icon-maskable-512.png", optimize=True)   # safe zone: inner ~60%
tile(180, 0.78).save(BASE / "apple-touch-icon.png", optimize=True)

fav = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
w = 248; h = int(w * CREST.height / CREST.width)
fav.alpha_composite(CREST.resize((w, h), Image.LANCZOS), ((256 - w) // 2, (256 - h) // 2))
fav.save(BASE / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
print("icons regenerated")

"""
generate_icons.py — Regenerate PWA app icons from the real KHU logo.

Run this AFTER saving khu-logo.png into the public/ folder.

Usage (from inside khu-frontend/public/):
    python generate_icons.py

Requires Pillow: pip install pillow
"""

from PIL import Image

SOURCE = "khu-logo.png"
SIZES = [192, 512]

def generate():
    try:
        img = Image.open(SOURCE).convert("RGBA")
    except FileNotFoundError:
        print(f"ERROR: '{SOURCE}' not found in this folder.")
        print("Save the real KHU logo here first, named exactly 'khu-logo.png'.")
        return

    for size in SIZES:
        # Resize while keeping aspect ratio, then paste onto a square canvas
        # so the icon looks correct on all home-screen icon shapes.
        resized = img.copy()
        resized.thumbnail((size, size), Image.LANCZOS)

        canvas = Image.new("RGBA", (size, size), (13, 17, 23, 255))  # matches app bg
        offset = ((size - resized.width) // 2, (size - resized.height) // 2)
        canvas.paste(resized, offset, resized)

        out_name = f"icon-{size}.png"
        canvas.save(out_name)
        print(f"Saved {out_name} ({size}x{size})")

    print("\nDone. Refresh your app to see the new icons.")

if __name__ == "__main__":
    generate()

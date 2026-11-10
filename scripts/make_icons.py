"""Render the Airglide app icons from the brand mark (BRAND_SVG in views/icons.js).

    python scripts/make_icons.py

Writes Assets/icon.png (1024 px), Assets/icon.icns (macOS) and Assets/icon.ico
(Windows): the blue glide mark on a white rounded tile. Needs Pillow; the
.icns step uses macOS's iconutil and is skipped elsewhere.
"""
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ASSETS = os.path.join(ROOT, "Assets")
BLUE = (37, 99, 235)   # --primary
SS = 4                 # supersampling for smooth edges

# The two paths of BRAND_SVG (32x32 viewBox), as absolute cubic Béziers.
MARK = [
    # (start, [(c1, c2, end), ...], opacity)
    ((5, 22.5), [((9, 11), (15, 5.5), (21.5, 5.5)),
                 ((24.7, 5.5), (26.8, 6.9), (27.5, 9)),
                 ((22.9, 7.6), (16.3, 11), (11.1, 22.5))], 1.0),
    ((9.5, 26.5), [((15.3, 17.3), (20.8, 13.9), (27, 15.1)),
                   ((25.4, 20.9), (19.4, 26.5), (9.5, 26.5))], 0.55),
]


def _bezier(p0, c1, c2, p1, steps=64):
    pts = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        pts.append((u ** 3 * p0[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t ** 3 * p1[0],
                    u ** 3 * p0[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t ** 3 * p1[1]))
    return pts


def render(size=1024, macos=True):
    """macOS icons sit on an 824 px tile with a soft shadow inside a 1024 canvas;
    Windows icons use the whole canvas."""
    S = size * SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    inset = round(S * 100 / 1024) if macos else round(S * 0.02)
    tile = (inset, inset, S - inset, S - inset)
    side = tile[2] - tile[0]
    radius = round(side * 0.225)

    if macos:  # soft drop shadow under the tile
        shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            (tile[0], tile[1] + S // 80, tile[2], tile[3] + S // 80), radius, fill=(17, 24, 39, 70))
        img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(S / 60)))
    ImageDraw.Draw(img).rounded_rectangle(tile, radius, fill=(255, 255, 255, 255))

    # Mark: its bounding box is x 5..27.5, y 5.5..26.5; scale it to ~56% of the tile.
    scale = side * 0.56 / 22.5
    cx, cy = (5 + 27.5) / 2, (5.5 + 26.5) / 2
    ox, oy = S / 2 - cx * scale, S / 2 - cy * scale
    for start, curves, opacity in MARK:
        pts, cur = [start], start
        for c1, c2, end in curves:
            pts += _bezier(cur, c1, c2, end)
            cur = end
        layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        ImageDraw.Draw(layer).polygon([(ox + x * scale, oy + y * scale) for x, y in pts],
                                      fill=BLUE + (round(255 * opacity),))
        img.alpha_composite(layer)
    return img.resize((size, size), Image.LANCZOS)


def main():
    mac = render(1024, macos=True)
    mac.save(os.path.join(ASSETS, "icon.png"))
    print("Wrote Assets/icon.png")

    win = render(256, macos=False)
    win.save(os.path.join(ASSETS, "icon.ico"),
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("Wrote Assets/icon.ico")

    if sys.platform == "darwin" and shutil.which("iconutil"):
        with tempfile.TemporaryDirectory() as tmp:
            iconset = os.path.join(tmp, "icon.iconset")
            os.makedirs(iconset)
            for pt in (16, 32, 128, 256, 512):
                mac.resize((pt, pt), Image.LANCZOS).save(os.path.join(iconset, f"icon_{pt}x{pt}.png"))
                mac.resize((pt * 2, pt * 2), Image.LANCZOS).save(os.path.join(iconset, f"icon_{pt}x{pt}@2x.png"))
            subprocess.check_call(["iconutil", "-c", "icns", iconset, "-o", os.path.join(ASSETS, "icon.icns")])
        print("Wrote Assets/icon.icns")


if __name__ == "__main__":
    main()

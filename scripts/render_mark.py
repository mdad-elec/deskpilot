#!/usr/bin/env python3
"""Render the Deskpilot mark to PNG.

Why this exists rather than an `magick convert` one-liner: ImageMagick's built-in
SVG renderer silently drops `stroke` on an unfilled shape, so the mark's outer
ring vanishes and you get a logo that is missing a third of its design with no
error. It only renders correctly when librsvg happens to be installed. Rather
than document a command that works on some machines, the geometry is drawn here
directly — same numbers as deskpilot/public/img/deskpilot_mark.svg.

If you edit the SVG, edit this too. They are small and they are checked against
each other by tests/test_mark.py.

    python3 scripts/render_mark.py logo.png --size 512
    python3 scripts/render_mark.py ghost.png --size 104 --ghost
"""

import argparse

from PIL import Image, ImageDraw, ImageEnhance

# The SVG's coordinate space, and its geometry.
VIEWBOX = 64.0
INK = (31, 41, 55)                       # #1f2937
RING = dict(cx=32, cy=32, r=28, width=3)
CROSS = [(8, 32), (32, 25), (56, 32), (32, 39)]     # 45% opacity
POINTER = [(32, 8), (39, 32), (32, 56), (25, 32)]
CENTRE = dict(cx=32, cy=32, r=3.5)
SUPERSAMPLE = 8                          # drawn big, then reduced: cheap antialiasing


def render(size, background=None):
    """The mark at `size` px. Transparent unless a background colour is given."""
    s = size * SUPERSAMPLE
    k = s / VIEWBOX
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def pt(p):
        return (p[0] * k, p[1] * k)

    r = RING["r"] * k
    cx, cy = RING["cx"] * k, RING["cy"] * k
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(*INK, 255),
              width=max(1, round(RING["width"] * k)))

    # Drawn onto its own layer so the 45% opacity composites rather than replacing.
    faint = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(faint).polygon([pt(p) for p in CROSS], fill=(*INK, 115))
    img.alpha_composite(faint)

    d.polygon([pt(p) for p in POINTER], fill=(*INK, 255))

    cr = CENTRE["r"] * k
    d.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=(255, 255, 255, 255))

    img = img.resize((size, size), Image.LANCZOS)
    if background:
        flat = Image.new("RGBA", img.size, background)
        flat.alpha_composite(img)
        img = flat.convert("RGB")
    return img


def ghost(size):
    """The dismissed launcher: the widget's grayscale(1) contrast(.35) brightness(1.25)."""
    img = render(int(size * 0.72), background=(255, 255, 255, 255))
    img = ImageEnhance.Color(img).enhance(0.0)
    img = ImageEnhance.Contrast(img).enhance(0.45)
    img = ImageEnhance.Brightness(img).enhance(1.15)
    canvas = Image.new("RGB", (size, size), (255, 255, 255))
    canvas.paste(img, ((size - img.width) // 2, (size - img.height) // 2))
    return canvas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--ghost", action="store_true")
    ap.add_argument("--white", action="store_true",
                    help="flatten onto white (some listings render logos on dark)")
    a = ap.parse_args()
    if a.ghost:
        img = ghost(a.size)
    else:
        img = render(a.size, background=(255, 255, 255, 255) if a.white else None)
    img.save(a.out)
    print("wrote %s (%dx%d)" % (a.out, img.width, img.height))


if __name__ == "__main__":
    main()

"""Generates assets/icon.png, assets/icon.ico (app icon with a tile) and assets/logo.png (same mosaic, transparent, for the sidebar).  Run: python tools/make_icon.py"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "assets"
S = 1024                      # drawn big, then downsampled for smooth edges
BG = (20, 23, 31)
ROWS = [                      # (relative tile widths, color per tile)
    ([1.0, 1.7], [(139, 108, 255), (255, 107, 157)]),
    ([1.6, 1.0, 1.2], [(255, 201, 51), (64, 201, 198), (90, 160, 255)]),
    ([1.2, 1.0], [(110, 214, 120), (255, 140, 66)]),
]


def mix(c, t):               # lighten toward white
    return tuple(int(v + (255 - v) * t) for v in c)


def draw(background=True):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if background:
        d.rounded_rectangle((0, 0, S - 1, S - 1), radius=int(S * 0.225), fill=BG)
    pad, gap = int(S * (0.15 if background else 0.03)), int(S * 0.035)
    inner = S - 2 * pad
    row_h = (inner - gap * (len(ROWS) - 1)) / len(ROWS)
    y = pad
    for widths, colors in ROWS:
        usable = inner - gap * (len(widths) - 1)
        total = sum(widths)
        x = pad
        for w, col in zip(widths, colors):
            tw = usable * w / total
            tile = Image.new("RGBA", (int(tw), int(row_h)), col)
            glow = Image.new("RGBA", tile.size, (0, 0, 0, 0))   # soft highlight fading downwards
            g = ImageDraw.Draw(glow)
            for i in range(tile.height):
                g.line((0, i, tile.width, i), fill=mix(col, 0.45) + (int(110 * (1 - i / tile.height) ** 2),))
            tile = Image.alpha_composite(tile, glow)
            mask = Image.new("L", tile.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, tile.width - 1, tile.height - 1), radius=int(S * 0.04), fill=255)
            img.paste(tile, (int(x), int(y)), mask)
            x += tw + gap
        y += row_h + gap
    return img


if __name__ == "__main__":
    big = draw()
    OUT.mkdir(exist_ok=True)
    big.resize((512, 512), Image.Resampling.LANCZOS).save(OUT / "icon.png")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    big.save(OUT / "icon.ico", sizes=[(s, s) for s in sizes])
    draw(background=False).resize((256, 256), Image.Resampling.LANCZOS).save(OUT / "logo.png")
    print("wrote", OUT / "icon.png", OUT / "icon.ico")

"""Turns a Layout + image files into the final collage image."""
import colorsys
import io
import math
import os
import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime

from PIL import Image

from ..core.config import OUTPUT_DIR
from .layout import Layout, grid, justified

Image.MAX_IMAGE_PIXELS = None  # collages are legitimately huge
_size_cache = {}


def ratio_of(path) -> float:
    key = (str(path), os.path.getmtime(path))
    if key not in _size_cache:
        with Image.open(path) as im:
            _size_cache[key] = im.width / im.height
    return _size_cache[key]


def aspect_from(text: str, landscape: bool = False) -> float:
    """'2:3' -> width/height. Presets are written portrait; landscape flips them. '' = free (0)."""
    if not text:
        return 0.0
    w, _, h = text.partition(":")
    w, h = sorted((float(w), float(h or 1)))      # short side first
    return (h / w) if landscape else (w / h)


def readable(path) -> bool:
    try:
        ratio_of(path)
        return True
    except Exception:
        return False


@dataclass
class Options:
    mode: str = "justified"        # justified | grid
    width: int = 4000
    gap: int = 0
    margin: int = 0
    row_height: int = 300          # target (justified)
    equal_rows: bool = True
    columns: int = 0               # grid, 0 = auto
    aspect: float = 0.0            # wanted overall width/height (0 = free); e.g. 2/3 portrait, 1 square
    order: str = "az"              # az | za | shuffle | hue | bright
    direction: str = "vertical"    # for hue / bright: which way the colors run - vertical | horizontal | diagonal
    color_mode: str = "average"    # for hue: average | dominant | accent (see color_of)
    reverse: bool = False          # flip the color / brightness order
    fit: str = "keep"              # keep = never crop or stretch (only resize) | crop = fill every cell
    seed: int = 1
    bg: tuple = (0, 0, 0)
    fmt: str = "JPEG"              # JPEG | PNG
    quality: int = 92


_color_cache = {}
COLOR_MODES = {"average": "Mean color of the whole image: a white cover with a small red logo counts as white",
               "dominant": "Most common hue: only a picture that is mostly white, black or gray counts as neutral",
               "accent": "The most colorful part: a white cover with a small red logo counts as red"}


def color_of(path, mode="average"):
    """(r, g, b) representing an image, cached. average = mean; dominant = most frequent color; accent = colorful pixels only."""
    key = (str(path), os.path.getmtime(path), mode)
    if key in _color_cache:
        return _color_cache[key]
    with Image.open(path) as im:
        im.draft("RGB", (96, 96))
        im = im.convert("RGB")
        mean = im.resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
        small = im.resize((32, 32), Image.Resampling.BOX)
    px = list(small.getdata())
    out = mean
    if mode == "dominant":
        bins = {}                                      # most common *hue*; white / black / gray pixels do not count
        for r, g, b in px:
            h, s_, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            if s_ > 0.2 and v > 0.15:
                bins.setdefault(int(h * 12) % 12, []).append(h)
        colorful = sum(len(v) for v in bins.values())
        if colorful >= 0.08 * len(px):                 # otherwise the picture really is mostly neutral: keep its mean color
            top = max(bins.values(), key=len)
            x = sum(math.cos(h * 2 * math.pi) for h in top)
            y = sum(math.sin(h * 2 * math.pi) for h in top)
            out = tuple(round(c * 255) for c in colorsys.hsv_to_rgb((math.atan2(y, x) / (2 * math.pi)) % 1.0, 1, 1))
    elif mode == "accent":
        wsum = x = y = 0.0
        colorful = 0
        for r, g, b in px:
            h, s_, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            if s_ > 0.25 and v > 0.2:                 # white, black and gray pixels do not vote
                w = s_ * v
                wsum += w
                x += w * math.cos(h * 2 * math.pi)
                y += w * math.sin(h * 2 * math.pi)
                colorful += 1
        if colorful >= 0.03 * len(px) and wsum:      # at least ~3% of the picture is actually colored
            h = (math.atan2(y, x) / (2 * math.pi)) % 1.0
            out = tuple(round(c * 255) for c in colorsys.hsv_to_rgb(h, 1, 1))
    _color_cache[key] = out
    return out


def average_color(path):
    return color_of(path, "average")


def color_key(path, by, mode="average"):
    """Sort key: 'hue' runs through the rainbow (grays last, dark to light); 'bright' runs dark to light."""
    r, g, b = (c / 255 for c in color_of(path, "average" if by == "bright" else mode))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    if by == "bright":
        return (lum,)
    return (1, lum) if s < 0.15 else (0, h)


def order_items(labels, order, seed, path_of=None, mode="average", reverse=False, check=None):
    """check: called now and then while working; it may raise to stop early (a cancelled preview)."""
    items = sorted(labels, key=lambda s: s.casefold())
    if order in ("hue", "bright"):
        def key(l):
            if check:
                check()
            return color_key(path_of[l], order, mode)
        items.sort(key=key)
        if reverse:
            items.reverse()
    elif order == "za":
        items.reverse()
    elif order == "shuffle":
        random.Random(seed).shuffle(items)
    return items


def make_layout(paths, o: Options, check=None) -> Layout:
    ratios = []
    for p in paths:
        if check:
            check()
        ratios.append(ratio_of(p))
    if o.mode == "grid":
        return grid(ratios, o.width, o.gap, o.margin, o.columns, aspect=o.aspect, keep=o.fit == "keep")
    return justified(ratios, o.width, o.gap, o.margin, o.row_height, True, o.equal_rows and o.fit != "keep", o.aspect,
                     keep=o.fit == "keep", check=check)


def arrange(paths, layout: Layout, direction: str):
    """`paths` are in color order. Hand them to the cells so the colors run vertically, horizontally or diagonally."""
    def pos(c):
        cx, cy = (c.x + c.w / 2) / layout.width, (c.y + c.h / 2) / layout.height
        return {"horizontal": (cx, cy), "diagonal": (cx + cy, cy)}.get(direction, (cy, cx))

    out = list(paths)
    for rank, cell in enumerate(sorted(layout.cells, key=pos)):
        out[cell.index] = paths[rank]
    return out


def _cover(path, w, h):
    with Image.open(path) as im:
        s = max(w / im.width, h / im.height)
        nw, nh = max(w, round(im.width * s)), max(h, round(im.height * s))
        im.draft("RGB", (nw, nh))  # fast, reduced-size JPEG decode
        im = im.convert("RGB").resize((nw, nh), Image.Resampling.LANCZOS)
    l, t = (nw - w) // 2, (nh - h) // 2
    return im.crop((l, t, l + w, t + h))


def _fitted(path, w, h, keep):
    """Image for a w x h cell, and its offset inside the cell. keep: only resized (letterboxed if the shapes differ)."""
    if keep:
        with Image.open(path) as im:
            ratio = im.width / im.height
        if abs(ratio / (w / h) - 1) > 0.03:           # clearly different shape: never crop or stretch it
            iw, ih = (w, max(1, round(w / ratio))) if ratio >= w / h else (max(1, round(h * ratio)), h)
            with Image.open(path) as im:
                im.draft("RGB", (iw, ih))
                img = im.convert("RGB").resize((iw, ih), Image.Resampling.LANCZOS)
            return img, ((w - iw) // 2, (h - ih) // 2)
    return _cover(path, w, h), (0, 0)             # same shape (up to a pixel of rounding): fill the cell exactly


def render(paths, layout: Layout, bg=(0, 0, 0), progress=None) -> Image.Image:
    canvas = Image.new("RGB", (layout.width, layout.height), bg)
    total = len(layout.cells)
    keep = layout.fit == "keep"
    ex = ThreadPoolExecutor(min(8, os.cpu_count() or 4))
    try:
        futs = ex.map(lambda c: (c, *_fitted(paths[c.index], c.w, c.h, keep)), layout.cells)
        for n, (c, img, off) in enumerate(futs, 1):
            canvas.paste(img, (c.x + off[0], c.y + off[1]))
            if progress:
                progress(n, total)             # may raise to stop early (a cancelled preview): the queued images are dropped
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    return canvas


def render_region(paths, layout: Layout, box, bg=(0, 0, 0)) -> Image.Image:
    """Just the part of a (scaled) layout inside box = (x, y, w, h): what a zoomed-in preview needs at full detail."""
    x, y, w, h = box
    canvas = Image.new("RGB", (w, h), bg)
    keep = layout.fit == "keep"
    cells = [c for c in layout.cells if c.x < x + w and c.x + c.w > x and c.y < y + h and c.y + c.h > y]
    with ThreadPoolExecutor(min(8, os.cpu_count() or 4)) as ex:
        for c, img, off in ex.map(lambda c: (c, *_fitted(paths[c.index], c.w, c.h, keep)), cells):
            canvas.paste(img, (c.x + off[0] - x, c.y + off[1] - y))
    return canvas


def estimate_size(preview: Image.Image, full_w: int, full_h: int, o: Options) -> int:
    """Rough size in bytes of the saved file: the preview is encoded the same way and its bytes per pixel scaled to the full size."""
    buf = io.BytesIO()
    if o.fmt == "PNG":
        preview.save(buf, "PNG", optimize=False)
    else:
        preview.save(buf, "JPEG", quality=o.quality, subsampling=0)
    return int(buf.tell() / max(1, preview.width * preview.height) * full_w * full_h)


def save(img: Image.Image, name: str, o: Options):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ext = "png" if o.fmt == "PNG" else "jpg"
    if ext == "jpg" and max(img.size) > 65500:
        raise ValueError("JPEG can't be larger than 65500 px per side - lower the width or use PNG.")
    path = OUTPUT_DIR / f"{name}_{datetime.now():%Y%m%d_%H%M%S}.{ext}"
    if ext == "png":
        img.save(path, optimize=False)
    else:
        img.save(path, quality=o.quality, subsampling=0)
    return path

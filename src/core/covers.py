"""Finds albums that share a cover: a perceptual hash (dHash) per poster, compared only between albums of the same artist.

Hashing is the slow part, so it runs on a thread pool (image decoding releases the GIL) and the results are cached in
data/albums/cover_hashes.json, keyed by file name + size + modified time. Looking for matches afterwards only compares
cached hashes, so it is cheap enough to call often."""
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageStat

from .config import kind_dir
from .jsonstore import read_json, write_json

HASH_W, HASH_H = 9, 8              # 9x8 grayscale -> 8 comparisons per row x 8 rows = 64 bits
MAX_DISTANCE = 6                   # bits that may differ (of 64) for two covers to count as the same picture
MIN_CONTRAST = 6.0                 # flat / empty images all look alike: they are never matched

_cache = {"mtime": None, "data": {}}


def _file(kind="albums"):
    return kind_dir(kind) / "cover_hashes.json"


def _load(kind="albums") -> dict:
    f = _file(kind)
    try:
        mt = f.stat().st_mtime_ns
    except OSError:
        mt = None
    if _cache["mtime"] != mt or not _cache["data"] and mt:
        _cache["mtime"], _cache["data"] = mt, read_json(f, {})
    return _cache["data"]


def dhash(path):
    """64-bit difference hash of an image, or None when it can not be read or has no real picture in it."""
    try:
        with Image.open(path) as im:
            im.draft("L", (64, 64))                              # JPEGs decode at a fraction of their size
            g = im.convert("L").resize((HASH_W, HASH_H), Image.Resampling.LANCZOS)
        if ImageStat.Stat(g).stddev[0] < MIN_CONTRAST:
            return None
        px = g.tobytes()
        bits = 0
        for y in range(HASH_H):
            for x in range(HASH_W - 1):
                bits = (bits << 1) | (px[y * HASH_W + x] > px[y * HASH_W + x + 1])
        return bits
    except Exception:
        return None


def _stamp(path):
    st = os.stat(path)
    return [st.st_size, st.st_mtime_ns]


def hash_posters(lib, progress=None, workers=None) -> int:
    """Hash every poster of `lib` that is not cached yet (or has changed), in parallel. Returns how many were computed."""
    data = dict(_load(lib.kind))
    todo = []
    for label in lib.items:
        p = lib.poster(label)
        if not p:
            continue
        try:
            stamp = _stamp(p)
        except OSError:
            continue
        hit = data.get(p.name)
        if not hit or hit[:2] != stamp:
            todo.append((p, stamp))
    if not todo:
        return 0
    done = 0
    with ThreadPoolExecutor(max_workers=workers or min(16, (os.cpu_count() or 4) * 2)) as pool:
        for (p, stamp), h in zip(todo, pool.map(lambda t: dhash(t[0]), todo)):
            data[p.name] = stamp + [h]
            done += 1
            if progress and done % 25 == 0:
                progress(done, len(todo))
    write_json(_file(lib.kind), data)
    _cache["mtime"], _cache["data"] = None, {}                  # re-read next time (the file just changed)
    if progress:
        progress(len(todo), len(todo))
    return len(todo)


def hashes_of(lib) -> dict:
    """{label: hash} of the posters whose cached hash is current (for the data export)."""
    data, out = _load(lib.kind), {}
    for label in lib.items:
        p = lib.poster(label)
        hit = data.get(p.name) if p else None
        try:
            if hit and hit[:2] == _stamp(p):
                out[label] = hit[2]
        except OSError:
            pass
    return out


def store_hashes(lib, hashes: dict):
    """Put hashes of known covers into the cache (the data import, so duplicates are found again without hashing)."""
    if not hashes:
        return
    data = dict(_load(lib.kind))
    for label, h in hashes.items():
        p = lib.poster(label)
        if p:
            try:
                data[p.name] = _stamp(p) + [h]
            except OSError:
                pass
    write_json(_file(lib.kind), data)
    _cache["mtime"], _cache["data"] = None, {}


def complete(lib) -> bool:
    """Is every poster of `lib` hashed? Without that, 'same cover' duplicates can not be told apart yet."""
    data = _load(lib.kind)
    return all(not (p := lib.poster(l)) or p.name in data for l in lib.items)


def _artist(lib, label) -> str:
    creators = lib.meta.get(label).get("creators")
    return (creators[0] if creators else label.split(" - ", 1)[0]).casefold().strip()


def similar(lib, labels) -> list:
    """[[label, ...], ...]: albums whose covers look the same and that share the artist or the album title
    (from cached hashes only)."""
    from .editions import base_key
    data = _load(lib.kind)
    items, buckets = [], defaultdict(list)
    for l in labels:
        p = lib.poster(l)
        hit = data.get(p.name) if p else None
        if hit and hit[2] is not None:
            i = len(items)
            items.append((l, hit[2]))
            buckets[("artist", _artist(lib, l))].append(i)
            buckets[("title", base_key(lib.name(l)))].append(i)       # the same album under another artist spelling
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for idx in buckets.values():
        for x in range(len(idx)):
            for y in range(x + 1, len(idx)):
                i, j = idx[x], idx[y]
                if (items[i][1] ^ items[j][1]).bit_count() <= MAX_DISTANCE:
                    parent[find(j)] = find(i)
    groups = defaultdict(list)
    for i, (l, _) in enumerate(items):
        groups[find(i)].append(l)
    return [sorted(g, key=str.casefold) for g in groups.values() if len(g) > 1]


# ---- cover colors (for sorting albums by color) ------------------------------------------------------------------
_colors = {"mtime": None, "data": {}}


def _colors_file(kind="albums"):
    return kind_dir(kind) / "cover_colors.json"


def _load_colors(kind="albums") -> dict:
    f = _colors_file(kind)
    try:
        mt = f.stat().st_mtime_ns
    except OSError:
        mt = None
    if _colors["mtime"] != mt:
        _colors["mtime"], _colors["data"] = mt, read_json(f, {})
    return _colors["data"]


def warm_colors(lib) -> int:
    """Work out the color of every poster that is not cached yet (in parallel) and keep it in cover_colors.json."""
    from ..collage.render import color_of
    data = dict(_load_colors(lib.kind))
    todo = []
    for label in lib.items:
        p = lib.poster(label)
        if not p:
            continue
        try:
            stamp = _stamp(p)
        except OSError:
            continue
        hit = data.get(p.name)
        if not hit or hit[:2] != stamp:
            todo.append((p, stamp))
    if not todo:
        return 0

    def work(t):
        try:
            return list(color_of(t[0], "dominant"))
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=min(16, (os.cpu_count() or 4) * 2)) as pool:
        for (p, stamp), rgb in zip(todo, pool.map(work, todo)):
            data[p.name] = stamp + [rgb]
    write_json(_colors_file(lib.kind), data)
    _colors["mtime"] = None
    return len(todo)


def color_key(lib, label, by="hue"):
    """Sort key from the cached color of the item's poster (items without one sort last)."""
    import colorsys
    p = lib.poster(label)
    hit = _load_colors(lib.kind).get(p.name) if p else None
    if not hit or not hit[2]:
        return (2, 0)
    r, g, b = (c / 255 for c in hit[2])
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    if by == "bright":
        return (0, lum)
    return (1, lum) if s < 0.15 else (0, h)

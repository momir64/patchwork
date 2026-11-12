"""Singles / EPs that are really part of an album you already have.

A single whose songs are on an album of the same artist in the library is hidden (like a duplicate edition) while that album is
there, and shows again when it is gone. Which albums are singles, and which songs they hold, comes from Deezer (see
sources/releases.py) and is cached in data/albums/releases.json; matching afterwards only reads that cache.

Stored in duplicates.json (next to the duplicate state):
  singles        {single: [albums it belongs to]}   confirmed links
  single_hidden  [titles hidden because they are a single of an album]
  not_single     [titles you said are not singles, so they are not offered again]
"""
import re
import time
from collections import defaultdict

from . import covers, editions
from .config import kind_dir
from .jsonstore import read_json, write_json
from .names import fold, norm_key

KIND = "albums"
REFRESH_AFTER = 3 * 86400                         # a discography is asked again after this long when an album is not in it
EP_FROM = 5                                       # Spotify calls an EP a single too: from this many songs it is an EP


def spotify_type(album_type, tracks) -> str:
    """Spotify's album_type (+ number of songs) as our release type: album / single / ep / compile."""
    return {"compilation": "compile", "single": "single" if (tracks or 0) < EP_FROM else "ep"}.get(album_type, "album")


# ---- what you decided ---------------------------------------------------------------------------------------------
def _state(kind=KIND):
    return editions._dup_state(kind)


def _write(d, kind=KIND):
    write_json(editions._dup_file(kind), d)


def singles_map(kind=KIND) -> dict:
    return _state(kind)["singles"]


def single_keys(kind=KIND) -> set:
    return {norm_key(s) for s in singles_map(kind)}


def hidden_keys(kind=KIND) -> set:
    """Titles hidden because they are a single (as normalized keys)."""
    return {norm_key(l) for l in _state(kind)["single_hidden"]}


def mark_single(lib, single: str, albums):
    """`single` is a single / EP whose songs are on these albums (one or several: a few-song single can span albums)."""
    d = _state(lib.kind)
    k = norm_key(single)
    d["singles"] = {s: v for s, v in d["singles"].items() if norm_key(s) != k}
    d["singles"][single] = sorted(set(albums))
    d["not_single"] = [l for l in d["not_single"] if norm_key(l) != k]
    _write(d, lib.kind)


def mark_not_single(lib, labels):
    """These are not singles of anything: shown, and not offered again."""
    d = _state(lib.kind)
    keys = {norm_key(l) for l in labels}
    d["not_single"] = sorted({*d["not_single"], *labels})
    d["singles"] = {s: v for s, v in d["singles"].items() if norm_key(s) not in keys}
    _write(d, lib.kind)


def in_duplicates(lib) -> set:
    """Titles that are part of a duplicate set (resolved or not). The duplicates tool already decided which of them is shown, so the
    singles tool leaves them alone: hiding the one that was kept could make the picture disappear from the library."""
    return {norm_key(l) for g in editions.groups(lib.items, lib.kind, lib) for l in g}


def hide(lib, singles) -> tuple:
    """Hide these singles when one of their albums is in the library (shown: otherwise nothing of it would be left to see).
    A single that is part of a duplicate set is never touched. Returns (hidden, kept): how many were hidden, and how many stay
    visible (their albums are hidden or gone, or the duplicates tool decided about them)."""
    d, have = _state(lib.kind), {norm_key(l): l for l in lib.items}
    locked = in_duplicates(lib)
    hidden, kept = [], 0
    for s in singles:
        albums = [have[norm_key(a)] for a in d["singles"].get(s, []) if norm_key(a) in have and norm_key(a) != norm_key(s)]
        if norm_key(s) not in locked and any(not lib.is_hidden(a) for a in albums):
            lib.set_hidden(s, True)
            hidden.append(s)
        else:
            kept += 1
    d["single_hidden"] = sorted({*d["single_hidden"], *hidden})
    _write(d, lib.kind)
    lib.save()
    return len(hidden), kept


def release(lib, labels):
    """Not a single (any more): shown again unless you hid it yourself, and not offered again."""
    d = _state(lib.kind)
    keys = {norm_key(l) for l in labels}
    for l in labels:
        if norm_key(l) in {norm_key(x) for x in d["single_hidden"]} and lib.has(l):
            lib.set_hidden(l, False)
    d["single_hidden"] = [l for l in d["single_hidden"] if norm_key(l) not in keys]
    _write(d, lib.kind)
    mark_not_single(lib, labels)
    lib.save()


def sweep(lib) -> bool:
    """A single comes back when none of its albums is in the library any more (removed or renamed). Returns True when
    something changed."""
    d = _state(lib.kind)
    if not d["single_hidden"] and not d["singles"]:
        return False
    have = {norm_key(l): l for l in lib.items}
    exists = lambda s: [have[norm_key(a)] for a in d["singles"].get(s, []) if norm_key(a) in have and norm_key(a) != norm_key(s)]
    keep, changed, rejected = [], False, []
    for s in d["single_hidden"]:
        if not lib.has(s):
            changed = True                                    # gone
        elif not lib.is_hidden(s):
            changed = True                                    # you unhid it yourself: not a single then
            rejected.append(s)
        elif exists(s):
            keep.append(s)
        else:
            lib.set_hidden(s, False)
            changed = True
    waiting = [s for s in d["singles"] if s not in keep and s not in rejected and lib.has(s) and not lib.is_hidden(s)
               and any(not lib.is_hidden(a) for a in exists(s))]
    locked = in_duplicates(lib) if waiting else set()
    for s in waiting:                                         # linked while their album was hidden: hide them once it is shown
        if norm_key(s) not in locked:
            lib.set_hidden(s, True)
            keep.append(s)
            changed = True
    if changed:
        d["single_hidden"] = keep
        d["not_single"] = sorted({*d["not_single"], *rejected})
        d["singles"] = {s: v for s, v in d["singles"].items() if s not in rejected}
        _write(d, lib.kind)
        lib.save()
    return changed


# ---- what Deezer said (cache) ---------------------------------------------------------------------------------------
def _file(kind=KIND):
    return kind_dir(kind) / "releases.json"


def load_cache(kind=KIND) -> dict:
    """{artist key: {"id": Deezer artist id or None, "at": time, "albums": {id: {"t": title, "k": record type}},
    "tracks": {album id: [song titles]}}}"""
    return read_json(_file(kind), {}).get("artists", {})


def save_cache(artists: dict, kind=KIND):
    write_json(_file(kind), {"artists": artists})


def merge_cache(artists: dict, kind=KIND):
    """Add artists we do not know yet (the data import)."""
    have = load_cache(kind)
    new = {k: v for k, v in artists.items() if k not in have}
    if new:
        save_cache({**have, **new}, kind)


# ---- matching ---------------------------------------------------------------------------------------------------------
_NOISE = re.compile(r"\s*[\(\[][^)\]]*\b(?:feat\.?|ft\.?|featuring|with|remaster(?:ed)?|version|mono|stereo|explicit|clean|bonus|"
                    r"radio edit|single|album)\b[^)\]]*[\)\]]", re.I)
_TAIL = re.compile(r"\s+-\s+(?:\d{4}\s+)?(?:remaster(?:ed)?(?:\s+\d{4})?|(?:album|single|radio|mono|stereo|explicit|clean)\s*(?:version|edit)?)\s*$", re.I)


def song_key(title: str) -> str:
    """A song title as one key: featured artists, 'Remastered' and 'Album Version' tags are ignored, a remix or live version is not."""
    t = _TAIL.sub("", _NOISE.sub("", title))
    return re.sub(r"[^\w]+", " ", fold(t).replace("&", " and ").replace("’", "'")).strip().casefold()


def title_of(lib, label: str) -> str:
    return lib.meta.get(label).get("title") or label.split(" - ", 1)[-1]


def artist_of(lib, label: str) -> str:
    return covers._artist(lib, label)


def artists(lib) -> dict:
    """{artist key: [labels]} for the artists that have more than one title (a single needs an album next to it)."""
    by = defaultdict(list)
    for l in lib.items:
        by[artist_of(lib, l)].append(l)
    return {k: v for k, v in by.items() if len(v) > 1}


def match(lib, labels, entry) -> dict:
    """{label: [(Deezer album id, record type), ...]} for the titles Deezer lists under that artist."""
    by = defaultdict(list)
    for aid, a in (entry.get("albums") or {}).items():
        by[editions.base_key(a["t"])].append((aid, a["k"]))
    return {l: by[k] for l in labels if (k := editions.base_key(title_of(lib, l))) in by}


def is_single(hits) -> bool:
    return bool(hits) and all(k == "single" for _, k in hits)


def split(lib, labels, entry):
    """(singles, albums, hits): the titles Deezer calls a single, the other titles it knows, and the matches of all."""
    hits = match(lib, labels, entry)
    singles = [l for l in labels if is_single(hits.get(l))]
    albums = [l for l in labels if hits.get(l) and not is_single(hits[l])]
    return singles, albums, hits


def known_without_singles(lib, labels) -> bool:
    """Sync already saw the release type of every title of this artist and none of them is a single: nothing to look up."""
    types = [lib.meta.get(l).get("release_type") for l in labels]
    return all(types) and "single" not in types


def needs_lookup(lib, labels, entry) -> bool:
    """Does the artist still have to be looked up? (new artist, an album its list lacks, or songs not read yet)"""
    if entry is None:
        return not known_without_singles(lib, labels)
    if entry.get("id") is None:
        return False
    singles, albums, hits = split(lib, labels, entry)
    if len(hits) < len(labels) and time.time() - entry.get("at", 0) > REFRESH_AFTER:
        return True
    if not singles:
        return False
    tracks = entry.get("tracks", {})
    return any(h[0][0] not in tracks for h in (hits[s] for s in singles)) or \
        any(aid not in tracks for l in albums for aid, k in hits[l][:3])


def pending(lib, cache=None, only=None) -> list:
    """[(artist key, name, labels)] still to be looked up (only these artists when `only` is given)."""
    cache = load_cache(lib.kind) if cache is None else cache
    skip = single_keys(lib.kind) | {norm_key(l) for l in _state(lib.kind)["not_single"]}
    out = []
    for n, (key, labels) in enumerate(artists(lib).items()):
        if n % 25 == 0:
            time.sleep(0.001)                                  # (a pause now and then: the window keeps its loading line moving)
        if (only is not None and key not in only) or all(norm_key(l) in skip for l in labels):
            continue
        if needs_lookup(lib, labels, cache.get(key)):
            creators = lib.meta.get(labels[0]).get("creators")
            out.append((key, (creators[0] if creators else labels[0].split(" - ", 1)[0]), labels))
    return out


def proposals(lib) -> list:
    """The singles that are on albums of the same artist in the library, from what Deezer said:
    [{"single", "songs", "albums": [(label, [index of each of its songs found there])], "covered", "lead"}]. A title you already
    decided about is left out."""
    cache = load_cache(lib.kind)
    skip = single_keys(lib.kind) | hidden_keys(lib.kind) | {norm_key(l) for l in _state(lib.kind)["not_single"]} | in_duplicates(lib)
    out = []
    for n, (key, labels) in enumerate(artists(lib).items()):
        if n % 25 == 0:
            time.sleep(0.001)                                  # (a pause now and then: the window keeps its loading line moving)
        entry = cache.get(key)
        if not entry or not entry.get("albums"):
            continue
        singles, albums, hits = split(lib, labels, entry)
        songs_of = lambda ids: [t for aid in ids for t in entry.get("tracks", {}).get(aid, [])]
        on = {l: {song_key(t) for t in songs_of([aid for aid, k in hits[l] if k != "single"])} for l in albums}
        for s in singles:
            if norm_key(s) in skip or lib.is_hidden(s):
                continue
            songs = entry.get("tracks", {}).get(hits[s][0][0])
            if not songs:
                continue
            keys = [song_key(t) for t in songs]
            found = [(a, [i for i, k in enumerate(keys) if k in on[a]]) for a in albums if on[a]]
            found = [(a, idx) for a, idx in found if idx]
            if not found:
                continue
            covered = {i for _, idx in found for i in idx}
            found.sort(key=lambda f: (-len(f[1]), f[0].casefold()))
            out.append({"single": s, "songs": songs, "albums": found, "covered": len(covered), "lead": 0 in covered})
    out.sort(key=lambda p: (artist_of(lib, p["single"]), p["single"].casefold()))
    return out


def edit_items(lib) -> list:
    """The singles hidden earlier, in the same shape as proposals (to change your mind in the Singles tab)."""
    links, have, hidden = singles_map(lib.kind), {norm_key(l): l for l in lib.items}, hidden_keys(lib.kind)
    return [{"single": s, "songs": None, "albums": [(have[norm_key(a)], []) for a in links.get(s, []) if norm_key(a) in have],
             "covered": 0, "lead": True}
            for s in lib.items if norm_key(s) in hidden and links.get(s)]


def should_hide(p) -> bool:
    """Hidden by default only when every song of the single is on an album (a single with a song of its own starts kept)."""
    return p["covered"] == len(p["songs"])

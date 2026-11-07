"""Finds the same title more than once: albums in several editions (Deluxe, Remastered...), shows / movies listed with and
without a year or country tag ("Archer" / "Archer (2009)")."""
import re
from collections import defaultdict

from .config import kind_dir
from .jsonstore import read_json, write_json
from .names import norm_key

WORDS = (r"deluxe|remaster(?:ed)?|edition|expanded|anniversary|version|bonus|special|explicit|clean|reissue|re-issue|"
         r"collector'?s?|super|legacy|mono|stereo|original|digital|extended|platinum|limited|tour")
_PAREN = re.compile(rf"\s*[\(\[][^)\]]*\b(?:{WORDS})\b[^)\]]*[\)\]]", re.I)
_SUFFIX = re.compile(rf"\s*[-–:]\s*(?:\d{{4}}\s+)?(?:{WORDS})\b.*$", re.I)


def base_key(label: str) -> str:
    """'Ghost - Meliora (Deluxe Edition)' and 'Ghost - Meliora' share one key."""
    t = _PAREN.sub("", label)
    t = _SUFFIX.sub("", t)
    return re.sub(r"\s+", " ", t).strip().casefold()


_TAG = re.compile(r"\s*\((\d{4}|[A-Z]{2,3})\)\s*$")
_ARTICLE = re.compile(r"^(?:the|a|an)\s+", re.I)


def split_tag(label: str):
    """'Archer (2009)' -> ('Archer', '2009'); 'Archer' -> ('Archer', '')."""
    m = _TAG.search(label)
    return (label[:m.start()], m.group(1)) if m else (label, "")


def video_key(label: str) -> str:
    return norm_key(_ARTICLE.sub("", split_tag(label)[0]))


def set_id(group) -> str:
    return "|".join(sorted(norm_key(l) for l in group))


def _dup_file(kind):
    return kind_dir(kind) / "duplicates.json"


_STATE = {}                                         # kind -> (file mtime, state): the file is only re-read when it changed


def _dup_state(kind) -> dict:
    f = _dup_file(kind)
    try:
        mt = f.stat().st_mtime_ns
    except OSError:
        mt = None
    hit = _STATE.get(kind)
    if hit and hit[0] == mt:
        d = hit[1]
    else:
        d = read_json(f, {})
        _STATE[kind] = (mt, d)
    return {"separate": list(d.get("separate", [])), "hidden": list(d.get("hidden", [])), "manual": list(d.get("manual", [])),
            "apart": list(d.get("apart", []))}


def separate_ids(kind: str) -> set:
    """Sets the user marked as 'not duplicates', so they are not offered again."""
    return set(_dup_state(kind)["separate"])


def mark_separate(kind: str, group):
    d = _dup_state(kind)
    d["separate"] = sorted(set(d["separate"]) | {set_id(group)})
    write_json(_dup_file(kind), d)


ID_KEYS = {"shows": ("tmdb", "tvdb", "imdb", "trakt"), "movies": ("tmdb", "imdb", "trakt"), "albums": ("mbid",)}


def _join(found, extra):
    """Merge overlapping sets (union-find over the labels): [[a, b], [b, c]] -> [[a, b, c]]."""
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for g in list(found) + list(extra):
        for l in g[1:]:
            parent[find(l)] = find(g[0])
    out = defaultdict(list)
    for l in parent:
        out[find(l)].append(l)
    return [sorted(v, key=str.casefold) for v in out.values() if len(v) > 1]


def manual_sets(kind) -> list:
    return [list(g) for g in _dup_state(kind)["manual"]]


def mark_duplicates(kind: str, labels):
    """You say these are the same title: they show up in the duplicates dialog like any detected set."""
    d = _dup_state(kind)
    d["manual"] = d["manual"] + [sorted(set(labels))]
    d["separate"] = [i for i in d["separate"] if i != set_id(labels)]            # an earlier 'not duplicates' no longer applies
    write_json(_dup_file(kind), d)


def mark_apart(kind: str, group, apart):
    """In this exact set, the `apart` titles are not duplicates of the rest (the others stay a duplicate set)."""
    d = _dup_state(kind)
    sid = set_id(group)
    d["apart"] = [r for r in d["apart"] if r["set"] != sid] + [{"set": sid, "apart": sorted(apart)}]
    write_json(_dup_file(kind), d)


def groups(labels, kind="albums", lib=None) -> list:
    """[[label, ...], ...] - only the titles that exist more than once (and were not marked as different).
    With `lib`, titles that share an id (TMDB / IMDb / TVDB / Trakt, or the album's MusicBrainz id) and sets you marked by hand count too."""
    by = defaultdict(list)
    if kind == "albums":
        for l in labels:
            by[base_key(l)].append(l)
        found = [v for v in by.values() if len(v) > 1]
    else:
        for l in labels:
            by[video_key(l)].append(l)
        found = []
        for v in by.values():
            tagged = defaultdict(list)                  # a different year / country means a different title (remakes)
            for l in v:
                tagged[split_tag(l)[1]].append(l)
            tags = [t for t in tagged if t]
            if len(tags) <= 1 and len(v) > 1:           # at most one tag: the untagged ones are the same title
                found.append(v)
            else:
                found += [x for t, x in tagged.items() if len(x) > 1]
    if lib is not None:
        have = {norm_key(l): l for l in labels}
        extra = [[have[k] for k in dict.fromkeys(norm_key(l) for l in g) if k in have] for g in manual_sets(kind)]
        ids = defaultdict(list)
        for l in labels:
            known = lib.meta.get(l).get("ids", {})
            for key in ID_KEYS.get(kind, ()):
                if known.get(key):
                    ids[(key, str(known[key]))].append(l)
        extra += [v for v in ids.values() if len(v) > 1]
        if kind == "albums":
            from . import covers
            extra += covers.similar(lib, labels)            # same artist, same-looking cover
        found = _join(found, [g for g in extra if len(g) > 1])
    rules = {r["set"]: {norm_key(x) for x in r["apart"]} for r in _dup_state(kind)["apart"]}
    if rules:
        found = [[l for l in g if norm_key(l) not in rules.get(set_id(g), ())] for g in found]
        found = [g for g in found if len(g) > 1]
    skip = separate_ids(kind)
    return [g for g in found if set_id(g) not in skip]


def keeper(group, is_fav=lambda l: False, plays=lambda l: 0, poster=lambda l: None) -> str:
    """The one to keep: a favorite, then the most played, then one that has a poster, then the plain title, then the shortest."""
    return min(group, key=lambda l: (not is_fav(l), -plays(l), not poster(l), base_key(l) != l.casefold(), len(l), l.casefold()))


def simplest(group, kind="albums") -> str:
    """The simplest name of a set: no edition words / year / country tag, then the shortest."""
    plain = (lambda l: base_key(l) == l.casefold()) if kind == "albums" else (lambda l: not split_tag(l)[1])
    return min(group, key=lambda l: (not plain(l), len(l), l.casefold()))


# ---- titles hidden because they are a duplicate; they come back as soon as they stop being one
def load_dup_hidden(kind) -> set:
    return set(_dup_state(kind)["hidden"])


def save_dup_hidden(kind, labels):
    d = _dup_state(kind)
    d["hidden"] = sorted(labels)
    write_json(_dup_file(kind), d)


def sweep(lib) -> bool:
    """Unhide titles that were hidden as duplicates but are no longer part of a duplicate set (the other one was renamed,
    removed or marked 'not duplicates'). Returns True when something changed."""
    kind = lib.kind
    rec = load_dup_hidden(kind)
    if not rec:
        return False
    live = {norm_key(l) for g in groups(lib.items, kind, lib) for l in g}
    keep, changed = set(), False
    for l in rec:
        if not lib.has(l) or not lib.is_hidden(l):
            changed = True                              # gone, or you unhid it yourself
        elif norm_key(l) in live:
            keep.add(l)
        else:
            lib.set_hidden(l, False)
            changed = True
    if changed:
        save_dup_hidden(kind, keep)
        lib.save()
    return changed


def dedupe(items, is_fav=lambda l: False, plays=lambda l: 0):
    """items: [(kind, label, path)] -> the same list with one edition per album (albums only; other kinds untouched)."""
    albums = [l for k, l, _ in items if k == "albums"]
    drop = set()
    for g in groups(albums):
        keep = keeper(g, is_fav, plays)
        drop.update(l for l in g if l != keep)
    return [it for it in items if not (it[0] == "albums" and it[1] in drop)]

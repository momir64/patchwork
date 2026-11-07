"""Finds the same title more than once: albums in several editions (Deluxe, Remastered...), shows / movies listed with and
without a year or country tag ("Archer" / "Archer (2009)")."""
import json
import re
import shutil
from collections import defaultdict

from .config import kind_dir
from .names import norm_key, safe_filename

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


def separate_ids(kind: str) -> set:
    """Sets the user marked as 'not duplicates', so they are not offered again."""
    p = kind_dir(kind) / "not_duplicates.txt"
    return set(p.read_text(encoding="utf-8").splitlines()) if p.exists() else set()


def mark_separate(kind: str, group):
    p = kind_dir(kind) / "not_duplicates.txt"
    ids = separate_ids(kind) | {set_id(group)}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(sorted(ids)) + "\n", encoding="utf-8")


def groups(labels, kind="albums") -> list:
    """[[label, ...], ...] - only the titles that exist more than once (and were not marked as different)."""
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
    skip = separate_ids(kind)
    return [g for g in found if set_id(g) not in skip]


def keeper(group, is_fav=lambda l: False, plays=lambda l: 0, poster=lambda l: None) -> str:
    """The one to keep: a favorite, then the most played, then one that has a poster, then the plain title, then the shortest."""
    return min(group, key=lambda l: (not is_fav(l), -plays(l), not poster(l), base_key(l) != l.casefold(), len(l), l.casefold()))


def simplest(group, kind="albums") -> str:
    """The simplest name of a set: no edition words / year / country tag, then the shortest."""
    plain = (lambda l: base_key(l) == l.casefold()) if kind == "albums" else (lambda l: not split_tag(l)[1])
    return min(group, key=lambda l: (not plain(l), len(l), l.casefold()))


# ---- merge records: what a merge removed is kept, so the choice can be changed (or the merge undone) later
def _merged_file(kind):
    return kind_dir(kind) / "merged.json"


def merged_dir(kind):
    return kind_dir(kind) / "merged_posters"


def load_merged(kind) -> dict:
    """{kept label: {"chosen": label, "members": {label: {"meta": {...}, "fav": bool, "poster": path or None}}}}"""
    try:
        return json.loads(_merged_file(kind).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_merged(kind, data: dict):
    p = _merged_file(kind)
    if data:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    elif p.exists():
        p.unlink()


def snapshot(kind, lib, label) -> dict:
    """Copy a title's details and poster aside before a merge removes or overwrites them."""
    poster = lib.poster(label)
    saved = None
    if poster:
        merged_dir(kind).mkdir(parents=True, exist_ok=True)
        dest = merged_dir(kind) / (safe_filename(label) + poster.suffix)
        shutil.copy2(poster, dest)
        saved = str(dest)
    return {"meta": json.loads(json.dumps(lib.meta.get(label))), "fav": lib.is_fav(label), "poster": saved}


def dedupe(items, is_fav=lambda l: False, plays=lambda l: 0):
    """items: [(kind, label, path)] -> the same list with one edition per album (albums only; other kinds untouched)."""
    albums = [l for k, l, _ in items if k == "albums"]
    drop = set()
    for g in groups(albums):
        keep = keeper(g, is_fav, plays)
        drop.update(l for l in g if l != keep)
    return [it for it in items if not (it[0] == "albums" and it[1] in drop)]

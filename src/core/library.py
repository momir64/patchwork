"""A Library = one media kind (shows / movies / albums): titles, favorites, hidden / removed titles (library.json), posters."""
import re
import time
import shutil
from pathlib import Path

from .config import ALIASES_PATH, ensure_dirs, kind_dir
from .jsonstore import read_json, write_json
from .meta import Meta
from .names import norm_key, safe_filename, sort_key

KINDS = {"shows": "Shows", "movies": "Movies", "albums": "Albums"}
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")


def load_aliases() -> dict:
    """data/aliases.json: {'name from Sonarr/file': 'name in my list'} -> {normalized source: target}."""
    return {norm_key(a): b for a, b in read_json(ALIASES_PATH, {}).items()}


def add_alias(source: str, target: str):
    """Remember 'source => target' so later syncs map the original name onto the renamed item."""
    if norm_key(source) == norm_key(target):
        return
    pairs = {a: b for a, b in read_json(ALIASES_PATH, {}).items() if norm_key(a) != norm_key(source)}
    pairs = {a: (target if norm_key(b) == norm_key(source) else b) for a, b in pairs.items()}      # keep chains pointing at what exists
    pairs[source] = target
    write_json(ALIASES_PATH, pairs)


def remove_alias(source: str):
    """Forget the alias for `source` (that name is its own title again)."""
    pairs = read_json(ALIASES_PATH, {})
    kept = {a: b for a, b in pairs.items() if norm_key(a) != norm_key(source)}
    if len(kept) != len(pairs):
        write_json(ALIASES_PATH, kept)


def title_from_label(kind: str, label: str) -> str:
    """What a card shows as the title for a label: albums drop the artist, movies drop the year tag."""
    if kind == "albums":
        return label.split(" - ", 1)[-1]
    if kind == "movies":
        return re.sub(r"\s*\(\d{4}\)\s*$", "", label)
    return label


def migrate_names(libs: dict):
    """Older data kept a hand-chosen title as `title` + `title_locked`. It now lives in its own field, `name`."""
    for lib in libs.values():
        changed = False
        for l in lib.items:
            m = lib.meta.get(l)
            if m.get("title_locked"):
                if m.get("title"):
                    m["name"] = m["title"]
                m.pop("title_locked", None)
                changed = True
        if changed:
            lib.meta.dirty = True
            lib.meta.save()


class Library:
    def __init__(self, kind: str):
        ensure_dirs()
        self.kind = kind
        self.title = KINDS[kind]
        self.json_path = kind_dir(kind) / "library.json"
        self.poster_dir = kind_dir(kind) / "posters"
        self.load()

    # ---- persistence
    def load(self):
        data = read_json(self.json_path, {})
        self.items = sorted(data.get("items", []), key=sort_key)
        self._keys = {norm_key(i): i for i in self.items}
        self.favs = {norm_key(f) for f in data.get("favorites", [])}
        self.hidden = {norm_key(f) for f in data.get("hidden", [])}
        self.removed_labels = {norm_key(f): f for f in data.get("removed", [])}
        self.removed = set(self.removed_labels)
        self.meta = Meta(self.kind)
        self.index_posters()

    def save(self):
        self.items = sorted(self.items, key=sort_key)
        write_json(self.json_path, {
            "items": self.items,
            "favorites": [i for i in self.items if norm_key(i) in self.favs],
            "hidden": [i for i in self.items if norm_key(i) in self.hidden],
            "removed": sorted(self.removed_labels[k] for k in self.removed if k in self.removed_labels),
        })
        self.meta.save()

    def index_posters(self):
        self._posters = {}
        if self.poster_dir.is_dir():
            for p in self.poster_dir.iterdir():
                if p.suffix.lower() in IMG_EXT:
                    self._posters[norm_key(p.stem)] = p

    # ---- queries
    def has(self, label: str) -> bool:
        return norm_key(label) in self._keys

    def canonical(self, label: str):
        return self._keys.get(norm_key(label))

    def poster(self, label: str):
        return self._posters.get(norm_key(label)) or self._posters.get(norm_key(safe_filename(label)))     # (very long names are stored shortened)

    def is_fav(self, label: str) -> bool:
        return norm_key(label) in self.favs

    def favorites(self):
        return [i for i in self.items if self.is_fav(i)]

    def is_hidden(self, label: str) -> bool:
        return norm_key(label) in self.hidden

    def hidden_items(self):
        return [i for i in self.items if self.is_hidden(i)]

    def shown_items(self):
        return [i for i in self.items if not self.is_hidden(i)]

    # ---- changes (call save() afterwards)
    def add(self, label: str) -> bool:
        label = label.strip()
        if not label or self.has(label):
            return False
        self.items.append(label)
        self._keys[norm_key(label)] = label
        self.meta.stamp_added(label)
        return True

    def remove(self, label: str):
        k = norm_key(label)
        self.items = [i for i in self.items if norm_key(i) != k]
        self._keys.pop(k, None)
        self.favs.discard(k)
        self.hidden.discard(k)
        self.meta.remove(label)

    def set_fav(self, label: str, value: bool):
        (self.favs.add if value else self.favs.discard)(norm_key(label))

    def forget(self, label: str):
        """The user removed this title: it is deleted completely (list entry, details, poster file). Nothing is remembered,
        so a later sync may add it again - hide a title instead to keep it out of sight."""
        p = self.poster(label)
        self.remove(label)
        self._posters.pop(norm_key(label), None)
        if p:
            try:
                p.unlink()
            except OSError:
                pass

    def unforget(self, label: str):
        self.removed.discard(norm_key(label))
        self.removed_labels.pop(norm_key(label), None)

    def is_removed(self, label: str) -> bool:
        return norm_key(label) in self.removed

    def set_hidden(self, label: str, value: bool):
        newly = value and norm_key(label) not in self.hidden
        (self.hidden.add if value else self.hidden.discard)(norm_key(label))
        if newly and not self.meta.get(label).get("hidden_at"):      # when it was hidden (for the Hidden tab's sort)
            self.meta.update(label, {"hidden_at": time.time()})
        elif not value:
            self.meta.drop(label, "hidden_at")

    def name(self, label: str) -> str:
        """What the app shows for an item: the name you chose, else what the source calls it, else the plain label.
        (The label itself never changes: it is the item's permanent handle for posters, groups and syncs.)"""
        m = self.meta.get(label)
        return m.get("name") or m.get("title") or title_from_label(self.kind, label)

    def rename(self, old: str, new: str):
        """Change the handle itself (only for upgrading old data, e.g. album names that had no artist yet)."""
        new = new.strip()
        ok, nk = norm_key(old), norm_key(new)
        if not new or (nk != ok and nk in self._keys):
            return False
        was_fav, was_hidden = ok in self.favs, ok in self.hidden
        p = self.poster(old)
        self.meta.rename(old, new)
        self.remove(old)
        self.add(new)
        self.set_fav(new, was_fav)
        self.set_hidden(new, was_hidden)
        if p:
            dest = p.with_name(safe_filename(new) + p.suffix)
            if dest != p:
                p.replace(dest)
            self._posters.pop(ok, None)
            self._posters[nk] = dest
        return True

    def set_poster(self, label: str, source: Path | bytes, ext: str = ".jpg"):
        """Store a poster from a file path or raw bytes (replacing any old one)."""
        old = self.poster(label)
        self.poster_dir.mkdir(parents=True, exist_ok=True)
        dest = self.poster_dir / (safe_filename(label) + (source.suffix.lower() if isinstance(source, Path) else ext))
        if isinstance(source, Path):
            shutil.copy2(source, dest)
        else:
            dest.write_bytes(source)
        if old and old != dest and old.exists():
            old.unlink()
        self._posters[norm_key(label)] = dest
        return dest

    _ok_cache: dict = {}

    def has_poster(self, label: str) -> bool:
        """A poster file that really is a readable image (an empty or broken file counts as missing)."""
        p = self.poster(label)
        if not p:
            return False
        try:
            st = p.stat()
        except OSError:
            return False
        key = (str(p), st.st_mtime_ns, st.st_size)
        ok = Library._ok_cache.get(key)
        if ok is None:
            try:
                from PIL import Image
                with Image.open(p) as im:
                    im.verify()
                ok = st.st_size > 0
            except Exception:
                ok = False
            Library._ok_cache[key] = ok
        return ok

    def missing_posters(self):
        return [i for i in self.items if not self.has_poster(i)]

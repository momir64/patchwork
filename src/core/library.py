"""A Library = one media kind (shows / movies / albums): sorted txt list, favorites txt list, posters."""
import re
import shutil
from pathlib import Path

from .config import ALIASES_PATH, ensure_dirs, kind_dir
from .meta import Meta
from .names import norm_key, safe_filename, sort_key

KINDS = {"shows": "Shows", "movies": "Movies", "albums": "Albums"}
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")


def read_lines(path: Path):
    if not path.is_file():
        return []
    return [l.strip() for l in path.read_text(encoding="utf-8-sig").splitlines() if l.strip()]


def write_sorted(path: Path, labels):
    path.parent.mkdir(parents=True, exist_ok=True)
    uniq = {}
    for l in labels:
        uniq.setdefault(norm_key(l), l)
    path.write_text("\n".join(sorted(uniq.values(), key=sort_key)) + "\n", encoding="utf-8")


def load_aliases() -> dict:
    """data/aliases.txt: 'name from Sonarr/file => name in my list' (one per line)."""
    out = {}
    for line in read_lines(ALIASES_PATH):
        if "=>" in line and not line.startswith("#"):
            a, b = line.split("=>", 1)
            out[norm_key(a)] = b.strip()
    return out


def add_alias(source: str, target: str):
    """Remember 'source => target' so later syncs map the original name onto the renamed item."""
    if norm_key(source) == norm_key(target):
        return
    ALIASES_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = read_lines(ALIASES_PATH)
    lines = [l for l in lines if not (("=>" in l) and norm_key(l.split("=>")[0]) == norm_key(source))]
    lines = [(f"{l.split('=>')[0].strip()} => {target}" if "=>" in l and not l.startswith("#") and norm_key(l.split("=>", 1)[1]) == norm_key(source) else l) for l in lines]
    lines.append(f"{source} => {target}")
    ALIASES_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def remove_alias(source: str):
    """Forget 'source => ...' (the merge was undone, so that name is its own title again)."""
    if not ALIASES_PATH.exists():
        return
    lines = [l for l in read_lines(ALIASES_PATH) if not ("=>" in l and norm_key(l.split("=>")[0]) == norm_key(source))]
    ALIASES_PATH.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def title_from_label(kind: str, label: str) -> str:
    """What a card shows as the title for a label: albums drop the artist, movies drop the year tag."""
    if kind == "albums":
        return label.split(" - ", 1)[-1]
    if kind == "movies":
        return re.sub(r"\s*\(\d{4}\)\s*$", "", label)
    return label


def fix_renamed_titles(libs: dict):
    """Titles you renamed or merged (they are alias targets) keep the name you chose, even after a sync."""
    targets = {norm_key(t) for t in load_aliases().values()}
    for lib in libs.values():
        changed = False
        for l in lib.items:
            if norm_key(l) in targets and not lib.meta.get(l).get("title_locked"):
                lib.meta.set_title(l, title_from_label(lib.kind, l))
                changed = True
        if changed:
            lib.meta.save()


class Library:
    def __init__(self, kind: str):
        ensure_dirs()
        self.kind = kind
        self.title = KINDS[kind]
        self.list_path = kind_dir(kind) / "list.txt"
        self.fav_path = kind_dir(kind) / "favorites.txt"
        self.hidden_path = kind_dir(kind) / "hidden.txt"
        self.removed_path = kind_dir(kind) / "removed.txt"
        self.poster_dir = kind_dir(kind) / "posters"
        self.load()

    # ---- persistence
    def load(self):
        self.items = sorted(read_lines(self.list_path), key=sort_key)
        self._keys = {norm_key(i): i for i in self.items}
        self.favs = {norm_key(f) for f in read_lines(self.fav_path)}
        self.hidden = {norm_key(f) for f in read_lines(self.hidden_path)} if self.hidden_path.exists() else set()
        self.removed_labels = {norm_key(f): f for f in read_lines(self.removed_path)} if self.removed_path.exists() else {}
        self.removed = set(self.removed_labels)
        self.meta = Meta(self.kind)
        self.index_posters()

    def save(self):
        self.items = sorted(self.items, key=sort_key)
        write_sorted(self.list_path, self.items)
        fav_labels = [i for i in self.items if norm_key(i) in self.favs]
        write_sorted(self.fav_path, fav_labels)
        if self.removed or self.removed_path.exists():
            write_sorted(self.removed_path, [self.removed_labels[k] for k in self.removed if k in self.removed_labels])
        if self.hidden or self.hidden_path.exists():
            write_sorted(self.hidden_path, [i for i in self.items if norm_key(i) in self.hidden])
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
        return self._posters.get(norm_key(label))

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
        """The user removed this title: take it out AND remember that, so later syncs do not bring it back."""
        self.removed_labels[norm_key(label)] = label
        self.removed.add(norm_key(label))
        self.remove(label)

    def unforget(self, label: str):
        self.removed.discard(norm_key(label))
        self.removed_labels.pop(norm_key(label), None)

    def is_removed(self, label: str) -> bool:
        return norm_key(label) in self.removed

    def set_hidden(self, label: str, value: bool):
        (self.hidden.add if value else self.hidden.discard)(norm_key(label))

    def rename(self, old: str, new: str, alias: bool = False):
        """alias=True: also remember the old name, so syncs don't re-add it as a duplicate."""
        new = new.strip()
        ok, nk = norm_key(old), norm_key(new)
        if not new or (nk != ok and nk in self._keys):
            return False
        if alias:
            add_alias(old, new)
        was_fav, was_hidden = ok in self.favs, ok in self.hidden
        p = self.poster(old)
        self.meta.rename(old, new)
        self.remove(old)
        self.add(new)
        self.set_fav(new, was_fav)
        self.set_hidden(new, was_hidden)
        if alias:                                             # a rename by hand: the shown title follows it
            self.meta.set_title(new, title_from_label(self.kind, new))
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

    def missing_posters(self):
        return [i for i in self.items if not self.poster(i)]

"""Application state shared by all pages (libraries, groups, collage picks, thumbnails, UI preferences)."""
import json

from PySide6.QtCore import QObject, Signal

from ..core.config import DATA_DIR, Config
from ..core.groups import Groups
from ..core import editions
from ..core.library import KINDS, Library, migrate_names
from .common import ThumbLoader

PREFS_PATH = DATA_DIR / "ui.json"


class AppState(QObject):
    changed = Signal()              # lists / favorites / posters changed
    groups_changed = Signal()

    def __init__(self):
        super().__init__()
        self.cfg = Config()
        self.libs = {k: Library(k) for k in KINDS}
        migrate_names(self.libs)
        for lib in self.libs.values():
            editions.sweep(lib)
        self.groups = Groups()
        self.thumbs = ThumbLoader()
        self.picks = []             # [(kind, label)] handed to the collage page from a library / group view
        self.picks_desc = ""
        try:
            self.prefs = json.loads(PREFS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.prefs = {}

    # ---- preferences (data/ui.json)
    def pref(self, key, default=None):
        return self.prefs.get(key, default)

    def set_pref(self, key, value):
        if self.prefs.get(key) != value:
            self.prefs[key] = value
            PREFS_PATH.write_text(json.dumps(self.prefs, indent=1), encoding="utf-8")

    # ---- group colors (data/ui.json: {"kind|name": "#rrggbb"}); unset groups get a stable default
    def group_color(self, kind, name):
        from .sidebar import folder_color
        return self.pref("group_colors", {}).get(f"{kind}|{name}") or folder_color(name)

    def set_group_color(self, kind, name, color):
        colors = dict(self.pref("group_colors", {}))
        if color:
            colors[f"{kind}|{name}"] = color
        else:
            colors.pop(f"{kind}|{name}", None)
        self.set_pref("group_colors", colors)

    def move_group_color(self, kind, old, new):
        color = self.pref("group_colors", {}).get(f"{kind}|{old}")
        self.set_group_color(kind, old, None)
        if color:
            self.set_group_color(kind, new, color)

    def reload(self):
        for lib in self.libs.values():
            lib.load()
        migrate_names(self.libs)
        for lib in self.libs.values():
            editions.sweep(lib)
        self.groups.refresh()
        self.thumbs.cache.clear()
        self.changed.emit()
        self.groups_changed.emit()

    def poster(self, kind, label):
        return self.libs[kind].poster(label)

    def pool(self, kinds, scope, group=None):
        """Items for a collage: [(kind, label, poster_path)].
        scope: all | favs | group | picks. A group is (kind, name) - it belongs to exactly one category."""
        if scope == "picks":
            return [(k, l, self.poster(k, l)) for k, l in self.picks if self.poster(k, l) and not self.libs[k].is_hidden(l)]
        members = None
        if scope == "group":
            if not group:
                return []
            kinds, members = [group[0]], set(self.groups.members(*group))
        out = []
        for kind in kinds:
            lib = self.libs[kind]
            labels = lib.favorites() if scope == "favs" else [l for l in lib.items if members is None or l in members]
            labels = [l for l in labels if not lib.is_hidden(l)]          # hidden titles never go into a collage
            out += [(kind, l, lib.poster(l)) for l in labels if lib.poster(l)]
        return out

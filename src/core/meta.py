"""Per-item metadata (genres, countries, languages, creators, ids...).

Stored as data/<kind>/meta.json, keyed by the item's title so it is easy to read and edit by hand.
"""
import json
import time
from collections import Counter

from . import genres
from .config import kind_dir
from .names import norm_key

LIST_FIELDS = ("genres", "countries", "languages", "creators")
FACETS = {"genre": "genres", "country": "countries", "language": "languages", "creator": "creators",
          "studio": "studio", "year": "year"}


# Serbian, Croatian, Bosnian (and Montenegrin) are treated as one language
LANGUAGE_ALIASES = {"serbian": "Serbo-Croatian", "croatian": "Serbo-Croatian", "bosnian": "Serbo-Croatian",
                    "montenegrin": "Serbo-Croatian", "serbo-croatian": "Serbo-Croatian"}


def norm_language(name):
    return LANGUAGE_ALIASES.get(str(name).strip().casefold(), str(name).strip())


# the same country under another name (TMDB says 'United States of America', MusicBrainz 'United States')
COUNTRY_ALIASES = {"united states of america": "United States", "usa": "United States", "us": "United States",
                   "u.s.": "United States", "u.s.a.": "United States", "great britain": "United Kingdom", "uk": "United Kingdom"}


def norm_country(name):
    n = str(name).strip()
    if len(n) <= 3 and n.isalpha() and n.upper() == n:                 # a leftover country code: 'BA' -> 'Bosnia and Herzegovina'
        from ..sources.lookups import COUNTRIES
        n = COUNTRIES.get(n, n)
    return COUNTRY_ALIASES.get(n.casefold(), n)


def as_list(v):
    if v in (None, "", []):
        return []
    return [str(x) for x in (v if isinstance(v, list) else [v])]


class Meta:
    def __init__(self, kind):
        self.kind = kind
        self.json_path = kind_dir(kind) / "meta.json"
        self.by_label = {}      # label -> dict   (what is on disk)
        self._index = {}        # norm_key -> label
        self.dirty = False
        if self.json_path.is_file():
            try:
                self.by_label = json.loads(self.json_path.read_text(encoding="utf-8"))
            except ValueError:
                self.by_label = {}
        self._index = {norm_key(l): l for l in self.by_label}
        for m in self.by_label.values():           # merge language / country variants in existing data
            langs = sorted({norm_language(x) for x in m.get("languages", [])})
            if langs != m.get("languages", []) and m.get("languages"):
                m["languages"], self.dirty = langs, True
            places = sorted({norm_country(x) for x in m.get("countries", [])})
            if places != m.get("countries", []) and m.get("countries"):
                m["countries"], self.dirty = places, True

    # ---- persistence
    def save(self):
        if not self.dirty:
            return
        self.json_path.parent.mkdir(parents=True, exist_ok=True)
        ordered = dict(sorted(self.by_label.items(), key=lambda kv: kv[0].casefold()))
        self.json_path.write_text(json.dumps(ordered, ensure_ascii=False, indent=1), encoding="utf-8")
        self.dirty = False

    # ---- access
    def get(self, label) -> dict:
        return self.by_label.get(self._index.get(norm_key(label), ""), {})

    def update(self, label, new: dict, replace=()):
        """Merge: lists are unioned (or replaced for keys in `replace`), ids merged, other fields take the newest non-empty value."""
        key = self._index.get(norm_key(label))
        if key is None:
            key = label
            self._index[norm_key(label)] = label
            self.by_label[label] = {}
        cur = self.by_label[key]
        before = json.dumps(cur, sort_keys=True)
        for k, v in (new or {}).items():
            if v in (None, "", [], {}):
                continue
            if k == "name" and cur.get("name"):
                continue                         # the name you chose is never replaced by an import
            if k == "title" and cur.get("title_locked"):
                continue                         # (older data) a locked title
            if k == "languages":
                v = [norm_language(x) for x in as_list(v)]
            elif k == "countries":
                v = [norm_country(x) for x in as_list(v)]
            if k in LIST_FIELDS:
                vals = set(as_list(v))
                cur[k] = sorted(vals if k in replace else set(cur.get(k, [])) | vals)
            elif k == "ids":
                cur["ids"] = {**cur.get("ids", {}), **{a: b for a, b in v.items() if b}}
            elif k == "overview" and cur.get("overview"):
                continue
            else:
                cur[k] = v
        if json.dumps(cur, sort_keys=True) != before:
            self.dirty = True

    def stamp_added(self, label, ts=None):
        """Remember when an item joined the library (only the first time)."""
        key = self._index.get(norm_key(label))
        if key is None:
            key = label
            self._index[norm_key(label)] = label
            self.by_label[label] = {}
        if not self.by_label[key].get("added"):
            self.by_label[key]["added"] = ts or time.time()
            self.dirty = True

    def rename(self, old, new):
        key = self._index.pop(norm_key(old), None)
        if key is not None:
            self.by_label[new] = self.by_label.pop(key)
            self._index[norm_key(new)] = new
            self.dirty = True

    def set_name(self, label, name):
        """The name you chose for an item. Syncs only ever touch `title` (what the source calls it), never this."""
        key = self._index.get(norm_key(label))
        if key is None:
            key = label
            self._index[norm_key(label)] = label
            self.by_label[label] = {}
        if name:
            self.by_label[key]["name"] = name
        else:
            self.by_label[key].pop("name", None)
        self.dirty = True

    def remove(self, label):
        key = self._index.pop(norm_key(label), None)
        if key is not None:
            del self.by_label[key]
            self.dirty = True

    # ---- queries
    def has_details(self, label) -> bool:
        m = self.get(label)
        return bool(m.get("genres") and (m.get("countries") or m.get("creators")))

    def values(self, label, facet):
        v = as_list(self.get(label).get(FACETS[facet]))
        if facet == "genre" and self.kind == "albums":
            return genres.broad(v)                        # hundreds of raw tags -> a short list of real genres
        return v

    def facet_counts(self, labels, facet) -> Counter:
        c = Counter()
        for l in labels:
            c.update(set(self.values(l, facet)))
        return c

    def matches(self, label, text, by_label=True) -> bool:
        """Text in the title (when by_label), or in year / studio / genres / countries / languages / creators."""
        text = text.casefold()
        if by_label and text in label.casefold():
            return True
        m = self.get(label)
        hay = [str(m.get("year", "")), str(m.get("studio", ""))] + [x for f in LIST_FIELDS for x in as_list(m.get(f))]
        return any(text in h.casefold() for h in hay)

"""Custom groups ("Sci-fi", "Metal", "Horror night").

A group belongs to exactly one category (shows, movies or albums). All groups of a category live in
data/<kind>/groups.json as {name: [titles]}.
"""
from .config import kind_dir
from .jsonstore import read_json, write_json
from .names import sort_key


class Groups:
    """The group files are read once and cached (the pages ask for names / members many times per change);
    every change made here refreshes the cache, refresh() re-reads after outside changes."""

    def __init__(self):
        self._data = {}

    def refresh(self):
        self._data.clear()

    def _file(self, kind):
        return kind_dir(kind) / "groups.json"

    def _load(self, kind) -> dict:
        if kind not in self._data:
            self._data[kind] = read_json(self._file(kind), {})
        return self._data[kind]

    def _save(self, kind):
        write_json(self._file(kind), dict(sorted(self._load(kind).items(), key=lambda kv: kv[0].casefold())))

    def names(self, kind):
        return sorted(self._load(kind), key=str.casefold)

    def exists(self, kind, name):
        return name in self._load(kind)

    def members(self, kind, name):
        return list(self._load(kind).get(name, []))

    def add(self, kind, name, labels):
        """Creates the group if needed. Returns how many titles were actually added."""
        d = self._load(kind)
        cur = set(d.get(name, []))
        new = cur | set(labels)
        d[name] = sorted(new, key=sort_key)
        self._save(kind)
        return len(new) - len(cur)

    def remove_items(self, kind, name, labels):
        d = self._load(kind)
        d[name] = sorted(set(d.get(name, [])) - set(labels), key=sort_key)
        self._save(kind)

    def delete(self, kind, name):
        self._load(kind).pop(name, None)
        self._save(kind)

    def rename(self, kind, old, new):
        d = self._load(kind)
        if new in d or old not in d:
            return False
        d[new] = d.pop(old)
        self._save(kind)
        return True

    def groups_of(self, kind, label):
        return [n for n, members in self._load(kind).items() if label in set(members)]

    def replace_member(self, kind, old, new):
        """An item was renamed: keep it in all its groups."""
        for n in self.groups_of(kind, old):
            self.remove_items(kind, n, [old])
            self.add(kind, n, [new])

    def remove_member(self, kind, label):
        """An item was deleted: drop it from every group of its category."""
        for n in self.groups_of(kind, label):
            self.remove_items(kind, n, [label])

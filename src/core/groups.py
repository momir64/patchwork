"""Custom groups ("Sci-fi", "Metal", "Horror night").

A group belongs to exactly one category (shows, movies or albums) and is stored as a plain txt file in that
category's folder:  data/<kind>/groups/<name>.txt  - one title per line, sorted.
"""
from .config import kind_dir
from .library import read_lines, write_sorted
from .names import safe_filename


class Groups:
    """Group files are read once and cached (the pages ask for names / members many times per change);
    every change made here refreshes the cache, refresh() re-reads after outside changes."""

    def __init__(self):
        self._names, self._members, self._made = {}, {}, set()

    def refresh(self):
        self._names.clear()
        self._members.clear()

    def folder(self, kind):
        d = kind_dir(kind) / "groups"
        if kind not in self._made:
            d.mkdir(parents=True, exist_ok=True)
            self._made.add(kind)
        return d

    def path(self, kind, name):
        return self.folder(kind) / f"{safe_filename(name)}.txt"

    def names(self, kind):
        if kind not in self._names:
            self._names[kind] = sorted((p.stem for p in self.folder(kind).glob("*.txt")), key=str.casefold)
        return list(self._names[kind])

    def members(self, kind, name):
        key = (kind, name)
        if key not in self._members:
            self._members[key] = read_lines(self.path(kind, name))
        return list(self._members[key])

    def add(self, kind, name, labels):
        """Creates the group if needed. Returns how many titles were actually added."""
        cur = set(self.members(kind, name))
        new = cur | set(labels)
        write_sorted(self.path(kind, name), new)
        self.refresh()
        return len(new) - len(cur)

    def remove_items(self, kind, name, labels):
        write_sorted(self.path(kind, name), set(self.members(kind, name)) - set(labels))
        self.refresh()

    def delete(self, kind, name):
        self.path(kind, name).unlink(missing_ok=True)
        self.refresh()

    def rename(self, kind, old, new):
        if self.path(kind, new).exists():
            return False
        self.path(kind, old).rename(self.path(kind, new))
        self.refresh()
        return True

    def groups_of(self, kind, label):
        return [n for n in self.names(kind) if label in set(self.members(kind, n))]

    def replace_member(self, kind, old, new):
        """An item was renamed: keep it in all its groups."""
        for n in self.groups_of(kind, old):
            self.remove_items(kind, n, [old])
            self.add(kind, n, [new])

    def remove_member(self, kind, label):
        """An item was deleted: drop it from every group of its category."""
        for n in self.groups_of(kind, label):
            self.remove_items(kind, n, [label])

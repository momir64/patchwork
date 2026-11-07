"""Small JSON helpers + the one-time move of the old txt data files to JSON.

Layout after the move (all under ./data):
    <kind>/library.json     {"items": [...], "favorites": [...], "hidden": [...], "removed": [...]}
    <kind>/groups.json      {"group name": [titles...]}
    <kind>/duplicates.json  {"separate": [set ids...], "hidden": [titles hidden by the duplicates dialog]}
    aliases.json            {"name from a source": "name in my list"}
The old txt files are moved to data/_txt_backup/ and never read again.
"""
import json
import os
import shutil
from pathlib import Path


def read_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, obj):
    """Atomic: a crash while saving can never leave a half-written file behind."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _lines(path: Path):
    if not path.is_file():
        return []
    return [l.strip() for l in path.read_text(encoding="utf-8-sig").splitlines() if l.strip()]


def migrate_txt(data_dir: Path, kinds):
    """Turn the old txt files into JSON (once). Safe to call on every start: it does nothing when there is nothing to move."""
    backup = data_dir / "_txt_backup"

    def keep(p: Path):
        dest = backup / p.relative_to(data_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(dest))

    for kind in kinds:
        d = data_dir / kind
        lib_json = d / "library.json"
        if not lib_json.exists() and (d / "list.txt").exists():
            write_json(lib_json, {"items": _lines(d / "list.txt"), "favorites": _lines(d / "favorites.txt"),
                                  "hidden": _lines(d / "hidden.txt"), "removed": _lines(d / "removed.txt")})
            for n in ("list.txt", "favorites.txt", "hidden.txt", "removed.txt"):
                if (d / n).exists():
                    keep(d / n)
        dup_json = d / "duplicates.json"
        if not dup_json.exists() and ((d / "not_duplicates.txt").exists() or (d / "duplicate_hidden.txt").exists()):
            write_json(dup_json, {"separate": _lines(d / "not_duplicates.txt"), "hidden": _lines(d / "duplicate_hidden.txt")})
            for n in ("not_duplicates.txt", "duplicate_hidden.txt"):
                if (d / n).exists():
                    keep(d / n)
        gdir = d / "groups"
        if not (d / "groups.json").exists() and gdir.is_dir() and any(gdir.glob("*.txt")):
            write_json(d / "groups.json", {p.stem: _lines(p) for p in sorted(gdir.glob("*.txt"), key=lambda p: p.stem.casefold())})
            for p in list(gdir.glob("*.txt")):
                keep(p)
    old = data_dir / "aliases.txt"
    if old.exists() and not (data_dir / "aliases.json").exists():
        pairs = {}
        for line in _lines(old):
            if "=>" in line and not line.startswith("#"):
                a, b = line.split("=>", 1)
                pairs[a.strip()] = b.strip()
        write_json(data_dir / "aliases.json", pairs)
        keep(old)

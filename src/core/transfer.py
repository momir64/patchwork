"""Export / import everything media related as one file.

  *.json  data only (lists, favorites, metadata, groups, aliases) - readable, small
  *.zip   the same patchwork.json plus every poster image (posters/<kind>/<file>)

Importing merges: nothing already in your library is deleted or overwritten (posters only fill gaps unless
`overwrite_posters` is set). Secrets from .env are never exported.
"""
import json
import zipfile
from datetime import datetime
from pathlib import Path

from .config import KIND_NAMES
from .groups import Groups
from .jsonstore import read_json
from .config import ALIASES_PATH
from .library import Library, add_alias, load_aliases
from .names import norm_key

FORMAT, VERSION, DATA_NAME = "patchwork-export", 1, "patchwork.json"


def collect(log=print):
    groups, kinds = Groups(), {}
    for kind in KIND_NAMES:
        lib = Library(kind)
        kinds[kind] = {
            "items": list(lib.items),
            "favorites": lib.favorites(),
            "hidden": lib.hidden_items(),
            "removed": sorted(lib.removed_labels.values()),
            "groups": {n: groups.members(kind, n) for n in groups.names(kind)},
            "metadata": lib.meta.by_label,
            "posters": {l: lib.poster(l).name for l in lib.items if lib.poster(l)},
        }
    aliases = [f"{a} => {b}" for a, b in read_json(ALIASES_PATH, {}).items()]       # exported as "a => b" lines, like before
    return {"format": FORMAT, "version": VERSION, "exported": datetime.now().isoformat(timespec="seconds"),
            "kinds": kinds, "aliases": aliases}


def export_data(path, log=print, progress=None) -> Path:
    path = Path(path)
    data = collect(log)
    text = json.dumps(data, ensure_ascii=False, indent=1)
    if path.suffix.lower() == ".json":
        path.write_text(text, encoding="utf-8")
        log(f"Exported data to {path.name}")
        return path
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(DATA_NAME, text, compress_type=zipfile.ZIP_DEFLATED)
        n, total = 0, sum(len(b["posters"]) for b in data["kinds"].values())
        for kind, block in data["kinds"].items():
            lib = Library(kind)
            for label in block["posters"]:
                z.write(lib.poster(label), f"posters/{kind}/{lib.poster(label).name}", compress_type=zipfile.ZIP_STORED)
                n += 1
                if progress:
                    progress(n, total)
    log(f"Exported data and {n} posters to {path.name}")
    return path


def _read(path):
    path = Path(path)
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8")), None
    z = zipfile.ZipFile(path)
    return json.loads(z.read(DATA_NAME).decode("utf-8")), z


def import_data(path, overwrite_posters=False, log=print, progress=None) -> dict:
    """Merge an export into the current data. Returns counts per kind."""
    data, z = _read(path)
    if data.get("format") != FORMAT:
        raise ValueError("This is not a Patchwork export file.")
    groups, counts, done = Groups(), {}, 0
    total = sum(len(b.get("posters", {})) for k, b in data["kinds"].items() if k in KIND_NAMES) if z else 0
    for kind, block in data["kinds"].items():
        if kind not in KIND_NAMES:
            continue
        lib = Library(kind)
        added = sum(1 for l in block.get("items", []) if lib.add(l))
        for l in block.get("favorites", []):
            if lib.has(l):
                lib.set_fav(l, True)
        for l in block.get("removed", []):
            lib.forget(l) if not lib.has(l) else None
        for l in block.get("hidden", []):
            if lib.has(l):
                lib.set_hidden(l, True)
        for label, meta in block.get("metadata", {}).items():
            if lib.has(label):
                lib.meta.update(label, meta)
        posters = 0
        for label, fname in block.get("posters", {}).items():
            done += 1
            if progress and total:
                progress(done, total)
            member = f"posters/{kind}/{fname}"
            if z and lib.has(label) and member in z.namelist() and (overwrite_posters or not lib.poster(label)):
                lib.set_poster(label, z.read(member), Path(fname).suffix or ".jpg")
                posters += 1
        for name, members in block.get("groups", {}).items():
            groups.add(kind, name, [m for m in members if lib.has(m)])
        lib.save()
        counts[kind] = {"added": added, "posters": posters, "groups": len(block.get("groups", {}))}
        log(f"{kind}: {added} new titles, {posters} posters, {counts[kind]['groups']} groups merged")
    known = load_aliases()
    for line in data.get("aliases", []):
        a, b = (x.strip() for x in line.split("=>", 1))
        if norm_key(a) not in known:
            add_alias(a, b)
    if z:
        z.close()
    return counts

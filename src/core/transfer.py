"""Export / import everything media related as one file.

  *.json  data only (lists, favorites, metadata, groups, aliases) - readable, small
  *.zip   the same patchwork.json plus every poster image (posters/<kind>/<file>)

Importing merges: nothing already in your library is deleted or overwritten (posters only fill gaps unless
`overwrite_posters` is set). The settings (.env, API keys included) and the Spotify sign-in are only exported / imported when asked for (`settings=True`).
"""
import json
import zipfile
from datetime import datetime
from pathlib import Path

from .config import KEYS, KIND_NAMES, SPOTIFY_AUTH_PATH, Config
from . import covers, editions, singles
from .groups import Groups
from .jsonstore import read_json, write_json
from .config import ALIASES_PATH
from .library import Library, add_alias, load_aliases
from .names import norm_key

FORMAT, VERSION, DATA_NAME = "patchwork-export", 1, "patchwork.json"


def collect(log=print, settings=False):
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
            "duplicates": editions.export_state(kind),               # which hidden titles are duplicates, "not duplicates" sets...
            "cover_hashes": covers.hashes_of(lib),                   # so the same-cover duplicates are found again at once
            "releases": singles.load_cache(kind) if kind == "albums" else {},      # what was looked up about singles (Spotify / Deezer)
        }
    aliases = [f"{a} => {b}" for a, b in read_json(ALIASES_PATH, {}).items()]       # exported as "a => b" lines, like before
    data = {"format": FORMAT, "version": VERSION, "exported": datetime.now().isoformat(timespec="seconds"),
            "kinds": kinds, "aliases": aliases}
    if settings:                                                    # the saved settings (.env), API keys included
        data["settings"] = {k: v for k, v in Config().values.items() if k in KEYS}
        login = read_json(SPOTIFY_AUTH_PATH, {})                    # the Spotify sign-in goes with the settings
        if login.get("refresh_token"):
            data["spotify_login"] = login
    return data


def export_data(path, log=print, progress=None, settings=False) -> Path:
    path = Path(path)
    data = collect(log, settings)
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


def has_settings(path) -> bool:
    """Does this export file contain settings (.env)?"""
    data, z = _read(path)
    if z:
        z.close()
    return bool(data.get("settings"))


def import_data(path, overwrite_posters=False, log=print, progress=None, settings=False) -> dict:
    """Merge an export into the current data. Returns counts per kind (and "settings": how many settings were applied)."""
    data, z = _read(path)
    if data.get("format") != FORMAT:
        raise ValueError("This is not a Patchwork export file.")
    groups, counts, done = Groups(), {}, 0
    blocks = {k: b for k, b in data["kinds"].items() if k in KIND_NAMES}
    # the progress counts every step: each title, its details, its poster, and saving a kind (so the bar moves all the time)
    total = sum(len(b.get("items", [])) + len(b.get("metadata", {})) + (len(b.get("posters", {})) if z else 0) + 1 for b in blocks.values())

    def step(n=1):
        nonlocal done
        done += n
        if progress:
            progress(done, total)

    names = set(z.namelist()) if z else set()
    for kind, block in blocks.items():
        lib = Library(kind)
        added, details = 0, block.get("metadata", {})
        for l in block.get("items", []):
            if lib.add(l):
                added += 1
                if "added" not in details.get(l, {}):
                    lib.meta.drop(l, "added")               # it had no date in the export: not "added today"
            step()
        for l in block.get("favorites", []):
            if lib.has(l):
                lib.set_fav(l, True)
        for l in block.get("removed", []):
            lib.forget(l) if not lib.has(l) else None
        for l in block.get("hidden", []):
            if lib.has(l):
                newly = not lib.is_hidden(l)
                lib.set_hidden(l, True)
                if newly and "hidden_at" not in details.get(l, {}):
                    lib.meta.drop(l, "hidden_at")
        for label, meta in block.get("metadata", {}).items():
            if lib.has(label):
                lib.meta.update(label, meta)
            step()
        posters, fresh = 0, []
        for label, fname in (block.get("posters", {}).items() if z else ()):
            member = f"posters/{kind}/{fname}"
            if lib.has(label) and member in names and (overwrite_posters or not lib.poster(label)):
                lib.set_poster(label, z.read(member), Path(fname).suffix or ".jpg")
                posters += 1
                fresh.append(label)
            step()
        cover_known = block.get("cover_hashes", {})
        covers.store_hashes(lib, {l: cover_known[l] for l in fresh if l in cover_known})      # only for posters written just now
        for name, members in block.get("groups", {}).items():
            groups.add(kind, name, [m for m in members if lib.has(m)])
        editions.merge_state(kind, block.get("duplicates", {}), lib)
        if block.get("releases"):
            singles.merge_cache(block["releases"], kind)
        lib.save()
        step()
        counts[kind] = {"added": added, "posters": posters, "groups": len(block.get("groups", {}))}
        log(f"{kind}: {added} new titles, {posters} posters, {counts[kind]['groups']} groups merged")
    known = load_aliases()
    for line in data.get("aliases", []):
        a, b = (x.strip() for x in line.split("=>", 1))
        if norm_key(a) not in known:
            add_alias(a, b)
    if z:
        z.close()
    if settings and data.get("settings"):
        new = {k: v for k, v in data["settings"].items() if k in KEYS}
        Config().save(new)
        counts["settings"] = len(new)
        log(f"{len(new)} settings imported")
    login = data.get("spotify_login") if settings else None
    if login and login.get("refresh_token") and login.get("client_id"):
        write_json(SPOTIFY_AUTH_PATH, login)                        # signed in to Spotify on this computer as well
        counts["spotify_login"] = 1
        log("Spotify sign-in imported")
    return counts

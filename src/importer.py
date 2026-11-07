"""One-off import of the old 'series_collage' folder (lists + downloaded posters + favs folders)."""
import shutil
from pathlib import Path

from .core.library import IMG_EXT, Library, load_aliases
from .core.names import norm_key, safe_filename


def _files(folder: Path):
    return [p for p in sorted(folder.iterdir()) if p.suffix.lower() in IMG_EXT] if folder.is_dir() else []


def import_legacy(src: Path, log=print):
    src = Path(src)
    aliases = load_aliases()

    # ---- shows
    shows = Library("shows")
    names = [l.strip() for l in (src / "serije.txt").read_text(encoding="utf-8-sig").splitlines() if l.strip()] \
        if (src / "serije.txt").is_file() else []
    for n in names:
        shows.add(n)

    def resolve(stem):
        a = aliases.get(norm_key(stem))
        return shows.canonical(a) if a and shows.has(a) else (shows.canonical(stem) or a or stem)

    # for each title keep the newest source file (downloads_difference holds re-fetched copies, but an older one must not win)
    best = {}
    for folder in ("downloads", "downloads_difference"):
        for p in _files(src / folder):
            label = resolve(p.stem)
            if label not in best or p.stat().st_mtime >= best[label].stat().st_mtime:
                best[label] = p
    copied = 0
    for label, p in best.items():
        if not shows.has(label):
            shows.add(label)
            log(f"  extra title not in list, added: {label}")
        shows.set_poster(label, p)
        copied += 1
    nfav = 0
    for folder in ("favs", "favs_difference"):
        for p in _files(src / folder):
            label = resolve(p.stem)
            if not shows.has(label):
                shows.add(label)
            if not shows.is_fav(label):
                shows.set_fav(label, True)
                nfav += 1
    shows.save()
    log(f"Shows: {len(shows.items)} titles, {copied} posters copied, {nfav} favorites")
    missing = shows.missing_posters()
    if missing:
        log(f"  without poster (sync will try to fetch): {', '.join(missing)}")

    # ---- albums (old folder only has album names, artists get added by the next Last.fm sync)
    albums = Library("albums")
    n = 0
    for p in _files(src / "downloads_albums"):
        if albums.add(p.stem):
            albums.set_poster(p.stem, p)
            n += 1
    albums.save()
    log(f"Albums: {n} imported")
    return shows, albums

"""Sync orchestration: pull titles from every configured source into the libraries, then fill posters + metadata."""
import threading
from concurrent.futures import ThreadPoolExecutor

from ..core.library import Library, load_aliases
from ..core.names import norm_key
from . import arr, covers, lastfm, musicbrainz, spotify, tmdb
from .http import download_image
from .trakt import Trakt

SOURCES = ("sonarr", "radarr", "trakt_shows", "trakt_movies", "lastfm")
STEPS = ("titles", "posters", "metadata")
KINDS = ("shows", "movies", "albums")


class Cancelled(BaseException):
    """Raised inside the worker when the user cancels. A BaseException so no `except Exception` swallows it."""


class Sync:
    """Pulls titles from the chosen sources, then fills posters / metadata for the chosen media kinds."""

    def __init__(self, cfg, libs: dict, log=print, progress=None, stage=None, cancel=None):
        self.cfg, self.libs = cfg, libs
        self.cancel = cancel or threading.Event()
        raw_log, raw_progress = log, progress or (lambda done, total: None)
        self.stage_cb = stage or (lambda text: None)

        def _log(msg):
            self.check()
            raw_log(msg)

        def _progress(done, total):
            self.check()
            raw_progress(done, total)

        self.log, self.progress = _log, _progress
        self.aliases = load_aliases()
        self.summary = []
        self.seen = {k: [] for k in libs}   # entries found this run, per kind (carry poster urls / tmdb ids)
        self.kinds = KINDS
        self.force_meta = False

    def check(self):
        if self.cancel.is_set():
            raise Cancelled()

    def stage(self, text):
        """Tell the UI which step is running (the percentage then belongs to it)."""
        self.check()
        self.stage_cb(text)

    def label(self, title):
        return self.aliases.get(norm_key(title), title)

    # ------------------------------------------------------------ main entry
    def run(self, sources=SOURCES, steps=STEPS, kinds=KINDS, force_meta=False):
        cfg = self.cfg
        self.kinds, self.force_meta = tuple(kinds), force_meta
        plan = []
        if "titles" in steps:
            if "sonarr" in sources:
                plan.append(("Sonarr", "shows", cfg.sonarr_ready, lambda: arr.fetch_sonarr(cfg)))
            if "radarr" in sources:
                plan.append(("Radarr", "movies", cfg.radarr_ready, lambda: arr.fetch_radarr(cfg)))
            if "lastfm" in sources:
                plan.append(("Last.fm", "albums", cfg.lastfm_ready, lambda: lastfm.fetch_albums(cfg, self.log, self.progress)))
            trakt = Trakt(cfg.get("TRAKT_CLIENT_ID"), cfg.get("TRAKT_USER"))
            for kind in ("shows", "movies"):
                if f"trakt_{kind}" in sources:
                    plan.append((f"Trakt {kind}", kind, cfg.trakt_ready, lambda k=kind: self._trakt_entries(trakt, k)))
            if not any(ready for _, _, ready, _ in plan):
                self.log("No selected source is configured - add its connection details in Settings.")

        for name, kind, ready, fetch in plan:
            if not ready:
                self.log(f"[{name}] skipped (not configured)")
                continue
            self.stage(f"Fetching {name}")
            try:
                self._merge(name, kind, fetch())
                self.progress(1, 1)                       # sources without steps of their own (Sonarr, Radarr) finish at 100%
                if name.startswith("Trakt"):
                    self._apply_ratings(kind)
            except Exception as e:  # one broken source must not stop the others
                self.log(f"[{name}] failed: {e}")
                self.summary.append(f"{name}: failed")
        for lib in self.libs.values():
            lib.save()
        if "posters" in steps:
            self.stage("Downloading posters")
            self._fill_posters()
        if "metadata" in steps:
            self.stage("Fetching metadata")
            self._fill_metadata()
        return self.summary

    def import_spotify(self, paths, liked=True, playlists=True, min_tracks=3, posters=True, metadata=False):
        """Add albums from Spotify export files, then (optionally) covers and MusicBrainz genres / country."""
        found = spotify.entries(paths, liked, playlists, min_tracks)
        self._merge("Spotify", "albums", found)
        self.libs["albums"].save()
        self.kinds = ("albums",)
        if posters:
            self._fill_posters()
        if metadata:
            self._album_metadata()
            self.libs["albums"].meta.save()
        return self.summary

    # ------------------------------------------------------------ merging
    def _merge(self, name, kind, entries):
        lib, added = self.libs[kind], 0
        for e in entries:
            label = self.label(e.title)
            if lib.is_removed(label):             # (older data) removed by hand
                continue
            if kind == "albums" and e.album:
                old = lib.canonical(e.album)    # old lists had album names without artist -> upgrade them
                if old and not lib.has(label):
                    lib.rename(old, label)
            if lib.add(label):
                added += 1
                self.log(f"[{name}] + {label}")
            e.label = lib.canonical(label) or label
            lib.meta.update(e.label, e.meta)
            self.seen[kind].append(e)
        self.log(f"[{name}] {len(entries)} found, {added} new")
        self.summary.append(f"{name}: +{added}")

    def _trakt_entries(self, trakt, kind):
        entries, self._ratings = trakt.collect(kind, self.progress)
        return entries

    def _apply_ratings(self, kind):
        """Titles you rated highly on Trakt become favorites."""
        lib, min_rating = self.libs[kind], self.cfg.integer("TRAKT_FAV_MIN_RATING", 0)
        if not (self.cfg.flag("TRAKT_SYNC_FAVORITES") and min_rating):
            return
        new = [t for t, r in self._ratings.items() if r >= min_rating and not lib.is_fav(self.label(t))]
        for t in new:
            lib.set_fav(self.label(t), True)
        self.log(f"[Trakt {kind}] {len(new)} new favorites (rated >= {min_rating})")

    # ------------------------------------------------------------ posters
    def _pool(self, jobs, work, workers=8):
        done = [0]

        def wrapped(job):
            self.check()
            result = work(job)
            done[0] += 1
            self.progress(done[0], len(jobs))
            return job, result

        with ThreadPoolExecutor(workers) as ex:
            yield from ex.map(wrapped, jobs)

    def _fill_posters(self):
        known = {kind: {} for kind in self.libs}
        for kind, entries in self.seen.items():
            for e in entries:    # prefer entries that carry a poster url
                if norm_key(e.label) not in known[kind] or e.poster:
                    known[kind][norm_key(e.label)] = e
        jobs = []
        for kind, lib in self.libs.items():
            if kind not in self.kinds:
                continue
            lib.index_posters()
            jobs += [(kind, lib, label, known[kind].get(norm_key(label))) for label in lib.missing_posters()
                     if not (kind == "albums" and lib.meta.get(label).get("cover_tried") and not known[kind].get(norm_key(label)))]   # misses are not retried every sync
        if not jobs:
            return
        self.log(f"Fetching {len(jobs)} missing posters...")
        key = self.cfg.get("TMDB_API_KEY")

        def work(job):
            kind, lib, label, e = job
            got = download_image(e.poster, e.poster_headers) if e and e.poster else None
            if not got and kind == "albums":                     # e.g. Spotify imports carry no picture
                m = lib.meta.get(label)
                if m.get("creators"):
                    for url in covers.album_cover_urls(self.cfg, m["creators"][0], m.get("title") or ""):
                        got = download_image(url)               # a source can know the album and still hand out a dead link
                        if got:
                            break
            tid = None
            if not got and key and kind != "albums":
                url, tid = tmdb.poster_url(key, kind, label, (e.tmdb_id if e else None) or lib.meta.get(label).get("ids", {}).get("tmdb"))
                got = download_image(url) if url else None
            return got, tid

        ok = 0
        for (kind, lib, label, _), (got, tid) in self._pool(jobs, work):
            if tid:                                       # remembered, so the metadata step does not search the title again
                lib.meta.update(label, {"ids": {"tmdb": tid}})
            if got:
                lib.set_poster(label, got[0], got[1])
                ok += 1
            else:
                if kind == "albums":
                    lib.meta.update(label, {"cover_tried": True})
                self.log(f"  no poster found: {label}")
        self.summary.append(f"posters: {ok}/{len(jobs)}")
        self.log(f"Posters downloaded: {ok}/{len(jobs)}")

    # ------------------------------------------------------------ metadata
    def _fill_metadata(self):
        """Genres/countries/creators for items that still lack them: TMDB (video) and Last.fm tags (albums)."""
        key = self.cfg.get("TMDB_API_KEY")
        if key:
            jobs = []
            for kind in ("shows", "movies"):
                if kind not in self.kinds:
                    continue
                lib = self.libs[kind]
                jobs += [(kind, lib, l) for l in lib.items
                         if self.force_meta or not (lib.meta.has_details(l) or lib.meta.get(l).get("tmdb_checked"))]
            if jobs:
                self.stage("Fetching details (TMDB)")
                self.log(f"Fetching details for {len(jobs)} titles (TMDB)...")
                work = lambda j: tmdb.details(key, j[0], j[2], j[1].meta.get(j[2]).get("ids", {}).get("tmdb"))
                for (kind, lib, label), meta in self._pool(jobs, work):
                    lib.meta.update(label, meta)
        if "albums" in self.kinds:
            self._album_metadata()
        for lib in self.libs.values():
            lib.meta.save()

    def _album_metadata(self):
        """Genres + country from MusicBrainz per artist (about one request per second), Last.fm tags as fallback."""
        lib, need, known = self.libs["albums"], {}, {}
        for label in lib.items:
            m = lib.meta.get(label)
            if not m.get("creators"):
                continue
            artist = m["creators"][0]
            if m.get("mb_checked") and not self.force_meta:
                known.setdefault(norm_key(artist), m)           # this artist was already looked up (via another album)
            else:
                need.setdefault(artist, []).append(label)
        for artist in [a for a in need if norm_key(a) in known]:        # a new album of an artist we already have: copy, no request
            src = known[norm_key(artist)]
            info = {k: src[k] for k in ("genres", "countries", "languages", "mb_checked") if src.get(k)}
            if src.get("ids", {}).get("artist_mbid"):
                info["ids"] = {"artist_mbid": src["ids"]["artist_mbid"]}
            for l in need.pop(artist):
                lib.meta.update(l, info)
        if not need:
            return
        mbids = {a: next((lib.meta.get(l).get("ids", {}).get("artist_mbid") for l in ls if lib.meta.get(l).get("ids", {}).get("artist_mbid")), None)
                 for a, ls in need.items()}
        self.stage("Looking up artists (MusicBrainz)")
        self.log(f"Looking up {len(need)} artists on MusicBrainz (about 1 per second, so this takes a while)...")
        for n, ((artist, labels), info) in enumerate(self._pool(list(need.items()), lambda it: musicbrainz.artist_details(it[0], mbids[it[0]]), 1), 1):
            if not info.get("genres") and info.get("mb_checked") and self.cfg.lastfm_ready:
                try:
                    info["genres"] = lastfm.artist_tags(self.cfg, artist)
                except Exception:
                    pass                          # a tag lookup failing must never lose the country / language we found
            for l in labels:
                lib.meta.update(l, info, replace=("genres",) if info.get("genres") else ())
            if n % 10 == 0:
                lib.meta.save()                   # keep progress if the sync is interrupted
                self.log(f"MusicBrainz: {n}/{len(need)} artists done")
        lib.meta.save()


def test_connection(which, cfg) -> str:
    """Short human readable status line for the Settings dialog / CLI."""
    try:
        if which == "sonarr":
            return "OK - Sonarr v" + arr.sonarr(cfg).version()
        if which == "radarr":
            return "OK - Radarr v" + arr.radarr(cfg).version()
        if which == "trakt":
            Trakt(cfg.get("TRAKT_CLIENT_ID"), cfg.get("TRAKT_USER")).check()
            return "OK - Trakt profile reachable"
        if which == "lastfm":
            lastfm.check(cfg)
            return "OK - Last.fm user found"
    except Exception as e:
        return f"Failed - {e}"
    return "Unknown source"

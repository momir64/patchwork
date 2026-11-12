"""Which of an artist's releases are singles, and the songs of the singles and of the artist's albums. Used to find singles that
are part of an album you already have (core/singles.py reads what is stored here).

Spotify is asked first when its credentials are set (an artist's songs come many albums per request), Deezer (no key) for
everything Spotify can not answer, and for the whole run once Spotify holds this app back (rate limit). Per artist: one search, one
list of the discography (with the release types), then the songs of the singles among your titles and of the albums to compare
with. Everything read is cached, so later runs only look up new artists and new albums."""
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..core import singles
from ..core.names import fold
from . import spotify_api
from .http import TIMEOUT, session

DEEZER = "https://api.deezer.com"
_lock, _last = threading.Lock(), [0.0]
EP_FROM = 5                                                   # Spotify calls an EP a single too: from this many songs it is an EP


class Quota(Exception):
    """Deezer says no more requests for now."""


def _norm(s):
    return re.sub(r"[^\w]+", " ", fold(s).casefold()).strip()


class Deezer:
    """No key needed; ~50 requests / 5 s, so the calls are spaced out. Ids look like 'dz:123'."""
    name, prefix = "Deezer", "dz:"

    def _get(self, path, **params):
        for attempt in range(4):
            with _lock:
                wait = 0.12 - (time.time() - _last[0])
                if wait > 0:
                    time.sleep(wait)
                _last[0] = time.time()
            data = session.get(DEEZER + path, params=params, timeout=TIMEOUT).json()
            err = data.get("error") if isinstance(data, dict) else None
            if not err:
                return data
            if err.get("code") == 4 and attempt < 3:            # quota exceeded: wait a little
                time.sleep(5 * (attempt + 1))
                continue
            raise Quota(str(err.get("message") or err))
        raise Quota("quota exceeded")

    def find_artist(self, name):
        data = self._get("/search/artist", q=name.replace('"', " "), limit=15).get("data") or []
        same = [a for a in data if _norm(a.get("name", "")) == _norm(name)]
        return self.prefix + str(max(same, key=lambda a: a.get("nb_fan", 0))["id"]) if same else None

    def discography(self, artist_id):
        out, index = {}, 0
        while index <= 1000:
            page = self._get(f"/artist/{artist_id[len(self.prefix):]}/albums", limit=100, index=index)
            for a in page.get("data") or []:
                out[self.prefix + str(a["id"])] = {"t": a.get("title", ""), "k": a.get("record_type", "album")}
            if not page.get("next"):
                break
            index += 100
        return out

    def songs(self, ids):
        return {i: [t.get("title", "") for t in self._get(f"/album/{i[len(self.prefix):]}/tracks", limit=200).get("data") or []] for i in ids}


class Spotify:
    """Your own app's credentials (client credentials: public catalog only). Ids look like 'sp:abc'."""
    name, prefix = "Spotify", "sp:"

    def __init__(self, cfg):
        self.cfg = cfg

    def find_artist(self, name):
        found = spotify_api.find_artist(self.cfg, name)
        return self.prefix + found if found else None

    def discography(self, artist_id):
        out = {}
        for aid, title, kind, count in spotify_api.artist_releases(self.cfg, artist_id[len(self.prefix):]):
            k = {"compilation": "compile", "single": "single" if count < EP_FROM else "ep"}.get(kind, "album")
            out[self.prefix + aid] = {"t": title, "k": k}
        return out

    def songs(self, ids):
        got = spotify_api.album_songs(self.cfg, [i[len(self.prefix):] for i in ids])
        return {i: got.get(i[len(self.prefix):], []) for i in ids}


class Sources:
    """The sources in the order they are asked; one that holds us back (rate limit, refused credentials) is skipped from then on."""

    def __init__(self, cfg, log=print):
        self.items = ([Spotify(cfg)] if spotify_api.available(cfg) else []) + [Deezer()]
        self.log, self._lock = log, threading.Lock()

    def usable(self):
        with self._lock:
            return list(self.items)

    def down(self, source, why):
        with self._lock:
            if source in self.items:
                self.items.remove(source)
                self.log(f"{source.name} is not available now ({why})" + ("; using Deezer instead" if self.items else ""))


def _fill(source, lib, name, labels, entry, cancelled):
    """The artist's cache entry from this source, brought up to date; None when the source does not know the artist."""
    entry = dict(entry) if entry and entry.get("src") == source.prefix and entry.get("id") else {}
    if not entry.get("id"):
        found = source.find_artist(name)
        if found is None:
            return None
        entry = {"id": found, "src": source.prefix, "at": 0, "albums": {}, "tracks": {}}
    stale = len(singles.match(lib, labels, entry)) < len(labels) and time.time() - entry.get("at", 0) > singles.REFRESH_AFTER
    if not entry["albums"] or stale:
        entry["albums"] = source.discography(entry["id"])
        entry["at"] = time.time()
    entry.setdefault("tracks", {})
    only, albums, hits = singles.split(lib, labels, entry)
    if only and not cancelled():                                # songs only matter when there is a single to place
        want = [hits[s][0][0] for s in only] + [aid for l in albums for aid, k in hits[l][:3]]
        entry["tracks"].update(source.songs([a for a in dict.fromkeys(want) if a not in entry["tracks"]]))
    return entry


def lookup(lib, name, labels, entry, sources, cancelled):
    """One artist: the first source that knows them. A source that fails is tried past (and dropped when it holds us back)."""
    failure = None
    for source in sources.usable():
        try:
            found = _fill(source, lib, name, labels, entry, cancelled)
        except (spotify_api.Limited, Quota) as e:
            sources.down(source, str(e))
            failure = e
            continue
        except RuntimeError as e:                               # refused credentials, a cancelled sync
            if source.prefix == "sp:":
                sources.down(source, str(e))
            failure = e
            continue
        except Exception as e:                                  # network trouble: the next source may still answer
            failure = e
            continue
        if found is not None:
            return found
    if failure:
        raise failure
    return {"id": None, "src": None, "at": time.time(), "albums": {}, "tracks": {}}      # nobody knows this artist


def run(lib, cfg, progress=None, cancelled=lambda: False, log=print, workers=4) -> dict:
    """Look up every artist that still needs it (several at once; the request spacing is shared). Returns
    {"looked": n, "failed": n, "total": n}. What was read is saved as it goes, so stopping loses nothing."""
    cache = singles.load_cache(lib.kind)
    todo = singles.pending(lib, cache)
    total, looked, failed, errors = len(todo), 0, 0, 0
    if not total:
        return {"looked": 0, "failed": 0, "total": 0}
    sources = Sources(cfg, log)
    log(f"Looking up {total} artists for singles ({' / '.join(s.name for s in sources.usable())})...")
    if progress:
        progress(0, total)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(lambda k=key, n=name, l=labels: None if cancelled() else lookup(lib, n, l, cache.get(k), sources, cancelled)): key
                   for key, name, labels in todo}
        for n, f in enumerate(as_completed(futures), 1):
            try:
                entry = f.result()
                if entry is not None:
                    cache[futures[f]] = entry
                    looked += 1
                    errors = 0
            except Exception as e:                              # one artist failing (network, odd answer) does not stop the rest
                failed += 1
                errors += 1
                if errors >= 8:
                    log(f"No source is answering ({type(e).__name__}); stopping")
                    for g in futures:
                        g.cancel()
                    break
            if progress:
                progress(n, total)
            if n % 40 == 0:
                singles.save_cache(cache, lib.kind)
                log(f"Singles: {n} of {total} artists looked up")
    singles.save_cache(cache, lib.kind)
    return {"looked": looked, "failed": failed, "total": total}

"""Album covers for albums that no source handed a picture for (Spotify imports): Deezer, iTunes (no keys), Last.fm, then the
Cover Art Archive. They are tried in that order and only as far as needed."""
import re
import threading
import time

from ..core.editions import base_key
from .http import TIMEOUT, session
from . import lastfm

_lock, _last = threading.Lock(), [0.0]


def _norm(s):
    return re.sub(r"[^\w]+", " ", s.casefold()).strip()


def _deezer(artist, album):
    for q in (f'artist:"{artist}" album:"{album}"', f"{artist} {album}"):
        with _lock:                                   # Deezer allows ~50 requests / 5 s
            wait = 0.15 - (time.time() - _last[0])
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.time()
        r = session.get("https://api.deezer.com/search/album", params={"q": q, "limit": 10}, timeout=TIMEOUT).json()
        for a in r.get("data") or []:
            if _norm(a["artist"]["name"]) == _norm(artist) and (_norm(a["title"]) == _norm(album) or
                                                                 base_key(a["title"]) == base_key(album)):
                return a.get("cover_xl") or a.get("cover_big")
    return None


_itunes_lock, _itunes_last = threading.Lock(), [0.0]


_RELEASE_TYPE = re.compile(r"\s+-\s+(single|ep)\s*$", re.I)


def _same_album(found_artist, found_title, artist, album):
    if _norm(found_artist) != _norm(artist):
        return False
    found = _RELEASE_TYPE.sub("", found_title)                  # 'Lord of Chaos - EP' is the album 'Lord of Chaos'
    return any(_norm(f) == _norm(album) or base_key(f) == base_key(album) for f in (found_title, found))


def _itunes(artist, album):
    """iTunes / Apple Music search (no key). Its artwork url ends in '100x100bb.jpg': the same file exists at any size."""
    with _itunes_lock:                                # Apple asks for roughly 20 requests a minute: stay polite
        wait = 0.6 - (time.time() - _itunes_last[0])
        if wait > 0:
            time.sleep(wait)
        _itunes_last[0] = time.time()
    r = session.get("https://itunes.apple.com/search", params={"term": f"{artist} {album}", "entity": "album", "limit": 10}, timeout=TIMEOUT)
    r.raise_for_status()
    for a in r.json().get("results") or []:
        if _same_album(a.get("artistName", ""), a.get("collectionName", ""), artist, album) and a.get("artworkUrl100"):
            return re.sub(r"\d+x\d+bb", "1000x1000bb", a["artworkUrl100"])
    return None


def _cover_art_archive(artist, album):
    """MusicBrainz release group -> Cover Art Archive front cover (slow: MusicBrainz allows one request a second)."""
    from . import musicbrainz
    q = f'releasegroup:"{album}" AND artist:"{artist}"'
    for g in musicbrainz._get("release-group", query=q, limit=5).get("release-groups", []):
        credit = " ".join(c.get("name", "") for c in g.get("artist-credit", []) if isinstance(c, dict))
        if g.get("score", 0) >= 90 and _same_album(credit, g.get("title", ""), artist, album):
            return f"https://coverartarchive.org/release-group/{g['id']}/front-500"
    return None


def album_cover_urls(cfg, artist, album):
    """Candidate cover urls, best / cheapest source first. It is a generator: the caller stops at the first one that works,
    so the slow sources are only asked when the quick ones found nothing."""
    def lastfm_url():
        if not cfg.lastfm_ready:
            return None
        info = lastfm._call(cfg, "album.getInfo", artist=artist, album=album, autocorrect=1)["album"]
        url = (info.get("image") or [{}])[-1].get("#text", "")
        return url if url and lastfm.BLANK_COVER not in url else None

    for source in (_deezer, _itunes, lastfm_url, _cover_art_archive):
        try:
            url = source(artist, album) if source is not lastfm_url else source()
        except Exception:
            continue
        if url:
            yield url


def album_cover(cfg, artist, album):
    """First candidate url or None."""
    return next(album_cover_urls(cfg, artist, album), None)

"""Album covers for albums that no source handed a picture for (Spotify imports): Deezer, iTunes (no keys), Last.fm, then the
Cover Art Archive. They are tried in that order and only as far as needed."""
import re
import threading
import time

from ..core.editions import base_key
from .http import TIMEOUT, once, session
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


_itunes_cache = {}


def _itunes_results(artist, album) -> list:
    """iTunes / Apple Music search (no key), asked once per album: the cover and the release year share the answer.
    Apple asks for roughly 20 requests a minute, so the requests are spaced out."""
    def fetch():
        with _itunes_lock:
            wait = 0.6 - (time.time() - _itunes_last[0])
            if wait > 0:
                time.sleep(wait)
            _itunes_last[0] = time.time()
        r = session.get("https://itunes.apple.com/search", params={"term": f"{artist} {album}", "entity": "album", "limit": 15}, timeout=TIMEOUT)
        r.raise_for_status()
        return [a for a in r.json().get("results") or [] if _same_album(a.get("artistName", ""), a.get("collectionName", ""), artist, album)]

    return once(_itunes_cache, (_norm(artist), _norm(album)), fetch)


def album_year(artist, album):
    """Release year of an album from iTunes, or None. A re-release carries a later date, so the earliest year among the
    matching editions is used."""
    years = [int(a["releaseDate"][:4]) for a in _itunes_results(artist, album) if str(a.get("releaseDate", ""))[:4].isdigit()]
    return min(years) if years else None


def _itunes(artist, album):
    """Its artwork url ends in '100x100bb.jpg': the same file exists at any size."""
    for a in _itunes_results(artist, album):
        if a.get("artworkUrl100"):
            return re.sub(r"\d+x\d+bb", "1000x1000bb", a["artworkUrl100"])
    return None


def _cover_art_archive(artist, album, mbid=None):
    """MusicBrainz release group -> Cover Art Archive front cover. With the artist's MusicBrainz id the release groups come
    from the one list per artist that the release-year lookup uses too (no search per album)."""
    from . import musicbrainz
    if mbid:
        group = musicbrainz.group_for(musicbrainz.artist_groups(mbid), album)
        return f"https://coverartarchive.org/release-group/{group['id']}/front-500" if group else None
    q = f'releasegroup:"{album}" AND artist:"{artist}"'
    for g in musicbrainz._get("release-group", query=q, limit=5).get("release-groups", []):
        credit = " ".join(c.get("name", "") for c in g.get("artist-credit", []) if isinstance(c, dict))
        if g.get("score", 0) >= 90 and _same_album(credit, g.get("title", ""), artist, album):
            return f"https://coverartarchive.org/release-group/{g['id']}/front-500"
    return None


def album_cover_urls(cfg, artist, album, mbid=None):
    """Candidate cover urls, best / cheapest source first: Spotify (when its credentials are set), Deezer, iTunes, Last.fm,
    then MusicBrainz + Cover Art Archive. It is a generator: the caller stops at the first one that works, so the slow
    sources are only asked when the quick ones found nothing."""
    def spotify_url():
        if not cfg.spotify_ready:
            return None
        from . import spotify_api
        return spotify_api.album_cover(cfg, artist, album)

    def lastfm_url():
        if not cfg.lastfm_ready:
            return None
        info = lastfm._call(cfg, "album.getInfo", artist=artist, album=album, autocorrect=1)["album"]
        url = (info.get("image") or [{}])[-1].get("#text", "")
        return url if url and lastfm.BLANK_COVER not in url else None

    for source in (spotify_url, lambda: _deezer(artist, album), lambda: _itunes(artist, album), lastfm_url,
                   lambda: _cover_art_archive(artist, album, mbid)):
        try:
            url = source()
        except Exception:
            continue
        if url:
            yield url


def album_cover(cfg, artist, album, mbid=None):
    """First candidate url or None."""
    return next(album_cover_urls(cfg, artist, album, mbid), None)

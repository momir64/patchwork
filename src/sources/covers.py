"""Album covers for albums that no source handed a picture for (Spotify imports): Deezer search (no key), then Last.fm."""
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


def album_cover(cfg, artist, album):
    """Image url or None."""
    try:
        url = _deezer(artist, album)
        if url:
            return url
    except Exception:
        pass
    if cfg.lastfm_ready:
        try:
            info = lastfm._call(cfg, "album.getInfo", artist=artist, album=album, autocorrect=1)["album"]
            url = (info.get("image") or [{}])[-1].get("#text", "")
            if url and lastfm.BLANK_COVER not in url:
                return url
        except Exception:
            pass
    return None

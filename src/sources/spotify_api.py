"""Spotify Web API with your own app's credentials (client credentials flow: public catalog data only, no login)."""
import threading
import time

from .covers import _norm, _same_album
import requests
from requests.adapters import HTTPAdapter

from .http import TIMEOUT, once

# an own session without automatic retries: the shared one would quietly sit out a rate limit's Retry-After (even hours)
session = requests.Session()
session.headers["User-Agent"] = "patchwork/1.0"
session.mount("https://", HTTPAdapter(pool_connections=8, pool_maxsize=16, max_retries=0))
TOKEN_URL = "https://accounts.spotify.com/api/token"
SEARCH_URL = "https://api.spotify.com/v1/search"
_lock, _last = threading.Lock(), [0.0]
_token = {"value": None, "until": 0.0, "id": None}
_pace = {"gap": 0.3}                                 # seconds between searches (slower after every rate limit answer)
_blocked = {}                                        # client id -> when Spotify lets this app search again (a ban belongs to the app)
should_stop = lambda: False                         # set by the sync: true once it was cancelled


class Limited(RuntimeError):
    """Spotify asked us to stop for a while: the caller moves on to the next source instead of waiting."""


def _sleep(seconds):
    """A pause that ends early when the sync is cancelled."""
    end = time.time() + seconds
    while time.time() < end and not should_stop():
        time.sleep(0.25)


def token(cfg) -> str:
    """An access token for the catalog endpoints (valid for an hour, kept until shortly before it runs out).
    Raises with a readable message when Spotify refuses the credentials."""
    cid, secret = cfg.get("SPOTIFY_CLIENT_ID"), cfg.get("SPOTIFY_CLIENT_SECRET")
    if not (cid and secret):
        raise RuntimeError("Client ID and Client secret are needed")
    with _lock:
        if _token["value"] and _token["id"] == (cid, secret) and time.time() < _token["until"]:
            return _token["value"]
        r = session.post(TOKEN_URL, data={"grant_type": "client_credentials"}, auth=(cid, secret), timeout=TIMEOUT)
        if r.status_code in (400, 401):
            raise RuntimeError("Spotify refused these credentials")
        r.raise_for_status()
        data = r.json()
        _token.update(value=data["access_token"], until=time.time() + int(data.get("expires_in", 3600)) - 60, id=(cid, secret))
        return _token["value"]


def check(cfg):
    token(cfg)


_searches = {}


def search(cfg, artist, album) -> list:
    """Albums Spotify returns for 'artist + album': [{artists, name, year, image}]. Asked once per album: the year lookup and
    the cover lookup share the answer. Raises on network / rate limit trouble so the caller can try again later."""
    return once(_searches, (_norm(artist), _norm(album)), lambda: _search(cfg, artist, album))


def _search(cfg, artist, album) -> list:
    cid = cfg.get("SPOTIFY_CLIENT_ID")
    for attempt in range(3):
        if time.time() < _blocked.get(cid, 0.0):
            raise Limited("Spotify rate limit: paused for a while")
        with _lock:
            wait = _pace["gap"] - (time.time() - _last[0])
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.time()
        r = session.get(SEARCH_URL, params={"q": f'album:"{album}" artist:"{artist}"', "type": "album", "limit": 10},
                        headers={"Authorization": "Bearer " + token(cfg)}, timeout=TIMEOUT)
        if r.status_code == 429:
            pause = int(r.headers.get("Retry-After", "2") or 2)
            _pace["gap"] = min(2.0, _pace["gap"] * 2)                     # every later search goes slower
            if pause > 20:                                                 # a long ban: do not sit it out
                _blocked[cid] = time.time() + pause
                raise Limited(f"Spotify rate limit reached (retry after {pause} s)")
            _sleep(pause + 1)
            if should_stop():
                raise RuntimeError("cancelled")
            continue
        r.raise_for_status()
        out = []
        for a in r.json().get("albums", {}).get("items") or []:
            images = a.get("images") or []
            out.append({"artists": [x.get("name", "") for x in a.get("artists") or []], "name": a.get("name", ""),
                        "year": str(a.get("release_date") or "")[:4], "image": images[0]["url"] if images else None})
        return out
    _blocked[cid] = time.time() + 300
    raise Limited("Spotify keeps rate limiting: paused for 5 minutes")


def _matching(cfg, artist, album):
    return [a for a in search(cfg, artist, album) if any(_same_album(n, a["name"], artist, album) for n in a["artists"])]


def album_year(cfg, artist, album):
    """Release year of an album (the earliest among the matching editions), or None when Spotify does not know it."""
    years = [int(a["year"]) for a in _matching(cfg, artist, album) if a["year"].isdigit()]
    return min(years) if years else None


def album_cover(cfg, artist, album):
    """Cover url (640 px) of the album, or None."""
    return next((a["image"] for a in _matching(cfg, artist, album) if a["image"]), None)

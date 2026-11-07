"""MusicBrainz: clean genres + country for an artist (free, no key; limited to ~1 request per second)."""
import threading
import time

from .http import TIMEOUT, session
from .lookups import country, country_language, title_case

API = "https://musicbrainz.org/ws/2"
HEADERS = {"User-Agent": "Patchwork/1.0 (personal media collage tool)", "Accept": "application/json"}
_lock, _last = threading.Lock(), [0.0]


def _get(path, **params):
    with _lock:                                   # one request at a time, spaced out
        wait = 1.1 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        for attempt in range(2):
            r = session.get(f"{API}/{path}", params={**params, "fmt": "json"}, headers=HEADERS, timeout=TIMEOUT)
            _last[0] = time.time()
            if r.status_code in (429, 503) and attempt == 0:
                time.sleep(3)
                continue
            r.raise_for_status()
            return r.json()


def find_artist_id(name):
    res = _get("artist", query=f'artist:"{name}"', limit=5).get("artists", [])
    res = [a for a in res if a.get("score", 0) >= 85]
    exact = [a for a in res if a.get("name", "").casefold() == name.casefold()]
    pick = (exact or res or [None])[0]
    return pick["id"] if pick else None


def artist_details(name, mbid=None) -> dict:
    """{genres, countries, languages, ids} - empty fields when unknown. Always marks the artist as checked."""
    out = {"mb_checked": True}
    try:
        mbid = mbid or find_artist_id(name)
        if not mbid:
            return out
        a = _get(f"artist/{mbid}", inc="genres")
        genres = sorted(a.get("genres", []), key=lambda g: -g.get("count", 0))[:3]
        code = a.get("country") or next(iter((a.get("area") or {}).get("iso-3166-1-codes") or []), None)
        place = (a.get("area") or {}).get("name")
        out.update(genres=[title_case(g["name"]) for g in genres],
                   countries=country(code) if code else place,
                   languages=country_language(code) if code else None,
                   ids={"artist_mbid": mbid})
    except Exception:
        out.pop("mb_checked")                     # network problem: try again next time
    return out

"""MusicBrainz: clean genres + country for an artist (free, no key; limited to ~1 request per second)."""
import re
import threading
import time

from ..core.editions import base_key
from .http import TIMEOUT, once, session
from .lookups import country, country_language, title_case

API = "https://musicbrainz.org/ws/2"
HEADERS = {"User-Agent": "Patchwork/1.0 (personal media collage tool)", "Accept": "application/json"}
_lock, _last = threading.Lock(), [0.0]


def _get(path, **params):
    with _lock:                                   # one request at a time, spaced out
        for attempt in range(2):
            wait = 1.05 - (time.time() - _last[0])          # spaced from the START of the previous request, not its end
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.time()
            r = session.get(f"{API}/{path}", params={**params, "fmt": "json"}, headers=HEADERS, timeout=TIMEOUT)
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


def _key(title):
    return re.sub(r"[^\w]+", " ", title.casefold()).strip()


_groups = {}


def artist_groups(mbid) -> list:
    """[{id, title, year}] for the albums, EPs and singles of an artist (one request per 100 releases), asked once per artist:
    the release-year lookup and the cover lookup both use it."""
    return once(_groups, mbid, lambda: _artist_groups(mbid))


def _artist_groups(mbid) -> list:
    out, offset = [], 0
    while offset < 500:
        data = _get("release-group", artist=mbid, type="album|ep|single", limit=100, offset=offset)
        for g in data.get("release-groups", []):
            date = str(g.get("first-release-date") or "")
            kind = "compile" if "Compilation" in (g.get("secondary-types") or []) else str(g.get("primary-type") or "album").casefold()
            out.append({"id": g["id"], "title": g["title"], "year": int(date[:4]) if date[:4].isdigit() else None, "type": kind})
        offset += 100
        if offset >= data.get("release-group-count", 0):
            break
    return out


def artist_years(mbid) -> dict:
    """{title key: year of the first release}. Each title is stored plain and without edition words, so 'X (Deluxe)' finds the
    year of 'X'."""
    out = {}
    for g in artist_groups(mbid):
        if g["year"]:
            for k in (_key(g["title"]), base_key(g["title"])):
                out[k] = min(g["year"], out.get(k, g["year"]))
    return out


def artist_types(mbid) -> dict:
    """{title key: release type (album / single / ep / compile)} from the same list as the years: no extra request."""
    out = {}
    for g in artist_groups(mbid):
        for k in (_key(g["title"]), base_key(g["title"])):
            out.setdefault(k, g.get("type") or "album")
    return out


def type_of(types, album):
    return types.get(_key(album)) or types.get(base_key(album))


def group_for(groups, album):
    """The release group of an album: the exact title first, else the one without edition words."""
    by_title = [g for g in groups if _key(g["title"]) == _key(album)] or [g for g in groups if base_key(g["title"]) == base_key(album)]
    return by_title[0] if by_title else None


def year_of(years, album):
    return years.get(_key(album)) or years.get(base_key(album))


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

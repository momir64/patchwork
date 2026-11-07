"""Last.fm: top albums (with cover art) and artist tags (used as genres, e.g. 'Black Metal')."""
import threading
import time

from .entry import Entry
from .http import TIMEOUT, session
from .lookups import title_case

API = "https://ws.audioscrobbler.com/2.0/"
BLANK_COVER = "2a96cbd8b46e442fc41c2b86b821562f"   # the grey "no cover" star
JUNK_TAGS = ("seen live", "favorite", "favorite", "albums i own", "owned", "my ", "spotify", "love", "check out")


_lock, _last = threading.Lock(), [0.0]
MIN_GAP = 0.3                       # seconds between requests: ~3/s, well under Last.fm's ~5/s limit for API keys
RETRY_CODES = {8, 11, 16, 29}       # operation failed / service offline / temporarily unavailable / rate limit exceeded
HEADERS = {"User-Agent": "Patchwork/1.0 (personal media collage tool)"}
PERIOD_DAYS = {"7day": 7, "1month": 30, "3month": 91, "6month": 182, "12month": 365}


def _call(cfg, method, **params):
    """One API call, spaced out and retried with growing pauses on rate limits / temporary errors."""
    for attempt in range(6):
        with _lock:
            wait = MIN_GAP - (time.time() - _last[0])
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.time()
        try:
            resp = session.get(API, timeout=TIMEOUT, headers=HEADERS,
                               params={"method": method, "api_key": cfg.get("LASTFM_API_KEY"), "format": "json", **params})
        except Exception:
            if attempt == 5:
                raise
            time.sleep(2 * 2 ** attempt)
            continue
        if resp.status_code in (429, 500, 502, 503, 504):
            time.sleep(min(60, 3 * 2 ** attempt))
            continue
        r = resp.json()
        if "error" in r:
            if r["error"] in RETRY_CODES and attempt < 5:
                time.sleep(min(60, 3 * 2 ** attempt))
                continue
            raise RuntimeError(f"Last.fm: {r.get('message')}")
        return r
    raise RuntimeError("Last.fm: too many failed attempts, try again later")


def check(cfg):
    _call(cfg, "user.getInfo", user=cfg.get("LASTFM_USER"))


def fetch_albums(cfg, log=print, progress=None) -> list:
    return fetch_recent_albums(cfg, log, progress) if cfg.get("LASTFM_SOURCE") == "recent" else fetch_top_albums(cfg, progress)


def fetch_recent_albums(cfg, log=print, progress=None) -> list:
    """Albums built from your scrobble history: plays are counted per album over the chosen period.
    Uses the biggest page size the API allows (200) and the paced _call, so even 100k scrobbles stay polite."""
    limit = cfg.integer("LASTFM_LIMIT", 1024) or 10 ** 9
    days = PERIOD_DAYS.get(cfg.get("LASTFM_PERIOD"))
    params = dict(user=cfg.get("LASTFM_USER"), limit=200)
    if days:
        params["from"] = int(time.time()) - days * 86400
    counts, page, pages = {}, 1, 1
    while page <= pages:
        data = _call(cfg, "user.getRecentTracks", page=page, **params)["recenttracks"]
        pages = int(data["@attr"]["totalPages"] or 1)
        for t in data.get("track", []):
            if (t.get("@attr") or {}).get("nowplaying"):
                continue
            album, artist = (t.get("album") or {}).get("#text", ""), (t.get("artist") or {}).get("#text", "")
            if not album or not artist:
                continue
            c = counts.setdefault((artist.casefold(), album.casefold()), {"artist": artist, "album": album, "plays": 0, "t": t})
            c["plays"] += 1
        if progress:
            progress(page, pages)
        if page % 10 == 0 or page == pages:
            log(f"[Last.fm] history page {page}/{pages}, {len(counts)} albums so far")
        page += 1
    out = []
    for c in sorted(counts.values(), key=lambda c: -c["plays"])[:limit]:
        t = c["t"]
        url = (t.get("image") or [{}])[-1].get("#text", "")
        meta = dict(title=c["album"], creators=c["artist"], playcount=c["plays"],
                    ids=dict(mbid=(t.get("album") or {}).get("mbid"), artist_mbid=(t.get("artist") or {}).get("mbid")))
        out.append(Entry(f"{c['artist']} - {c['album']}", meta, None if BLANK_COVER in url else (url or None), album=c["album"]))
    return out


def fetch_top_albums(cfg, progress=None) -> list:
    limit = cfg.integer("LASTFM_LIMIT", 1024) or 10 ** 9      # 0 = every album
    albums, page = [], 1
    while len(albums) < limit:
        data = _call(cfg, "user.getTopAlbums", user=cfg.get("LASTFM_USER"),
                     period=cfg.get("LASTFM_PERIOD") or "overall", limit=50, page=page)["topalbums"]
        albums += data.get("album", [])
        pages = min(int(data["@attr"]["totalPages"] or 1), -(-limit // 50))      # pages that will really be needed
        if progress:
            progress(page, pages)
        if not data.get("album") or page >= pages:
            break
        page += 1
    out = []
    for a in albums[:limit]:
        url = a["image"][-1]["#text"] if a.get("image") else ""
        artist = a["artist"]["name"]
        meta = dict(title=a["name"], creators=artist, playcount=int(a.get("playcount") or 0),
                    ids=dict(mbid=a.get("mbid"), artist_mbid=a["artist"].get("mbid")))
        out.append(Entry(f"{artist} - {a['name']}", meta, None if BLANK_COVER in url else (url or None), album=a["name"]))
    return out


def artist_tags(cfg, artist) -> list:
    try:
        tags = _call(cfg, "artist.getTopTags", artist=artist, autocorrect=1)["toptags"].get("tag", [])
        names = [t["name"] for t in tags if int(t.get("count", 0)) >= 40 and not any(j in t["name"].lower() for j in JUNK_TAGS)]
        return [title_case(n) for n in names[:3]]
    except Exception:
        return []

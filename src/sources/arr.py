"""Sonarr (shows) and Radarr (movies) - both speak the same v3 API."""
from .entry import Entry
from .http import TIMEOUT, base_url, session
from .lookups import movie_label


class Arr:
    def __init__(self, url, key):
        self.url, self.headers = base_url(url), {"X-Api-Key": key}

    def get(self, path, **params):
        r = session.get(f"{self.url}/api/v3/{path}", headers=self.headers, params=params, timeout=TIMEOUT)
        if r.status_code == 401:
            raise RuntimeError("401 Unauthorized - check the API key")
        r.raise_for_status()
        return r.json()

    def version(self):
        return self.get("system/status").get("version", "?")

    def poster(self, item):
        """(url, headers): public artwork url if present, else the instance's own cover cache."""
        for im in item.get("images", []):
            if im.get("coverType") == "poster":
                if im.get("remoteUrl"):
                    return im["remoteUrl"], None
                if im.get("url"):
                    return self.url + im["url"], self.headers
        return None, None


def sonarr(cfg) -> Arr:
    return Arr(cfg.get("SONARR_URL"), cfg.get("SONARR_API_KEY"))


def radarr(cfg) -> Arr:
    return Arr(cfg.get("RADARR_URL"), cfg.get("RADARR_API_KEY"))


def fetch_sonarr(cfg) -> list:
    arr, out = sonarr(cfg), []
    for s in arr.get("series"):
        if cfg.flag("SONARR_ONLY_DOWNLOADED") and not s.get("statistics", {}).get("episodeFileCount"):
            continue
        meta = dict(title=s["title"], year=s.get("year"), genres=s.get("genres"),
                    languages=(s.get("originalLanguage") or {}).get("name"), studio=s.get("network"),
                    overview=s.get("overview"), status=s.get("status"), rating=(s.get("ratings") or {}).get("value"),
                    ids=dict(tvdb=s.get("tvdbId"), tmdb=s.get("tmdbId"), imdb=s.get("imdbId")))
        url, hdr = arr.poster(s)
        out.append(Entry(s["title"], meta, url, hdr, s.get("tmdbId")))
    return out


def fetch_radarr(cfg) -> list:
    arr, out = radarr(cfg), []
    for m in arr.get("movie"):
        if cfg.flag("RADARR_ONLY_DOWNLOADED") and not m.get("hasFile"):
            continue
        if cfg.flag("RADARR_ONLY_UNMONITORED") and m.get("monitored"):
            continue                                  # still monitored in Radarr: added once you unmonitor it
        meta = dict(title=m["title"], year=m.get("year"), genres=m.get("genres"),
                    languages=(m.get("originalLanguage") or {}).get("name"), studio=m.get("studio"),
                    overview=m.get("overview"), rating=((m.get("ratings") or {}).get("tmdb") or {}).get("value"),
                    ids=dict(tmdb=m.get("tmdbId"), imdb=m.get("imdbId")))
        url, hdr = arr.poster(m)
        out.append(Entry(movie_label(m["title"], m.get("year")), meta, url, hdr, m.get("tmdbId")))
    return out

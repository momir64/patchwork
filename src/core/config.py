"""Settings + data locations.

Everything secret lives in a single .env file in the project root.
All data is plain files under ./data so it can be browsed/edited by hand:

    data/
      shows|movies|albums/
        library.json      titles, favorites, hidden and removed titles
        meta.json         genres, countries, languages, creators, ids ... (keyed by title)
        groups.json       hand-made groups of this category: {name: [titles]}
        duplicates.json   duplicate sets marked "not duplicates" and titles hidden as duplicates
        posters/          <title>.jpg
      output/             finished collages
      aliases.json        different spellings of one title (older txt files are kept in data/_txt_backup)
"""
import os
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)                            # running as the packaged .exe
RES = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))     # bundled read-only files (assets)
ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parents[2]   # .env and data/ live next to the exe
ENV_PATH = ROOT / ".env"
DATA_DIR = ROOT / "data"
OUTPUT_DIR = DATA_DIR / "output"
ALIASES_PATH = DATA_DIR / "aliases.json"
KIND_NAMES = ("shows", "movies", "albums")


def kind_dir(kind: str) -> Path:
    return DATA_DIR / kind


# key -> (default, description)
KEYS = {
    "SONARR_URL": ("http://localhost:8989", "Sonarr address (TV shows)"),
    "SONARR_API_KEY": ("", "Sonarr -> Settings -> General -> API Key"),
    "RADARR_URL": ("http://localhost:7878", "Radarr address (movies)"),
    "RADARR_API_KEY": ("", "Radarr -> Settings -> General -> API Key"),
    "SONARR_ONLY_DOWNLOADED": ("false", "true = only shows that actually have files in Sonarr"),
    "RADARR_ONLY_DOWNLOADED": ("false", "true = only movies that actually have files in Radarr"),
    "RADARR_ONLY_UNMONITORED": ("true", "true = only movies Radarr no longer monitors (the ones that are done / watched)"),
    "TRAKT_CLIENT_ID": ("", "https://trakt.tv/oauth/applications -> your app's Client ID"),
    "TRAKT_USER": ("", "Trakt username (profile must be public)"),
    "TRAKT_SYNC_FAVORITES": ("false", "true = titles you rated highly on Trakt become favorites"),
    "TRAKT_FAV_MIN_RATING": ("9", "Minimum Trakt rating (1-10) that counts as a favorite"),
    "LASTFM_API_KEY": ("", "https://www.last.fm/api/account/create"),
    "LASTFM_USER": ("", "Last.fm username"),
    "LASTFM_SOURCE": ("top", "top = your top albums | recent = built from your scrobble history (slower)"),
    "LASTFM_PERIOD": ("overall", "overall | 7day | 1month | 3month | 6month | 12month"),
    "LASTFM_LIMIT": ("1024", "How many of your most played albums to import (0 = all of them)"),
    "TMDB_API_KEY": ("", "Fallback posters + genres/countries/creators for shows & movies"),
    "SPOTIFY_CLIENT_ID": ("", "https://developer.spotify.com/dashboard -> your app's Client ID"),
    "SPOTIFY_CLIENT_SECRET": ("", "https://developer.spotify.com/dashboard -> your app's Client secret"),
    "SPOTIFY_LIKED": ("false", "true = albums of your liked songs are imported when you sync from your Spotify account"),
    "SPOTIFY_PLAYLISTS": ("false", "true = albums of your playlists are imported when you sync from your Spotify account"),
    "SPOTIFY_TOP": ("true", "true = albums of your top songs (Spotify's own ranking of what you play most) are imported when you sync from your Spotify account"),
    "SPOTIFY_MIN_SONGS": ("1", "Songs an album needs in top songs / liked songs / playlists to be imported by an account sync (saved albums always count). The file import has its own setting"),
}


def parse_env(path: Path = ENV_PATH) -> dict:
    out = {}
    if path.is_file():
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            out[k.strip()] = v
    return out


class Config:
    def __init__(self):
        self.reload()

    def reload(self):
        file_vals = parse_env()
        legacy = file_vals.get("ONLY_DOWNLOADED", os.environ.get("ONLY_DOWNLOADED", "false"))   # one flag for both, before it was split
        self.values = {k: file_vals.get(k, os.environ.get(k, legacy if k.endswith("_ONLY_DOWNLOADED") else d)) for k, (d, _) in KEYS.items()}

    def get(self, key: str) -> str:
        return (self.values.get(key) or "").strip()

    def flag(self, key: str) -> bool:
        return self.get(key).lower() in ("1", "true", "yes", "on")

    def integer(self, key: str, fallback: int) -> int:
        try:
            return int(self.get(key))
        except ValueError:
            return fallback

    def save(self, new_values: dict):
        """Update keys in .env, keeping comments and unknown lines."""
        self.values.update({k: str(v).strip() for k, v in new_values.items()})
        lines = ENV_PATH.read_text(encoding="utf-8-sig").splitlines() if ENV_PATH.is_file() else []
        done = set()
        for i, raw in enumerate(lines):
            s = raw.strip()
            if s and not s.startswith("#") and "=" in s:
                k = s.split("=", 1)[0].strip()
                if k in KEYS:
                    lines[i] = f"{k}={self.values[k]}"
                    done.add(k)
        for k in KEYS:
            if k not in done:
                lines += [f"# {KEYS[k][1]}", f"{k}={self.values[k]}"]
        ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    sonarr_ready = property(lambda self: bool(self.get("SONARR_URL") and self.get("SONARR_API_KEY")))
    radarr_ready = property(lambda self: bool(self.get("RADARR_URL") and self.get("RADARR_API_KEY")))
    trakt_ready = property(lambda self: bool(self.get("TRAKT_CLIENT_ID") and self.get("TRAKT_USER")))
    lastfm_ready = property(lambda self: bool(self.get("LASTFM_API_KEY") and self.get("LASTFM_USER")))
    tmdb_ready = property(lambda self: bool(self.get("TMDB_API_KEY")))
    spotify_ready = property(lambda self: bool(self.get("SPOTIFY_CLIENT_ID") and self.get("SPOTIFY_CLIENT_SECRET")))


def ensure_dirs():
    for d in (OUTPUT_DIR, *(kind_dir(k) / "posters" for k in KIND_NAMES)):
        d.mkdir(parents=True, exist_ok=True)
    from .jsonstore import migrate_txt
    migrate_txt(DATA_DIR, KIND_NAMES)                 # old txt data files become JSON (once)

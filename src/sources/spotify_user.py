"""Spotify with your own login (authorization code flow with PKCE): reads your saved albums, liked songs and playlists
straight from your account, so no data export is needed.

It uses the Client ID of your own Spotify app (no secret is sent). The app needs the redirect address (REDIRECT_URI, or SPOTIFY_REDIRECT_URI) among its redirect URIs. The
login is kept in data/spotify_auth.json (a refresh token: it stays on your computer, and only goes into an export when you tick
"Include settings")."""
import base64
import hashlib
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from ..core.config import SPOTIFY_AUTH_PATH
from ..core.jsonstore import read_json, write_json
from . import spotify_api
from .http import TIMEOUT

PORT = 8765
REDIRECT_URI = f"http://127.0.0.1:{PORT}/callback"                 # the default; SPOTIFY_REDIRECT_URI can change it
SCOPES = "user-library-read playlist-read-private playlist-read-collaborative user-top-read"
AUTH_URL = "https://accounts.spotify.com/authorize"
API = "https://api.spotify.com/v1"
AUTH_FILE = SPOTIFY_AUTH_PATH
_access = {"value": None, "until": 0.0}
_lock = threading.Lock()
notice = lambda text: None                          # where waits are reported (library() points it at the sync log)


class NotSignedIn(RuntimeError):
    pass


def redirect(cfg) -> str:
    return cfg.get("SPOTIFY_REDIRECT_URI") or REDIRECT_URI


def listen_on(uri):
    """(host, port, path) the local sign-in server must answer on for a redirect address. Only a plain http address on this
    computer works, because Patchwork itself catches the answer."""
    u = urlparse(uri)
    try:
        port = u.port
    except ValueError:
        port = None
    if u.scheme != "http" or u.hostname not in ("127.0.0.1", "localhost") or not port:
        raise RuntimeError("The redirect address must look like http://127.0.0.1:8765/callback "
                           "(http, 127.0.0.1 or localhost, and a port)")
    return u.hostname, port, u.path or "/"


# ---------------------------------------------------------------- login state
def _saved(cfg) -> dict:
    data = read_json(AUTH_FILE, {})
    return data if data.get("refresh_token") and data.get("client_id") == cfg.get("SPOTIFY_CLIENT_ID") else {}


def signed_in(cfg) -> bool:
    return bool(_saved(cfg))


def user_name(cfg) -> str:
    """Who is signed in ('' when nobody is; a login made with another Client ID does not count)."""
    return _saved(cfg).get("name") or ("Spotify user" if _saved(cfg) else "")


def sign_out():
    try:
        AUTH_FILE.unlink()
    except OSError:
        pass
    _access.update(value=None, until=0.0)


def _store(cfg, refresh_token, name=None):
    data = read_json(AUTH_FILE, {})
    data.update(refresh_token=refresh_token, client_id=cfg.get("SPOTIFY_CLIENT_ID"))
    if name:
        data["name"] = name
    write_json(AUTH_FILE, data)


# ---------------------------------------------------------------- login
class _Catcher(BaseHTTPRequestHandler):
    result = None
    path_wanted = "/callback"

    def do_GET(self):
        q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        if urlparse(self.path).path != type(self).path_wanted:
            self.send_response(404)
            self.end_headers()
            return
        type(self).result = q
        body = ("<html><body style='font-family:sans-serif;background:#12141c;color:#e6e8f0;text-align:center;padding-top:80px'>"
                "<h2>Patchwork is connected to Spotify</h2><p>You can close this tab.</p></body></html>" if "code" in q else
                "<html><body style='font-family:sans-serif;text-align:center;padding-top:80px'><h2>Spotify sign-in failed</h2>"
                "<p>You can close this tab and try again in Patchwork.</p></body></html>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def sign_in(cfg, cancel=None, timeout=180) -> str:
    """Opens the Spotify login in the browser, waits for the answer on the local redirect address and stores the login.
    Returns the account's name. Raises with a readable message when it fails or `cancel` (an Event) is set."""
    cid = cfg.get("SPOTIFY_CLIENT_ID")
    if not cid:
        raise RuntimeError("Client ID is needed")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    uri = redirect(cfg)
    host, port, _Catcher.path_wanted = listen_on(uri)
    _Catcher.result = None
    try:
        server = HTTPServer((host, port), _Catcher)
    except OSError:
        raise RuntimeError(f"Port {port} is in use, close whatever uses it and try again")
    server.timeout = 0.4
    try:
        webbrowser.open(AUTH_URL + "?" + urlencode({"client_id": cid, "response_type": "code", "redirect_uri": uri,
                                                    "scope": SCOPES, "state": state, "code_challenge_method": "S256",
                                                    "code_challenge": challenge}))
        end = time.time() + timeout
        while _Catcher.result is None and time.time() < end and not (cancel and cancel.is_set()):
            server.handle_request()
    finally:
        server.server_close()
    got = _Catcher.result
    if cancel and cancel.is_set():
        raise RuntimeError("cancelled")
    if got is None:
        raise RuntimeError("No answer from Spotify (timed out)")
    if got.get("state") != state or "code" not in got:
        raise RuntimeError("Spotify refused the login" + (f": {got['error']}" if got.get("error") else ""))
    r = spotify_api.session.post(spotify_api.TOKEN_URL, timeout=TIMEOUT, data={
        "grant_type": "authorization_code", "code": got["code"], "redirect_uri": uri, "client_id": cid,
        "code_verifier": verifier})
    if r.status_code >= 400:
        raise RuntimeError("Spotify did not accept the login (check the redirect address of your app)")
    data = r.json()
    _store(cfg, data["refresh_token"])
    with _lock:
        _access.update(value=data["access_token"], until=time.time() + int(data.get("expires_in", 3600)) - 60)
    name = ""
    try:
        me = _get(cfg, "/me").json()
        name = me.get("display_name") or me.get("id") or ""
    except Exception:
        pass
    _store(cfg, data["refresh_token"], name or "Spotify user")
    return name or "Spotify user"


def _token(cfg) -> str:
    with _lock:
        if _access["value"] and time.time() < _access["until"]:
            return _access["value"]
        saved = _saved(cfg)
        if not saved:
            raise NotSignedIn("Not signed in to Spotify")
        r = spotify_api.session.post(spotify_api.TOKEN_URL, timeout=TIMEOUT, data={
            "grant_type": "refresh_token", "refresh_token": saved["refresh_token"], "client_id": saved["client_id"]})
        if r.status_code in (400, 401):
            sign_out()
            raise NotSignedIn("The Spotify login expired, sign in again in Settings")
        r.raise_for_status()
        data = r.json()
        if data.get("refresh_token"):
            _store(cfg, data["refresh_token"])
        _access.update(value=data["access_token"], until=time.time() + int(data.get("expires_in", 3600)) - 60)
        return _access["value"]


# ---------------------------------------------------------------- reading the account
def _get(cfg, path, **params):
    """One API request (path like '/me/albums' or a full next-page url), waiting out short rate limits."""
    url = path if path.startswith("http") else API + path
    for _ in range(4):
        if spotify_api.should_stop():
            raise RuntimeError("cancelled")
        r = spotify_api.session.get(url, params=params or None, headers={"Authorization": "Bearer " + _token(cfg)}, timeout=TIMEOUT)
        if r.status_code == 429:
            pause = int(r.headers.get("Retry-After", "2") or 2)
            if pause > 30:
                raise RuntimeError(f"Spotify rate limit reached (retry after {pause} s)")
            notice(f"[Spotify] rate limited, waiting {pause + 1} s...")
            spotify_api._sleep(pause + 1)
            continue
        r.raise_for_status()
        return r
    raise RuntimeError("Spotify keeps rate limiting, try again later")


TOP_DEPTH = 1000          # Spotify ranks tens of thousands of songs for the top list; only the first ones say anything


def _pages(cfg, path, on_page=None, cap=None, **params):
    """Every item of a paged list (the first `cap` of them when given). on_page(items so far, total) is called after each page
    (total can be None)."""
    url, count = path, 0
    for _ in range(1000):                                 # a guard: never page forever
        if not url or (cap and count >= cap):
            return
        data = _get(cfg, url, **params).json()
        items = data.get("items") or []
        count += len(items)
        yield from items
        if on_page:
            on_page(count, min(data.get("total") or 0, cap) if cap and data.get("total") else data.get("total"))
        url, params = (data.get("next") if items else None), {}


facts = {}                                            # (artist, album) -> what Spotify said about it while library() read it (see _album_key)


def _album_key(album):
    artists = album.get("artists") or []
    artist, name = (artists[0].get("name") if artists else "") or "", album.get("name") or ""
    if not (artist.strip() and name.strip()):
        return None
    key = (artist.strip(), name.strip())
    if album.get("id") and key not in facts:              # every album object read passes here: keep its ids and type (no extra request)
        facts[key] = {"album": album["id"], "artist": artists[0].get("id"), "type": album.get("album_type"), "tracks": album.get("total_tracks")}
    return key


def library(cfg, liked=True, playlists=True, top=True, log=print, progress=None):
    """-> (saved, liked, playlists, top): the first three in the shape spotify.read gives for the export files,
    saved = {(artist, album): uri}; liked / playlists / top = {(artist, album): {track ids}}."""
    global notice
    facts.clear()
    saved, lk, pl, tp = {}, {}, {}, {}
    progress = progress or (lambda done, total: None)
    notice = log
    log("[Spotify] reading saved albums...")

    def reporter(what, every=0):
        """Moves the progress bar with the pages read and (optionally) logs every `every` items."""
        last = [0]

        def on_page(count, total):
            if total:
                progress(count, total)
            if every and total and count - last[0] >= every and count < total:
                last[0] = count
                log(f"[Spotify] {what}: {count}/{total}")
        return on_page

    for item in _pages(cfg, "/me/albums", reporter("saved albums", 500), limit=50):
        key = _album_key(item.get("album") or {})
        if key:
            saved[key] = (item.get("album") or {}).get("uri") or ""
    log(f"[Spotify] {len(saved)} saved albums")
    if liked:
        log("[Spotify] reading liked songs...")
        for item in _pages(cfg, "/me/tracks", reporter("liked songs", 2000), limit=50):
            t = item.get("track") or {}
            key = _album_key(t.get("album") or {})
            if key:
                lk.setdefault(key, set()).add(t.get("uri") or t.get("id"))
        log(f"[Spotify] {len(lk)} albums in liked songs")
    if top:
        log("[Spotify] reading top songs...")
        for span in ("long_term", "medium_term", "short_term"):
            try:
                n = 0
                for t in _pages(cfg, "/me/top/tracks", reporter(f"top songs ({span.split('_')[0]} term)", 500), cap=TOP_DEPTH, limit=50, time_range=span):
                    n += 1
                    key = _album_key((t or {}).get("album") or {})
                    if key:
                        tp.setdefault(key, set()).add(t.get("uri") or t.get("id"))
                log(f"[Spotify] top songs ({span.split('_')[0]} term): {n}")
            except Exception as e:
                if "cancelled" in str(e):
                    raise
                log("[Spotify] top songs skipped" + (" (sign in again to allow it)" if "403" in str(e) else f": {e}"))
                break
        log(f"[Spotify] {len(tp)} albums in top songs")
    if playlists:
        log("[Spotify] reading playlists...")
        lists = [p for p in _pages(cfg, "/me/playlists", limit=50) if p and p.get("id")]
        log(f"[Spotify] {len(lists)} playlists to read")
        for i, p in enumerate(lists, 1):
            progress(i, len(lists))
            try:
                for item in _items(cfg, p["id"]):
                    t = item.get("track") or item.get("item") or {}
                    if not t or item.get("is_local") or t.get("is_local") or t.get("type") not in (None, "track"):
                        continue
                    key = _album_key(t.get("album") or {})
                    if key:
                        pl.setdefault(key, set()).add(t.get("uri") or t.get("id"))
            except Exception as e:                       # e.g. a playlist of someone else that Spotify does not let this app read
                if "cancelled" in str(e):
                    raise
                log(f"[Spotify] skipped playlist {p.get('name')}: {e}")
        log(f"[Spotify] {len(pl)} albums in {len(lists)} playlists")
    return saved, lk, pl, tp


def _items(cfg, playlist_id):
    """The tracks of a playlist; Spotify is moving this endpoint from /tracks to /items, so the other one is tried when needed."""
    for suffix in ("tracks", "items"):
        try:
            yield from _pages(cfg, f"/playlists/{playlist_id}/{suffix}", limit=100)
            return
        except Exception as e:
            if suffix == "items" or "404" not in str(e) and "410" not in str(e):
                raise

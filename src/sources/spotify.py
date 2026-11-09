"""Spotify data export (YourLibrary.json, Playlist*.json) -> albums.

Saved albums are always imported. Albums only known through single songs are imported when at least `min_tracks`
different songs of them are in your liked songs / playlists, so one-off songs don't flood the list."""
import json
from pathlib import Path

from .entry import Entry


def _load(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return json.load(f)


def read(paths):
    """-> (saved, liked, playlists): saved = {(artist, album): uri}; liked / playlists = {(artist, album): {track ids}}."""
    saved, liked, playlists = {}, {}, {}

    def add(target, artist, album, track_id):
        if artist and album:
            target.setdefault((artist.strip(), album.strip()), set()).add(track_id)

    for path in paths:
        data = _load(path)
        if not isinstance(data, dict):
            continue
        for a in data.get("albums") or []:
            if a.get("artist") and a.get("album"):
                saved[(a["artist"].strip(), a["album"].strip())] = a.get("uri") or ""
        for t in data.get("tracks") or []:
            add(liked, t.get("artist"), t.get("album"), t.get("uri") or t.get("track"))
        for pl in data.get("playlists") or []:
            for item in pl.get("items") or []:
                t = (item or {}).get("track") or {}
                if t and not (item.get("localTrack")):
                    add(playlists, t.get("artistName"), t.get("albumName"), t.get("trackUri") or t.get("trackName"))
    return saved, liked, playlists


def entries(paths, liked=True, playlists=True, min_tracks=3) -> list:
    return entries_from(*read([Path(p) for p in paths]), liked=liked, playlists=playlists, min_tracks=min_tracks)


def entries_from(saved, lk, pl, liked=True, playlists=True, min_tracks=3, top=None) -> list:
    """The albums to import out of what read() or spotify_user.library() found."""
    tracks = {}
    for use, src in ((liked, lk), (playlists, pl), (bool(top), top or {})):
        if use:
            for key, ids in src.items():
                tracks.setdefault(key, set()).update(ids)
    keys = set(saved) | {k for k, ids in tracks.items() if len(ids) >= max(1, min_tracks)}
    out = []
    for artist, album in sorted(keys, key=lambda k: (k[0].casefold(), k[1].casefold())):
        meta = dict(title=album, creators=artist, spotify_tracks=len(tracks.get((artist, album), ())))
        if saved.get((artist, album)):
            meta["ids"] = {"spotify": saved[(artist, album)]}
        out.append(Entry(f"{artist} - {album}", meta, None, album=album))
    return out

"""TMDB: poster fallback and rich details (genres, countries, languages, creators/director, ids)."""
from .http import TIMEOUT, session
from .lookups import country, language, split_movie_label

API = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p/w780"


def _path(kind):
    return "tv" if kind == "shows" else "movie"


def find(key, kind, label):
    """Best search hit (a dict with id and poster_path) or None."""
    q, year = split_movie_label(label) if kind == "movies" else (label, None)
    params = {"api_key": key, "query": q, **({"year": year} if year else {})}
    res = session.get(f"{API}/search/{_path(kind)}", params=params, timeout=TIMEOUT).json().get("results") or []
    return res[0] if res else None


def find_id(key, kind, label):
    hit = find(key, kind, label)
    return hit["id"] if hit else None


def poster_url(key, kind, label, tmdb_id=None):
    """(poster url or None, tmdb id or None). A search hit already carries its poster, so a new title costs one request."""
    try:
        if not tmdb_id:
            hit = find(key, kind, label)
            if not hit:
                return None, None
            return (IMG + hit["poster_path"] if hit.get("poster_path") else None), hit["id"]
        d = session.get(f"{API}/{_path(kind)}/{tmdb_id}", params={"api_key": key}, timeout=TIMEOUT).json()
        return (IMG + d["poster_path"] if d.get("poster_path") else None), tmdb_id
    except Exception:
        return None, tmdb_id


def details(key, kind, label, tmdb_id=None) -> dict:
    """Meta dict (empty when nothing was found)."""
    try:
        tmdb_id = tmdb_id or find_id(key, kind, label)
        if not tmdb_id:
            return {"tmdb_checked": True}                 # nothing on TMDB: do not ask again on every sync
        d = session.get(f"{API}/{_path(kind)}/{tmdb_id}", timeout=TIMEOUT,
                        params={"api_key": key, "append_to_response": "external_ids,credits"}).json()
        langs = [l.get("english_name") for l in d.get("spoken_languages", [])]
        if d.get("original_language"):
            langs.append(language(d["original_language"]))
        if kind == "shows":
            ext = d.get("external_ids") or {}
            countries = [country(c) for c in d.get("origin_country", [])]
            creators = [c["name"] for c in d.get("created_by", [])]
            studio = (d.get("networks") or [{}])[0].get("name")
            year = (d.get("first_air_date") or "")[:4]
            ids = dict(tmdb=tmdb_id, imdb=ext.get("imdb_id"), tvdb=ext.get("tvdb_id"))
        else:
            countries = [c["name"] for c in d.get("production_countries", [])]
            creators = [c["name"] for c in (d.get("credits") or {}).get("crew", []) if c.get("job") == "Director"]
            studio = (d.get("production_companies") or [{}])[0].get("name")
            year = (d.get("release_date") or "")[:4]
            ids = dict(tmdb=tmdb_id, imdb=d.get("imdb_id"))
        return dict(genres=[g["name"] for g in d.get("genres", [])], countries=countries, languages=langs,
                    creators=creators, studio=studio, year=int(year) if year.isdigit() else None,
                    overview=d.get("overview"), rating=d.get("vote_average") or None, ids=ids)
    except Exception:
        return {}

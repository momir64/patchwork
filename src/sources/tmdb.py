"""TMDB: poster fallback and rich details (genres, countries, languages, creators/director, ids)."""
from .http import TIMEOUT, session
from .lookups import country, language, split_movie_label

API = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p/w780"


def _path(kind):
    return "tv" if kind == "shows" else "movie"


def find_id(key, kind, label):
    q, year = split_movie_label(label) if kind == "movies" else (label, None)
    params = {"api_key": key, "query": q, **({"year": year} if year else {})}
    res = session.get(f"{API}/search/{_path(kind)}", params=params, timeout=TIMEOUT).json().get("results") or []
    return res[0]["id"] if res else None


def poster_url(key, kind, label, tmdb_id=None):
    try:
        tmdb_id = tmdb_id or find_id(key, kind, label)
        if not tmdb_id:
            return None
        d = session.get(f"{API}/{_path(kind)}/{tmdb_id}", params={"api_key": key}, timeout=TIMEOUT).json()
        return IMG + d["poster_path"] if d.get("poster_path") else None
    except Exception:
        return None


def details(key, kind, label, tmdb_id=None) -> dict:
    """Meta dict (empty when nothing was found)."""
    try:
        tmdb_id = tmdb_id or find_id(key, kind, label)
        if not tmdb_id:
            return {}
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

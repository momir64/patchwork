"""Trakt: everything you watched / rated (public profile, only a Client ID is needed)."""
from .entry import Entry
from .http import TIMEOUT, session
from .lookups import country, language, movie_label, title_case


class Trakt:
    def __init__(self, client_id, user):
        self.user = user
        self.headers = {"trakt-api-version": "2", "trakt-api-key": client_id, "Content-Type": "application/json"}

    def get(self, path):
        r = session.get(f"https://api.trakt.tv{path}", headers=self.headers, timeout=TIMEOUT)
        if r.status_code in (401, 403):
            raise RuntimeError("Trakt refused access - check the Client ID and that the profile is public")
        if r.status_code == 404:
            raise RuntimeError(f"Trakt user '{self.user}' not found")
        r.raise_for_status()
        return r.json() if r.content else None

    def check(self):
        if self.get(f"/users/{self.user}/watched/shows") is None:
            raise RuntimeError("Trakt returned no data - is the profile public, and is the username the slug in your profile URL?")

    def pages(self, path, limit=1000, on_page=None):
        """Paginated endpoint (history can be thousands of entries)."""
        page = 1
        while True:
            r = session.get(f"https://api.trakt.tv{path}?limit={limit}&page={page}", headers=self.headers, timeout=60)
            r.raise_for_status()
            data = r.json() if r.content else []
            yield from data
            count = int(r.headers.get("X-Pagination-Page-Count", 1))
            if on_page:
                on_page(page, count)
            if not data or page >= count:
                return
            page += 1

    def collect(self, kind, progress=None):
        """kind 'shows'|'movies' -> (entries, ratings{label: 1-10}).

        Trakt's 'watched' summary is sometimes stale, so the full play history is the main source;
        watched / collection / ratings are merged in as well."""
        single = "show" if kind == "shows" else "movie"
        entries = {}

        def put(o):
            label = o["title"] if single == "show" else movie_label(o["title"], o.get("year"))
            ids = o.get("ids") or {}
            meta = dict(title=o["title"], year=o.get("year"), genres=[title_case(g) for g in o.get("genres") or []],
                        countries=country(o["country"]) if o.get("country") else None,
                        languages=language(o["language"]) if o.get("language") else None,
                        studio=o.get("network"), overview=o.get("overview"), rating=o.get("rating"),
                        ids=dict(trakt=ids.get("trakt"), slug=ids.get("slug"), tmdb=ids.get("tmdb"),
                                 imdb=ids.get("imdb"), tvdb=ids.get("tvdb")))
            entries.setdefault(label, Entry(label, meta, tmdb_id=ids.get("tmdb")))
            return label

        u, hist = self.user, [1]                  # hist: number of history pages (known after the first one); 3 more requests follow

        def step(done):
            if progress:
                progress(done, hist[0] + 3)

        def on_page(page, count):
            hist[0] = count
            step(page)

        watchlist = {(it[single].get("ids") or {}).get("trakt") for it in self.get(f"/users/{u}/watchlist/{kind}") or []}
        watched = set()                                       # titles you actually watched; the watchlist (still to watch) never adds one

        def seen(o):
            watched.add((o.get("ids") or {}).get("trakt"))
            return put(o)

        for it in self.pages(f"/users/{u}/history/{'episodes' if kind == 'shows' else 'movies'}", on_page=on_page):
            seen(it[single])
        for n, src in enumerate(("watched", "collection"), 1):
            for it in self.get(f"/users/{u}/{src}/{kind}?extended=full") or []:
                o = it[single]
                tid = (o.get("ids") or {}).get("trakt")
                if src == "collection" and tid in watchlist and tid not in watched:
                    continue                                  # collected, but only on your watchlist: not watched yet
                (seen if src == "watched" else put)(o)
            step(hist[0] + n)
        ratings = {}
        for it in self.get(f"/users/{u}/ratings/{kind}?extended=full") or []:
            ratings[put(it[single])] = it.get("rating", 0)
        step(hist[0] + 3)
        return list(entries.values()), ratings

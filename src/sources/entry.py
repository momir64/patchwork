"""What every connector returns: one media item as found at the source."""
from dataclasses import dataclass, field


@dataclass
class Entry:
    title: str                      # label as it appears in the list ("Title (Year)" for movies)
    meta: dict = field(default_factory=dict)
    poster: str | None = None       # image url, if the source has one
    poster_headers: dict | None = None
    tmdb_id: int | None = None
    album: str | None = None        # albums: name without artist (to upgrade old artist-less entries)
    label: str = ""                 # filled in by Sync once the entry is in the library

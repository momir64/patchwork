"""Helpers for turning titles into file names and into comparable keys."""
import re
import unicodedata
from functools import lru_cache

_BAD_CHARS = re.compile(r'[<>"/\|?*\x00-\x1f]')


def safe_filename(label: str) -> str:
    """File-system safe name. ':' becomes ' -' (same convention as the old scripts)."""
    s = label.replace(":", " -")
    s = _BAD_CHARS.sub("-", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s or "_"


@lru_cache(maxsize=None)
def norm_key(label: str) -> str:
    """Loose comparison key: 'Avatar: The Last Airbender' == 'Avatar - The Last Airbender'."""
    s = unicodedata.normalize("NFKD", label.casefold())
    return "".join(c for c in s if c.isalnum())


def sort_key(label: str):
    return (label.casefold(), label)

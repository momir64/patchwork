"""Helpers for turning titles into file names and into comparable keys."""
import hashlib
import re
import unicodedata
from functools import lru_cache

_BAD_CHARS = re.compile(r'[<>"/\\|?*\x00-\x1f]')           # includes the backslash, which would otherwise start a sub-folder


def safe_filename(label: str) -> str:
    """File-system safe name. ':' becomes ' -' (same convention as the old scripts)."""
    s = label.replace(":", " -")
    s = _BAD_CHARS.sub("-", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    if len(s) > 110:                                           # Windows refuses very long paths: shorten, keep it unique
        s = s[:100].rstrip(" .") + "~" + hashlib.md5(label.encode("utf-8")).hexdigest()[:8]
    return s or "_"


@lru_cache(maxsize=None)
def norm_key(label: str) -> str:
    """Loose comparison key: 'Avatar: The Last Airbender' == 'Avatar - The Last Airbender'."""
    s = unicodedata.normalize("NFKD", label.casefold())
    return "".join(c for c in s if c.isalnum())


def sort_key(label: str):
    return (label.casefold(), label)

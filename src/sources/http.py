"""Shared HTTP session and image download helper."""
import io

import requests
from PIL import Image

TIMEOUT = 25
session = requests.Session()
session.headers["User-Agent"] = "patchwork/1.0"


def base_url(url: str) -> str:
    url = url.strip().rstrip("/")
    return url if url.startswith("http") else "http://" + url


def download_image(url: str, headers=None):
    """Returns (bytes, extension), or None when the URL does not deliver a valid image."""
    try:
        r = session.get(url, headers=headers, timeout=TIMEOUT)
        r.raise_for_status()
        im = Image.open(io.BytesIO(r.content))
        fmt = im.format
        im.verify()
        ext = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}.get(fmt)
        return (r.content, ext) if ext else None
    except Exception:
        return None

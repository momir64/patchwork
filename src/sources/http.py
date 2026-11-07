"""Shared HTTP session and image download helper."""
import io

import requests
from PIL import Image
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

TIMEOUT = 25
session = requests.Session()
session.headers["User-Agent"] = "patchwork/1.0"
# more pooled connections than worker threads (so none wait for a free one), and a polite retry on rate limits / server hiccups
_adapter = HTTPAdapter(pool_connections=16, pool_maxsize=32,
                       max_retries=Retry(total=2, backoff_factor=0.6, status_forcelist=(429, 500, 502, 503, 504), respect_retry_after_header=True))
session.mount("https://", _adapter)
session.mount("http://", _adapter)


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

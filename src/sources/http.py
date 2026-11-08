"""Shared HTTP session and image download helper."""
import io
import threading
from concurrent.futures import Future

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


_once_lock = threading.Lock()


def once(cache: dict, key, fetch):
    """The result of fetch() for this key, asked only once: later (or simultaneous) callers get the same answer instead of
    sending the same request again. A failure is not remembered, so it is tried again next time."""
    with _once_lock:
        future = cache.get(key)
        owner = future is None
        if owner:
            future = cache[key] = Future()
    if owner:
        try:
            future.set_result(fetch())
        except Exception as e:
            future.set_exception(e)
            with _once_lock:
                cache.pop(key, None)
    return future.result()


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

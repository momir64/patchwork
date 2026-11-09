"""Shared GUI helpers: background jobs and thumbnail loading."""
import time
from collections import OrderedDict

from PIL import Image
from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, Signal
from PySide6.QtGui import QImage, QPixmap


def pil_to_qimage(img: Image.Image) -> QImage:
    img = img.convert("RGB")
    return QImage(img.tobytes(), img.width, img.height, 3 * img.width, QImage.Format.Format_RGB888).copy()


class Cancelled(Exception):
    pass


class Job(QThread):
    """Runs fn(progress_cb) in a thread. Keep a reference while running."""
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn
        self.cancelled, self._last_emit = False, 0.0

    def cancel(self):
        """Stop at the next progress report; neither done nor failed is emitted."""
        self.cancelled = True

    def _progress(self, a, b):
        if self.cancelled:
            raise Cancelled()
        now = time.monotonic()
        if a >= b or now - self._last_emit >= 0.05:          # frequent callers (every item) do not flood the interface
            self._last_emit = now
            self.progress.emit(a, b)

    def run(self):
        try:
            res = self.fn(self._progress)
            if not self.cancelled:
                self.done.emit(res)
        except Cancelled:
            pass
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")


class _Task(QRunnable):
    def __init__(self, loader, key):
        super().__init__()
        self.loader, self.key = loader, key

    def run(self):
        img = QImage()
        try:
            with Image.open(self.key) as im:
                im.draft("RGB", (440, 660))
                im = im.convert("RGB")
                im.thumbnail((220, 330), Image.Resampling.LANCZOS)
                img = pil_to_qimage(im)
        except Exception:
            pass
        try:
            self.loader._ready.emit(self.key, img)
        except RuntimeError:
            pass                                  # the window was closed while this thumbnail was loading


class ThumbLoader(QObject):
    loaded = Signal(str)
    _ready = Signal(str, QImage)

    def __init__(self, limit=700):
        super().__init__()
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(6)
        self.cache, self.pending, self.limit = OrderedDict(), set(), limit
        self._ready.connect(self._store)

    def get(self, path):
        key = str(path)
        pm = self.cache.get(key)
        if pm is not None:
            self.cache.move_to_end(key)
            return pm
        if key not in self.pending:
            self.pending.add(key)
            self.pool.start(_Task(self, key))
        return None

    def invalidate(self, path):
        self.cache.pop(str(path), None)

    def _store(self, key, img):
        self.pending.discard(key)
        self.cache[key] = QPixmap.fromImage(img)
        while len(self.cache) > self.limit:
            self.cache.popitem(last=False)
        self.loaded.emit(key)

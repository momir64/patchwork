"""Dialogs: granular Sync, Settings (.env editor + data export/import) and the activity log."""
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QLineEdit,
                               QListWidget, QPlainTextEdit, QRadioButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from ..core import editions, transfer
from ..core.library import KINDS, Library, add_alias, title_from_label
from ..sources import Sync
from ..core.config import ENV_PATH, KEYS
from ..sources import test_connection
from ..sources.sync import KINDS, SOURCES, STEPS
from . import theme
from .chrome import Modal, notify
from .common import Job
from .widgets import FlowLayout, UnitSpin, button, label


def card(title=None, hint=None, divider=True):
    """A flat section (no box): thin divider, bold title, dim hint. Returns (widget, layout) - add rows to the layout."""
    f = QWidget()
    v = QVBoxLayout(f)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(10)
    if divider:
        line = QFrame()
        line.setObjectName("divider")
        v.addWidget(line)
        v.addSpacing(4)
    if title:
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(label(title, "cardtitle"))
        short = bool(hint) and len(hint) <= 40
        if short:
            head.addWidget(label(hint, "dim"), 1)
        else:
            head.addStretch()
        v.addLayout(head)
        if hint and not short:
            v.addWidget(label(hint, "dim", wrap=True))
        v.addSpacing(14)                      # air between the heading and its fields
    return f, v


def check_row(box: QCheckBox, desc=None) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(12)
    row.addWidget(box)
    if desc:
        d = label(desc, "dim")
        d.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(d, 1)
    else:
        row.addStretch()
    return row


# ====================================================================== sync
SOURCE_INFO = {  # key -> (title, description, config check)
    "sonarr": ("Sonarr", "TV shows from your Sonarr library", lambda c: c.sonarr_ready),
    "radarr": ("Radarr", "Movies from your Radarr library", lambda c: c.radarr_ready),
    "trakt_shows": ("Trakt - shows", "Watch history, collection, ratings", lambda c: c.trakt_ready),
    "trakt_movies": ("Trakt - movies", "Watch history, collection, ratings", lambda c: c.trakt_ready),
    "lastfm": ("Last.fm", "Your top albums", lambda c: c.lastfm_ready),
}
STEP_INFO = {
    "titles": ("Add new titles", "Never deletes anything"),
    "posters": ("Download missing posters", "Only titles without one"),
    "metadata": ("Fetch missing metadata", "Albums: MusicBrainz, ~1 artist/s"),
}
KIND_NAMES = {"shows": "Shows", "movies": "Movies", "albums": "Albums"}
DEFAULT_SYNC = {"sources": list(SOURCES), "steps": list(STEPS), "kinds": list(KINDS), "force_meta": False}


class SyncDialog(Modal):
    """Pick sources, steps and media types. Returns the choice via .choice after exec()."""

    def __init__(self, cfg, choice, parent=None):
        super().__init__(parent, "Sync", 560)
        self.choice = None
        self.boxes = {"sources": {}, "steps": {}, "kinds": {}}
        self.body.addWidget(label("Choose exactly what to update. Your selection is remembered for the Sync button.", "muted", wrap=True))

        f, v = card("Sources", divider=False)
        for key, (title, desc, ready) in SOURCE_INFO.items():
            ok = ready(cfg)
            cb = QCheckBox(title + ("" if ok else "  (not configured)"))
            cb.setChecked(ok and key in choice["sources"])
            cb.setEnabled(ok)
            self.boxes["sources"][key] = cb
            v.addLayout(check_row(cb, desc))
        self.body.addWidget(f)

        f, v = card("What to do")
        for key, (title, desc) in STEP_INFO.items():
            cb = QCheckBox(title)
            cb.setChecked(key in choice["steps"])
            self.boxes["steps"][key] = cb
            v.addLayout(check_row(cb, desc))
        self.force = QCheckBox("Re-fetch metadata even where it already exists")
        self.force.setChecked(choice.get("force_meta", False))
        v.addWidget(self.force)
        self.body.addWidget(f)

        f, v = card("Posters & metadata for")
        row = QHBoxLayout()
        row.setSpacing(22)
        for key in KINDS:
            cb = QCheckBox(KIND_NAMES[key])
            cb.setChecked(key in choice["kinds"])
            self.boxes["kinds"][key] = cb
            row.addWidget(cb)
        row.addStretch()
        v.addLayout(row)
        self.body.addWidget(f)
        self.footer("Start sync", "sync", self.accept_choice)

    def accept_choice(self):
        self.choice = {
            "sources": [k for k, b in self.boxes["sources"].items() if b.isChecked()],
            "steps": [k for k, b in self.boxes["steps"].items() if b.isChecked()],
            "kinds": [k for k, b in self.boxes["kinds"].items() if b.isChecked()],
            "force_meta": self.force.isChecked(),
        }
        self.accept()


# ====================================================================== settings
SECTIONS = (
    ("Sonarr", "Shows library", "sonarr", ("SONARR_URL", "SONARR_API_KEY", "SONARR_ONLY_DOWNLOADED")),
    ("Radarr", "Movies library", "radarr", ("RADARR_URL", "RADARR_API_KEY", "RADARR_ONLY_DOWNLOADED")),
    ("Trakt", "Watch history of a public profile", "trakt", ("TRAKT_CLIENT_ID", "TRAKT_USER", "TRAKT_FAV_MIN_RATING", "TRAKT_SYNC_FAVORITES")),
    ("Last.fm", "Your played albums", "lastfm", ("LASTFM_API_KEY", "LASTFM_USER", "LASTFM_SOURCE", "LASTFM_PERIOD", "LASTFM_LIMIT")),
    ("TMDB", "Posters and details for shows and movies", None, ("TMDB_API_KEY",)),
)
CHECKS = {"SONARR_ONLY_DOWNLOADED": "Skip shows without files", "RADARR_ONLY_DOWNLOADED": "Skip movies without files",
          "TRAKT_SYNC_FAVORITES": "Let Trakt sync change my favorites"}
SOURCES_LF = (("Top albums", "top"), ("Listening history", "recent"))
PERIODS = (("All time", "overall"), ("Last 7 days", "7day"), ("Last month", "1month"), ("Last 3 months", "3month"),
           ("Last 6 months", "6month"), ("Last 12 months", "12month"))
HINTS = {"LASTFM_LIMIT": "",
         "TRAKT_SYNC_FAVORITES": "Off by default. When on, Trakt titles rated at or above the value above become favorites on sync."}
LIMIT_HINTS = {"top": "The most played of your top albums for the period. 0 imports all.",
               "recent": "Plays in your listening history are counted per album over the period; the most played are kept. 0 imports all."}
NICE = {"SONARR_URL": "Address", "SONARR_API_KEY": "API key", "SONARR_ONLY_DOWNLOADED": "Only downloaded", "RADARR_ONLY_DOWNLOADED": "Only downloaded", "LASTFM_SOURCE": "Albums from",
        "RADARR_URL": "Address", "RADARR_API_KEY": "API key", "TRAKT_CLIENT_ID": "Client ID", "TRAKT_USER": "Username",
        "TRAKT_SYNC_FAVORITES": "Trakt sync", "TRAKT_FAV_MIN_RATING": "Favorite if rated ≥", "LASTFM_API_KEY": "API key",
        "LASTFM_USER": "Username", "LASTFM_PERIOD": "Period", "LASTFM_LIMIT": "Albums to import", "TMDB_API_KEY": "API key"}


class SettingsDialog(Modal):
    """Left: list of setting groups. Right: the details of the chosen group."""
    msg = Signal(str)

    def __init__(self, cfg, parent=None):
        super().__init__(parent, "Settings", 800)
        self.cfg, self.fields, self.jobs, self.imported = cfg, {}, [], False
        self.nav, self.stack = QListWidget(), QStackedWidget()
        self.nav.setObjectName("settingsnav")
        self.nav.setFixedWidth(160)
        self.nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)

        self.add_page("Your data", self.data_page())
        for title, desc, test, keys in SECTIONS:
            self.add_page(title, self.section_page(title, desc, test, keys))
        self.add_page("Spotify", self.spotify_page())
        row = QHBoxLayout()
        row.setSpacing(18)
        row.addWidget(self.nav)
        row.addWidget(self.stack, 1)
        self.body.addLayout(row, 1)
        note = label("Saved to .env in the project folder", "dim")
        self.footer("Save", "check", self.save, extra=note)
        self.nav.setCurrentRow(0)
        self.setMinimumSize(620, 440)
        self.resize(840, 600)

    def add_page(self, title, widget):
        self.nav.addItem(title)
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 2, 16, 0)
        v.setSpacing(12)
        v.addWidget(widget)
        v.addStretch()
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sc.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        sc.setWidget(page)
        self.stack.addWidget(sc)

    def data_page(self):
        f, v = card("Your data", None, divider=False)

        def lines(*sentences):
            tight = QVBoxLayout()                     # the lines of one text belong together: almost no space between them
            tight.setSpacing(1)
            tight.setContentsMargins(0, 0, 0, 0)
            for t in sentences:
                tight.addWidget(label(t, "dim", wrap=True))
            v.addLayout(tight)

        def block(title, icon, text, sentences, slot):
            v.addWidget(label(title, "cardtitle"))
            lines(*sentences)
            v.addSpacing(4)
            btn = button(text, icon)
            btn.clicked.connect(slot)
            row = QHBoxLayout()
            row.addWidget(btn)
            row.addStretch()
            v.addLayout(row)
            v.addSpacing(14)

        lines("Back up everything Patchwork knows about your media.", "Or move it to another computer.")
        v.addSpacing(8)
        block("Export", "download", "Export...",
              ("Saves your lists, favorites, metadata, groups and name fixes into one file.",
               "Choose .zip to include the poster images, or .json for the data only."), self.export_data)
        block("Import", "folder", "Import...",
              ("Adds the contents of a file made by Export to your library.",
               "Nothing you already have is deleted or replaced."), self.import_data)
        self.data_msg = label("", "muted", wrap=True)
        v.addWidget(self.data_msg)
        return f

    def spotify_page(self):
        f, v = card("Spotify", "Import albums from your Spotify data export.", divider=False)
        self.sp_files = []

        def step(n, title):
            """A numbered heading; returns the (indented) layout that holds the step's content."""
            head = QHBoxLayout()
            head.setSpacing(10)
            badge = QLabel(str(n))
            badge.setFixedSize(22, 22)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet(f"background: {theme.ACCENT_SOFT}; color: {theme.ACCENT_H}; border-radius: 11px; font-weight: 700;")
            head.addWidget(badge)
            head.addWidget(label(title, "cardtitle"), 1)
            if n > 1:
                v.addSpacing(2)
            v.addLayout(head)
            body = QVBoxLayout()
            body.setSpacing(8)
            body.setContentsMargins(32, 0, 0, 0)
            v.addLayout(body)
            return body

        b = step(1, "Choose your export files")
        pick = button("Choose files...", "folder")
        pick.clicked.connect(self.pick_spotify)
        self.sp_list = label("YourLibrary.json and Playlist*.json", "dim", wrap=True)
        prow = QHBoxLayout()
        prow.setSpacing(12)
        prow.addWidget(pick)
        prow.addWidget(self.sp_list, 1)
        self.sp_clear = button("Clear", "x")
        self.sp_clear.setToolTip("Forget the chosen files")
        self.sp_clear.clicked.connect(self.clear_spotify)
        self.sp_clear.hide()
        prow.addWidget(self.sp_clear)
        b.addLayout(prow)

        b = step(2, "Choose what to import")
        b.addWidget(label("Saved albums are always included. Optionally add the albums of:", "dim", wrap=True))
        self.sp_liked, self.sp_play = QCheckBox("Liked songs"), QCheckBox("Playlists")
        b.addWidget(self.sp_liked)
        b.addWidget(self.sp_play)
        self.sp_min = UnitSpin("songs")
        self.sp_min.setRange(1, 50)
        self.sp_min.setValue(3)
        self.sp_min.setFixedWidth(130)
        mrow = QHBoxLayout()
        mrow.setSpacing(10)
        self.sp_min_lbl = [label("Skip albums with fewer than", "dim"), label("in these lists", "dim")]
        mrow.addWidget(self.sp_min_lbl[0])
        mrow.addWidget(self.sp_min)
        mrow.addWidget(self.sp_min_lbl[1])
        mrow.addStretch()
        b.addLayout(mrow)

        def sync_min():
            on = self.sp_liked.isChecked() or self.sp_play.isChecked()
            self.sp_min.setEnabled(on)
            for l in self.sp_min_lbl:
                l.setEnabled(on)
        self.sp_liked.toggled.connect(sync_min)
        self.sp_play.toggled.connect(sync_min)

        b = step(3, "Then")
        self.sp_covers, self.sp_meta = QCheckBox("Download covers"), QCheckBox("Fetch genres and country")
        b.addWidget(self.sp_covers)
        b.addWidget(self.sp_meta)
        b.addWidget(label("Genres and country are looked up at about 1 artist per second.", "dim", wrap=True))
        for cb in (self.sp_liked, self.sp_play, self.sp_covers):
            cb.setChecked(True)

        self.sp_btn = button("Import albums", "download", "primary")
        self.sp_btn.clicked.connect(self.run_spotify)
        self.sp_out = label("", "muted", wrap=True)
        brow = QHBoxLayout()
        brow.setSpacing(12)
        brow.setContentsMargins(32, 0, 0, 0)
        brow.addWidget(self.sp_btn)
        brow.addWidget(self.sp_out, 1)
        v.addSpacing(16)
        v.addLayout(brow)
        self.msg.connect(lambda m: self.sp_out.setText(m))
        return f

    def pick_spotify(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Spotify export files", "", "Spotify export (*.json)")
        if paths:
            self.sp_files = paths
            self.sp_list.setText(", ".join(Path(p).name for p in paths))
            self.sp_clear.show()

    def clear_spotify(self):
        self.sp_files = []
        self.sp_list.setText("YourLibrary.json and Playlist*.json")
        self.sp_clear.hide()

    def run_spotify(self):
        if not self.sp_files:
            self.sp_out.setText("Choose your Spotify files first.")
            return
        opts = dict(liked=self.sp_liked.isChecked(), playlists=self.sp_play.isChecked(), min_tracks=self.sp_min.value(),
                    posters=self.sp_covers.isChecked(), metadata=self.sp_meta.isChecked())
        files, cfg = list(self.sp_files), self.cfg

        def work(progress):
            libs = {k: Library(k) for k in KINDS}
            return Sync(cfg, libs, log=lambda m: self.msg.emit(m.splitlines()[0][:110]), progress=progress).import_spotify(files, **opts)

        job = Job(work)
        self.sp_btn.setEnabled(False)
        self.sp_out.setText("Importing...")
        job.progress.connect(lambda a, b: self.sp_out.setText(f"{100 * a // max(1, b)}%  ·  working..."))

        def finished(summary):
            self.sp_btn.setEnabled(True)
            self.imported = True
            self.sp_out.setText("Done: " + ", ".join(summary))

        job.done.connect(finished)
        job.failed.connect(lambda m: (self.sp_btn.setEnabled(True), self.sp_out.setText("Failed: " + m)))
        job.finished.connect(lambda: self.jobs.remove(job))
        self.jobs.append(job)
        job.start()

    def section_page(self, title, desc, test, keys):
        cfg = self.cfg
        f, v = card(title, desc, divider=False)
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        for k in keys:
            if k in ("LASTFM_PERIOD", "LASTFM_SOURCE"):
                w = QComboBox()
                for text, val in (PERIODS if k == "LASTFM_PERIOD" else SOURCES_LF):
                    w.addItem(text, val)
                w.setCurrentIndex(max(0, w.findData(cfg.get(k))))
                w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            elif k in CHECKS:
                w = QCheckBox(CHECKS[k])
                w.setMinimumWidth(1)
                w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                w.setChecked(cfg.flag(k))
            else:
                w = QLineEdit(cfg.get(k))
                w.setToolTip(KEYS[k][1])
                if k.endswith(("API_KEY", "CLIENT_ID")):
                    w.setEchoMode(QLineEdit.EchoMode.Password)
            self.fields[k] = w
            lab = QLabel(NICE[k])
            lab.setObjectName("muted")
            lab.setMinimumWidth(140)
            if k == "TRAKT_FAV_MIN_RATING":
                form.addRow(label("Favorites", "cardtitle"))
            if k in HINTS:
                box = QWidget()
                bl = QVBoxLayout(box)
                bl.setContentsMargins(0, 0, 0, 0)
                bl.setSpacing(6)
                bl.addWidget(w)
                hint = label(HINTS[k], "dim", wrap=True)
                bl.addWidget(hint)
                if k == "LASTFM_LIMIT":
                    self.limit_hint = hint
                lab.setFixedHeight(w.sizeHint().height())
                form.addRow(lab, box)
            else:
                form.addRow(lab, w)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        v.addLayout(form)
        if "LASTFM_SOURCE" in keys:
            src = self.fields["LASTFM_SOURCE"]
            src.currentIndexChanged.connect(lambda *_: self.limit_hint.setText(LIMIT_HINTS[src.currentData()]))
            self.limit_hint.setText(LIMIT_HINTS[src.currentData()])
        if "TRAKT_SYNC_FAVORITES" in keys:
            rating, flag = self.fields["TRAKT_FAV_MIN_RATING"], self.fields["TRAKT_SYNC_FAVORITES"]
            rating.setEnabled(flag.isChecked())
            flag.toggled.connect(rating.setEnabled)
        if test:
            v.addSpacing(14)
            out = QLabel("")
            out.setObjectName("muted")
            btn = button("Test connection", "check")
            btn.clicked.connect(lambda _=False, t=test, o=out: self.test(t, o))
            trow = QHBoxLayout()
            trow.setSpacing(12)
            trow.addWidget(btn)
            trow.addWidget(out, 1)
            v.addLayout(trow)
        return f

    def export_data(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export data", "patchwork-export.zip", "With posters (*.zip);;Data only (*.json)")
        if path:
            try:
                transfer.export_data(path, lambda m: None)
                self.data_msg.setText(f"Exported to {path}")
            except Exception as e:
                notify(self, "Export", f"Export failed: {e}")

    def import_data(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import data", "", "Patchwork export (*.zip *.json)")
        if not path:
            return
        try:
            counts = transfer.import_data(path, log=lambda m: None)
        except Exception as e:
            notify(self, "Import", f"Import failed: {e}")
            return
        self.imported = True
        self.data_msg.setText("Imported: " + ", ".join(f"{k} +{c['added']}" for k, c in counts.items()))

    def values(self):
        out = {}
        for k, w in self.fields.items():
            out[k] = (("true" if w.isChecked() else "false") if isinstance(w, QCheckBox)
                      else w.currentData() if isinstance(w, QComboBox) else w.text().strip())
        return out

    def test(self, which, out):
        self.cfg.values.update(self.values())          # test what is typed, not what is saved
        out.setText("testing...")
        job = Job(lambda _p: test_connection(which, self.cfg))
        job.done.connect(lambda msg: (out.setText(msg), out.setStyleSheet(f"color: {theme.DANGER if msg.startswith('Failed') else '#7bd88f'};")))
        job.finished.connect(lambda: self.jobs.remove(job))
        self.jobs.append(job)
        job.start()

    def save(self):
        self.cfg.save(self.values())
        self.accept()


# ====================================================================== log
class LogDialog(Modal):
    def __init__(self, text, parent=None):
        super().__init__(parent, "Activity log", 780)
        box = QPlainTextEdit(text or "Nothing yet.")
        box.setReadOnly(True)
        box.setStyleSheet("font-family: Consolas, 'Cascadia Mono', monospace; font-size: 12px;")
        self.body.addWidget(box, 1)
        self.footer("Close", None, self.accept, cancel_text=None)
        self.resize(820, 520)
        box.verticalScrollBar().setValue(box.verticalScrollBar().maximum())


# ====================================================================== duplicate album editions
class EditionTile(QWidget):
    """One edition of an album: its cover, with a Keep / Remove badge. Click to make it the one that stays."""
    clicked = Signal(object)
    W = 136

    def __init__(self, text, plays, fav, path, thumbs, cover_h=136):
        super().__init__()
        self.text, self.plays, self.fav, self.path, self.thumbs, self.COVER = text, plays, fav, path, thumbs, cover_h
        self.keep = self.hover = False
        self.setFixedSize(self.W, self.COVER + 56)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(text)
        if path:
            thumbs.loaded.connect(lambda key: self.update() if key == str(path) else None)

    def set_keep(self, on):
        self.keep = on
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self)

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        cover = QRectF(0, 0, self.W, self.COVER)
        shape = QPainterPath()
        shape.addRoundedRect(cover, 8, 8)
        pm = self.thumbs.get(self.path) if self.path else None
        p.save()
        p.setClipPath(shape)
        p.fillRect(cover, QColor(theme.SURFACE2))
        p.setOpacity(1.0 if self.keep or self.hover else 0.45)       # the ones that will be removed fade back
        if pm is not None and not pm.isNull():
            sc = max(cover.width() / pm.width(), cover.height() / pm.height())
            w, h = pm.width() * sc, pm.height() * sc
            p.drawPixmap(QRectF((cover.width() - w) / 2, (cover.height() - h) / 2, w, h), pm, QRectF(pm.rect()))
        p.restore()
        if self.keep:
            p.setPen(QPen(QColor(theme.ACCENT), 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(cover.adjusted(1.5, 1.5, -1.5, -1.5), 7, 7)
        badge = QRectF(8, 8, 70 if self.keep else 68, 22)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.ACCENT) if self.keep else QColor(8, 10, 14, 215))
        p.drawRoundedRect(badge, 11, 11)
        p.setPen(QColor("white") if self.keep else QColor(theme.MUTED))
        f = p.font()
        f.setPixelSize(12)
        f.setBold(True)
        p.setFont(f)
        p.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), "✓ Keep" if self.keep else "Hide")
        f.setBold(self.keep)
        p.setFont(f)
        p.setPen(QColor(theme.TEXT if self.keep else theme.MUTED))
        p.drawText(QRectF(2, self.COVER + 6, self.W - 4, 32), int(Qt.AlignmentFlag.AlignLeft) | int(Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap),
                   QFontMetrics(f).elidedText(self.text, Qt.TextElideMode.ElideRight, (self.W - 4) * 2 - 24))
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor(theme.GOLD if self.fav else theme.DIM))
        p.drawText(QRectF(2, self.COVER + 38, self.W - 4, 16), int(Qt.AlignmentFlag.AlignLeft) | int(Qt.AlignmentFlag.AlignVCenter),
                   ("★ " if self.fav else "") + (f"{self.plays} plays" if self.plays else ("favorite" if self.fav else "")))


class EditionSet(QWidget):
    """The copies of one title side by side (max 3 per row); exactly one is kept, by default the first (left) one.
    "Keep all" marks them as different titles instead."""
    GAP, PAD, COLS, BAR = 12, 10, 3, 30

    def __init__(self, labels, plays, lib, thumbs, keep, cover_h, poster=None, fav=None,
                 different="Not duplicates, don't merge", tip=None):
        super().__init__()
        poster, fav = poster or lib.poster, fav or lib.is_fav
        self.setObjectName("editionset")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"QWidget#editionset {{ background: {theme.SURFACE}; border: 1px solid {theme.BORDER}; border-radius: 10px; }}")
        self.tiles = []
        grid = QGridLayout(self)
        grid.setContentsMargins(self.PAD, self.PAD, self.PAD, self.PAD)
        grid.setSpacing(self.GAP)
        ordered = [keep] + sorted((l for l in labels if l != keep), key=str.casefold)
        for i, l in enumerate(ordered):
            t = EditionTile(l, plays(l), fav(l), poster(l), thumbs, cover_h)
            t.clicked.connect(self.choose)
            t.set_keep(i == 0)
            self.tiles.append(t)
            grid.addWidget(t, i // self.COLS, i % self.COLS)
        n = len(self.tiles)
        cols, rows = min(n, self.COLS), -(-n // self.COLS)
        self.different = QCheckBox(different)
        self.different.setToolTip(tip or "Tick this if these are really different titles (for example the UK and US versions of a show).\nAll of them stay in your list and this pair is not offered again.")
        self.different.toggled.connect(self._different)
        grid.addWidget(self.different, rows, 0, 1, cols)
        grid.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.min_w = 2 * self.PAD + cols * EditionTile.W + (cols - 1) * self.GAP
        self.setMinimumWidth(self.min_w)
        self.setFixedHeight(2 * self.PAD + rows * (cover_h + 56) + rows * self.GAP + self.BAR)

    def choose(self, tile):
        self.different.setChecked(False)
        for t in self.tiles:
            t.set_keep(t is tile)

    def _different(self, on):
        if on:
            self._before = next((t for t in self.tiles if t.keep), self.tiles[0])      # remembered for when it is unticked
            for t in self.tiles:
                t.set_keep(True)
        else:
            self.choose(getattr(self, "_before", self.tiles[0]))

    def keep(self):
        """The label that stays, or None when the user marked the set as different titles."""
        if self.different.isChecked():
            return None
        return next(t.text for t in self.tiles if t.keep)


NOUNS = {"albums": "album", "shows": "show", "movies": "movie"}


class AdaptiveGrid(QWidget):
    """Cards of a minimum width, laid out in as many columns as fit; the cards share the leftover width, so no gap is left on the right."""

    def __init__(self, gap=14):
        super().__init__()
        self.gap, self.cards = gap, []

    def add(self, card):
        card.setParent(self)
        card.show()
        self.cards.append(card)

    def resizeEvent(self, e):
        self.relayout()
        super().resizeEvent(e)

    def relayout(self):
        if not self.cards:
            return
        w = max(self.width(), 1)
        need = max(c.min_w for c in self.cards)
        cols = max(1, (w + self.gap) // (need + self.gap))
        cw = (w - (cols - 1) * self.gap) // cols
        y = 0
        for i in range(0, len(self.cards), cols):
            row = self.cards[i:i + cols]
            for j, c in enumerate(row):
                c.setGeometry(j * (cw + self.gap), y, cw, c.height())
            y += max(c.height() for c in row) + self.gap
        self.setMinimumHeight(max(0, y - self.gap))


class DuplicatesDialog(Modal):
    """Titles that exist more than once. Pick the one to show; the others are moved to Hidden (not deleted), so you can
    open this again and pick a different one at any time."""

    def __init__(self, state, kind="albums", parent=None):
        noun = NOUNS[kind]
        super().__init__(parent, "Duplicate editions" if kind == "albums" else f"Duplicate {noun}s", 820)
        self.state, self.kind, self.lib = state, kind, state.libs[kind]
        plays = lambda l: self.lib.meta.get(l).get("playcount", 0) or 0
        self.sets = editions.groups(self.lib.items, kind)
        self.choices, self.changed = [], 0
        if not self.sets:
            self.body.addWidget(label(f"No duplicate {noun}s found.", "muted"))
            self.footer("Close", None, cancel_text=None)
            return
        self.body.addWidget(label(f"{len(self.sets)} {noun}s exist more than once" +
                                  (" (Deluxe, Remastered, Explicit...)." if kind == "albums" else " (listed with and without a year or country)."), "muted", wrap=True))
        self.body.addWidget(label("Click the cover you want to show. The others are moved to Hidden: they stay out of the list and of collages, "
                                  "and come back if you pick them here later. Tick \"Not duplicates\" if they are really different " + noun + "s (all of them are then shown).", "dim", wrap=True))
        cover_h = EditionTile.W if kind == "albums" else int(EditionTile.W * 1.5)
        grid = AdaptiveGrid()
        for g in self.sets:
            shown = [l for l in g if not self.lib.is_hidden(l)]
            keep = shown[0] if len(shown) == 1 else editions.keeper(g, self.lib.is_fav, plays, self.lib.poster)
            es = EditionSet(g, plays, self.lib, state.thumbs, keep, cover_h)
            self.choices.append(es)
            grid.add(es)
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 4, 14, 8)
        col.addWidget(grid)
        col.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(inner)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body.addWidget(scroll, 1)
        self.footer("Apply", "check", self.merge)
        self.resize(1180, 700)

    def merge(self):
        """The picked title is shown, the rest of its set is hidden. Nothing is deleted or renamed."""
        lib, kind = self.lib, self.kind
        for grp, g in zip(self.choices, self.sets):
            chosen = grp.keep()
            if chosen is None:                                    # really different titles: show all, do not offer again
                for l in g:
                    lib.set_hidden(l, False)
                editions.mark_separate(kind, g)
                self.changed += 1
                continue
            for l in g:
                want = l != chosen
                if lib.is_hidden(l) != want:
                    lib.set_hidden(l, want)
                    self.changed += 1
            if any(lib.is_fav(l) for l in g):
                lib.set_fav(chosen, True)
        lib.save()
        self.accept()

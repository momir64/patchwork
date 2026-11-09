"""Dialogs: granular Sync, Settings (.env editor + data export/import) and the activity log."""
import threading
from pathlib import Path

from PySide6.QtCore import QEvent, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QLineEdit,
                               QListWidget, QPlainTextEdit, QRadioButton, QSizePolicy, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from ..core import covers, editions, transfer
from ..core.library import KINDS, Library, add_alias, title_from_label
from ..sources import Sync
from ..core.config import ENV_PATH, KEYS
from ..sources import test_connection
from ..sources import spotify_user
from ..sources.sync import KINDS, SOURCES, STEPS, Cancelled
from . import theme
from .chrome import Modal, notify
from .common import Job
from .widgets import FlowLayout, UnitSpin, button, label


def card(title=None, hint=None, divider=True, gap=14):
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
        short = bool(hint) and len(hint) <= 44
        if short:
            head.addWidget(label(hint, "dim"), 1)
        else:
            head.addStretch()
        v.addLayout(head)
        if hint and not short:
            v.addWidget(label(hint, "dim", wrap=True))
        v.addSpacing(gap)                     # air between the heading and its fields
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
    "spotify": ("Spotify", "Saved albums, liked songs, playlists", lambda c: spotify_user.signed_in(c)),
}
STEP_INFO = {
    "titles": ("Add new items", "Never deletes anything"),
    "posters": ("Download missing posters", "Only items without one"),
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
        self.start, self._cancelled = False, False
        self.footer("Start sync", "sync", self.accept_choice, on_cancel=self.cancel)

    def cancel(self):
        self._cancelled = True                    # the Cancel button throws the changes away
        self.reject()

    def reject(self):
        if not self._cancelled:                   # closing with X (or Esc) keeps the options, without syncing
            self._collect()
        super().reject()

    def accept_choice(self):
        self.start = True
        self._collect()
        self.accept()

    def _collect(self):
        self.choice = {
            "sources": [k for k, b in self.boxes["sources"].items() if b.isChecked()],
            "steps": [k for k, b in self.boxes["steps"].items() if b.isChecked()],
            "kinds": [k for k, b in self.boxes["kinds"].items() if b.isChecked()],
            "force_meta": self.force.isChecked(),
        }


# ====================================================================== settings
SECTIONS = (
    ("Sonarr", "Shows library", "sonarr", ("SONARR_URL", "SONARR_API_KEY", "SONARR_ONLY_DOWNLOADED")),
    ("Radarr", "Movies library", "radarr", ("RADARR_URL", "RADARR_API_KEY", "RADARR_ONLY_DOWNLOADED", "RADARR_ONLY_UNMONITORED")),
    ("Trakt", "Watch history of a public profile", "trakt", ("TRAKT_CLIENT_ID", "TRAKT_USER", "TRAKT_FAV_MIN_RATING", "TRAKT_SYNC_FAVORITES")),
    ("Last.fm", "Your played albums", "lastfm", ("LASTFM_API_KEY", "LASTFM_USER", "LASTFM_SOURCE", "LASTFM_PERIOD", "LASTFM_LIMIT")),
    ("TMDB", "Posters and details for shows and movies", None, ("TMDB_API_KEY",)),
    ("Spotify", "Your own free Spotify app (developer.spotify.com/dashboard): add the redirect address below, paste its Client ID and "
     "secret, then sign in. The secret is only used for release years and covers.",
     "spotify", ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET")),
)
CHECKS = {"SONARR_ONLY_DOWNLOADED": "Skip shows without files", "RADARR_ONLY_DOWNLOADED": "Skip movies without files",
          "RADARR_ONLY_UNMONITORED": "Add movies only after they are unmonitored",
          "TRAKT_SYNC_FAVORITES": "Let Trakt sync change my favorites"}
SOURCES_LF = (("Top albums", "top"), ("Listening history", "recent"))
PERIODS = (("All time", "overall"), ("Last 7 days", "7day"), ("Last month", "1month"), ("Last 3 months", "3month"),
           ("Last 6 months", "6month"), ("Last 12 months", "12month"))
HINTS = {"LASTFM_LIMIT": "",
         "TRAKT_SYNC_FAVORITES": "Off by default. When on, Trakt items rated at or above the value above become favorites on sync."}
LIMIT_HINTS = {"top": "The most played of your top albums for the period. 0 imports all.",
               "recent": "Plays in your listening history are counted per album over the period; the most played are kept. 0 imports all."}
NICE = {"SONARR_URL": "Address", "SONARR_API_KEY": "API key", "SONARR_ONLY_DOWNLOADED": "Only downloaded", "RADARR_ONLY_DOWNLOADED": "Only downloaded", "RADARR_ONLY_UNMONITORED": "Only unmonitored", "LASTFM_SOURCE": "Albums from",
        "RADARR_URL": "Address", "RADARR_API_KEY": "API key", "TRAKT_CLIENT_ID": "Client ID", "TRAKT_USER": "Username",
        "TRAKT_SYNC_FAVORITES": "Trakt sync", "TRAKT_FAV_MIN_RATING": "Favorite if rated ≥", "LASTFM_API_KEY": "API key",
        "LASTFM_USER": "Username", "LASTFM_PERIOD": "Period", "LASTFM_LIMIT": "Albums to import", "TMDB_API_KEY": "API key",
        "SPOTIFY_CLIENT_ID": "Client ID", "SPOTIFY_CLIENT_SECRET": "Client secret"}


class SettingsDialog(Modal):
    """Left: list of setting groups. Right: the details of the chosen group."""
    msg = Signal(str)
    note = Signal(str)          # a line for the activity log and the main window's status row
    status = Signal(str)        # status row only (progress)
    progress = Signal(int, int)  # the loading line in the sidebar
    busy = Signal(bool)         # an import is running

    def __init__(self, cfg, parent=None):
        super().__init__(parent, "Settings", 800, modal=False)
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
        row = QHBoxLayout()
        row.setSpacing(18)
        row.addWidget(self.nav)
        row.addWidget(self.stack, 1)
        self.body.addLayout(row, 1)
        note = label("Saved to .env in the project folder", "dim")
        self.footer("Save", "check", self.save, extra=note)
        self.nav.setCurrentRow(0)
        self.setMinimumSize(620, 440)
        self.resize(840, 625)

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
        f, v = card("Import from file", "Preferred over the account sync for large playlists and saved libraries", gap=9)
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
                v.addSpacing(2 if n == 2 else -9)           # step 3 sits a few pixels closer to step 2
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
        b.setSpacing(4)
        self.sp_liked, self.sp_play = QCheckBox("Liked songs"), QCheckBox("Playlists")
        b.addWidget(self.sp_liked)
        b.addWidget(self.sp_play)
        self.sp_min = UnitSpin("songs", "song")
        self.sp_min.setRange(1, 50)
        self.sp_min.setValue(3)
        self.sp_min.setFixedWidth(96)
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
        for cb in (self.sp_liked, self.sp_play, self.sp_covers, self.sp_meta):
            cb.setChecked(True)

        self.sp_btn = button("Import albums", "download", "primary")
        self.sp_btn.clicked.connect(self.run_spotify)
        self.sp_out = label("", "muted", wrap=True)
        brow = QHBoxLayout()
        brow.setSpacing(12)
        brow.setContentsMargins(32, 0, 0, 0)
        brow.addWidget(self.sp_btn)
        brow.addWidget(self.sp_out, 1)
        v.addSpacing(11)
        v.addLayout(brow)
        self.msg.connect(lambda m: self.sp_out.setText(m))
        return f

    def cancel_import(self):
        if getattr(self, "importing", False):
            self.cancel_event.set()
            self.sp_out.setText("Cancelling...")
            self.status.emit("Cancelling the Spotify import...")

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
        self.cancel_event = cancel = threading.Event()

        def work(progress):
            libs = {k: Library(k) for k in KINDS}
            sync = Sync(cfg, libs, log=lambda m: (self.msg.emit(m.splitlines()[0][:110]), self.note.emit("Spotify import: " + m.splitlines()[0])),
                        progress=progress, cancel=cancel)
            try:
                return sync.import_spotify(files, **opts)
            except Cancelled:
                for lib in libs.values():                  # keep whatever was already imported
                    lib.save()
                    lib.meta.save()
                return None

        job = Job(work)
        self.sp_btn.setEnabled(False)
        self.sp_out.setText("Importing...")
        self.status.emit("Spotify import...")
        self.importing = True
        self.busy.emit(True)
        self.progress.emit(0, 0)

        def on_progress(a, b):
            pct = 100 * a // max(1, b)
            self.progress.emit(a, b)
            self.sp_out.setText(f"{pct}%  ·  working...")
            self.status.emit(f"Spotify import  ·  {pct}%")
        job.progress.connect(on_progress)

        def finished(summary):
            self.sp_btn.setEnabled(True)
            self.imported = True
            self.importing = False
            if summary is None:
                self.sp_out.setText("Cancelled")
                self.note.emit("Spotify import cancelled (what was already imported is kept)")
                self.busy.emit(False)
                return
            self.sp_out.setText("Done: " + ", ".join(summary))
            self.note.emit("Spotify import finished: " + (", ".join(summary) or "nothing to do"))
            self.busy.emit(False)

        job.done.connect(finished)
        job.failed.connect(lambda m: (setattr(self, "importing", False), self.sp_btn.setEnabled(True), self.sp_out.setText("Failed: " + m), self.note.emit("Spotify import failed: " + m), self.busy.emit(False)))
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
                if k.endswith(("API_KEY", "CLIENT_ID", "CLIENT_SECRET")):
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
        if title == "Spotify":
            self.spotify_login(v)
            self.spotify_account_options(v)
            v.addSpacing(6)
            v.addWidget(self.spotify_page())
        return f

    # ---- Spotify sign-in (the account is read on every sync; the export-file import below does not need it)
    def spotify_login(self, v):
        v.addSpacing(14)
        v.addWidget(label("Sign in", "cardtitle"))
        v.addWidget(label("Add this redirect address to your Spotify app (Settings -> Redirect URIs), then sign in. You can change it, e.g. to use another port. "
                          "Sync then reads your saved albums, liked songs, playlists and top songs directly.", "dim", wrap=True))
        uri = QLineEdit(spotify_user.redirect(self.cfg))
        uri.setPlaceholderText(spotify_user.REDIRECT_URI)
        self.fields["SPOTIFY_REDIRECT_URI"] = uri                 # editable: change it when port 8765 is taken
        copy = button("Copy", "copy")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(uri.text().strip() or spotify_user.REDIRECT_URI))
        urow = QHBoxLayout()
        urow.setSpacing(10)
        urow.addWidget(uri, 1)
        urow.addWidget(copy)
        v.addLayout(urow)
        self.sp_login_btn = button("Sign in with Spotify", "link", "primary")
        self.sp_logout_btn = button("Sign out", "x")
        self.sp_account = label("", "muted", wrap=True)
        self.sp_login_btn.clicked.connect(self.spotify_sign_in)
        self.sp_logout_btn.clicked.connect(self.spotify_sign_out)
        lrow = QHBoxLayout()
        lrow.setSpacing(12)
        lrow.addWidget(self.sp_login_btn)
        lrow.addWidget(self.sp_logout_btn)
        lrow.addWidget(self.sp_account, 1)
        v.addLayout(lrow)
        self.sp_login_cancel = threading.Event()
        self.sp_signing_in = False
        self.spotify_account_state()

    def spotify_account_options(self, v):
        """What a sync takes from the signed-in account (same wording as the file import below)."""
        v.addSpacing(14)
        v.addWidget(label("Choose what to import", "cardtitle"))
        v.addWidget(label("Saved albums are always imported.", "dim"))
        boxes = QVBoxLayout()
        boxes.setSpacing(4)
        for key, text in (("SPOTIFY_TOP", "Top songs"), ("SPOTIFY_LIKED", "Liked songs"), ("SPOTIFY_PLAYLISTS", "Playlists")):
            cb = QCheckBox(text)
            cb.setChecked(self.cfg.flag(key))
            self.fields[key] = cb
            boxes.addWidget(cb)
        v.addLayout(boxes)
        spin = UnitSpin("songs", "song")
        spin.setRange(1, 50)
        spin.setValue(self.cfg.integer("SPOTIFY_MIN_SONGS", 3))
        spin.setFixedWidth(96)
        self.fields["SPOTIFY_MIN_SONGS"] = spin
        lbls = [label("Skip albums with fewer than", "dim"), label("in these lists", "dim")]
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(lbls[0])
        row.addWidget(spin)
        row.addWidget(lbls[1])
        row.addStretch()
        v.addLayout(row)

        def sync_min():
            on = any(self.fields[k].isChecked() for k in ("SPOTIFY_TOP", "SPOTIFY_LIKED", "SPOTIFY_PLAYLISTS"))
            spin.setEnabled(on)
            for l in lbls:
                l.setEnabled(on)
        for k in ("SPOTIFY_TOP", "SPOTIFY_LIKED", "SPOTIFY_PLAYLISTS"):
            self.fields[k].toggled.connect(sync_min)
        sync_min()

    def spotify_account_state(self, text=None):
        """Shows who is signed in and which buttons make sense."""
        who = spotify_user.user_name(self.cfg)
        self.sp_logout_btn.setVisible(bool(who) and not self.sp_signing_in)
        self.sp_login_btn.setText("Cancel" if self.sp_signing_in else ("Sign in again" if who else "Sign in with Spotify"))
        self.sp_account.setText(text if text is not None else (f"Signed in as {who}" if who else "Not signed in"))

    def spotify_sign_in(self):
        if self.sp_signing_in:                              # the button is "Cancel" while the browser login is open
            self.sp_login_cancel.set()
            return
        values = self.values()
        self.cfg.values.update(values)
        if not self.cfg.get("SPOTIFY_CLIENT_ID"):
            self.spotify_account_state("Enter the Client ID first.")
            return
        self.sp_login_cancel.clear()
        self.sp_signing_in = True
        self.spotify_account_state("Waiting for the Spotify login in your browser...")
        job = Job(lambda _p: spotify_user.sign_in(self.cfg, self.sp_login_cancel))

        def done(name):
            self.sp_signing_in = False
            self.cfg.save({k: v for k, v in values.items() if k.startswith("SPOTIFY")})     # the app the login belongs to is kept
            self.spotify_account_state(f"Signed in as {name}")
            self.note.emit(f"Spotify: signed in as {name}")

        def failed(msg):
            self.sp_signing_in = False
            self.spotify_account_state("Cancelled" if "cancelled" in msg else "Failed: " + msg.split(": ", 1)[-1])

        job.done.connect(done)
        job.failed.connect(failed)
        job.finished.connect(lambda: self.jobs.remove(job))
        self.jobs.append(job)
        job.start()

    def spotify_sign_out(self):
        spotify_user.sign_out()
        self.spotify_account_state()

    def export_data(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export data", "patchwork-data.zip", "With posters (*.zip);;Data only (*.json)")
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
                      else w.currentData() if isinstance(w, QComboBox) else str(w.value()) if isinstance(w, QSpinBox) else w.text().strip())
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
    """The activity log. New lines are appended live (see `append`) and the view follows them unless you scrolled up."""

    def __init__(self, text, parent=None):
        super().__init__(parent, "Activity log", 780, modal=False)
        self.box = QPlainTextEdit(text or "Nothing yet.")
        self.box.setReadOnly(True)
        self.box.setMaximumBlockCount(5000)
        self.box.setStyleSheet("font-family: Consolas, 'Cascadia Mono', monospace; font-size: 12px;")
        self.body.addWidget(self.box, 1)
        self.footer("Close", None, self.accept, cancel_text=None)
        self.resize(820, 520)
        self._empty = not text
        QTimer.singleShot(0, self.to_end)

    def to_end(self):
        bar = self.box.verticalScrollBar()
        bar.setValue(bar.maximum())

    def append(self, line):
        bar = self.box.verticalScrollBar()
        follow = bar.value() >= bar.maximum() - 4                 # at the bottom: keep following; scrolled up: stay put
        if self._empty:
            self.box.clear()
            self._empty = False
        self.box.appendPlainText(line)
        if follow:
            self.to_end()


# ====================================================================== duplicate album editions
class EditionTile(QWidget):
    """One copy of a title: its cover with a state badge (Keep / Hide / Different). Click the cover to keep this one;
    click the chip on the cover to say it is a different title altogether."""
    clicked = Signal(object)
    apart_toggled = Signal(object)
    W = 136

    def __init__(self, text, plays, path, thumbs, cover_h=136, noun="title", show_name=True, lines=2, plays_row=True):
        super().__init__()
        self.text, self.plays, self.path, self.thumbs, self.COVER = text, plays, path, thumbs, cover_h
        self.noun, self.show_name = noun, show_name
        self.keep = self.hover = self.apart = False
        self.state = "hide"                                  # keep | hide | apart (set by the card that holds the tiles)
        self.lines = lines
        self.setFixedSize(self.W, self.COVER + (4 + 15 * lines if show_name else 0) + (18 if plays_row else 0) + (0 if (show_name or plays_row) else 0))
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(text)
        if path:
            thumbs.loaded.connect(lambda key: self.update() if key == str(path) else None)

    def chip_rect(self):
        return QRectF(6, self.COVER - 28, self.W - 12, 22)

    def set_keep(self, on):
        self.keep = on
        self.update()

    def set_apart(self, on):
        self.apart = on
        self.update()

    def set_state(self, state):
        self.state = state
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            (self.apart_toggled if self.chip_rect().contains(e.position()) else self.clicked).emit(self)

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
        kept, apart = self.state == "keep", self.state == "apart"
        p.save()
        p.setClipPath(shape)
        p.fillRect(cover, QColor(theme.SURFACE2))
        p.setOpacity(0.45 if (self.state == "hide" and not self.hover) else 1.0)       # the ones that will be hidden fade back
        if pm is not None and not pm.isNull():
            sc = max(cover.width() / pm.width(), cover.height() / pm.height())
            w, h = pm.width() * sc, pm.height() * sc
            p.drawPixmap(QRectF((cover.width() - w) / 2, (cover.height() - h) / 2, w, h), pm, QRectF(pm.rect()))
        p.restore()
        if kept:
            p.setPen(QPen(QColor(theme.ACCENT), 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(cover.adjusted(1.5, 1.5, -1.5, -1.5), 7, 7)
        f = p.font()
        f.setPixelSize(12)
        f.setBold(True)
        p.setFont(f)
        # state badge, top left
        text = "✓ Keep" if kept else ("Different" if apart else "Hide")
        badge = QRectF(8, 8, QFontMetrics(f).horizontalAdvance(text) + 22, 22)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.ACCENT) if kept else QColor(8, 10, 14, 215))
        p.drawRoundedRect(badge, 11, 11)
        p.setPen(QColor("white") if kept else QColor(theme.MUTED))
        p.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), text)
        # the "different <title>" chip, bottom of the cover
        chip = self.chip_rect()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.ACCENT_SOFT) if self.apart else QColor(8, 10, 14, 205))
        p.drawRoundedRect(chip, 11, 11)
        p.setPen(QColor(theme.ACCENT_H) if self.apart else QColor(theme.MUTED))
        f.setBold(False)
        f.setPixelSize(11)
        p.setFont(f)
        p.drawText(chip, int(Qt.AlignmentFlag.AlignCenter), ("✓ " if self.apart else "") + f"Different {self.noun}")
        # caption: the name (only when there is no name box above to read it from) and the play count
        f.setPixelSize(12)
        y = self.COVER + 4
        if self.show_name:
            f.setBold(kept)
            p.setFont(f)
            p.setPen(QColor(theme.TEXT if kept or apart else theme.MUTED))
            p.drawText(QRectF(2, y, self.W - 4, 15 * self.lines), int(Qt.AlignmentFlag.AlignLeft) | int(Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap),
                       QFontMetrics(f).elidedText(self.text, Qt.TextElideMode.ElideRight, (self.W - 4) * self.lines - 24))
            y += 15 * self.lines + 2
        if self.plays:
            f.setBold(False)
            p.setFont(f)
            p.setPen(QColor(theme.DIM))
            p.drawText(QRectF(2, y, self.W - 4, 16), int(Qt.AlignmentFlag.AlignLeft) | int(Qt.AlignmentFlag.AlignVCenter), f"{self.plays} plays")


class EditionSet(QWidget):
    """The copies of one title side by side (max 2 per row). Click a cover to keep that one (the others get hidden); the chip on
    a cover says it is a different title, not a duplicate. When fewer than two copies are left as duplicates, the set is
    "not duplicates" altogether. When the names differ a lot, a Name box picks what the kept title is called."""
    GAP, VGAP, PAD, COLS, NAME = 12, 8, 10, 2, 32

    def __init__(self, labels, plays, lib, thumbs, keep, cover_h, poster=None, name_choice=False, noun="title", default_name=None):
        super().__init__()
        poster = poster or lib.poster
        self.setObjectName("editionset")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"QWidget#editionset {{ background: {theme.SURFACE}; border: 1px solid {theme.BORDER}; border-radius: 10px; }}")
        self.tiles, self._name_touched, self.default_name = [], False, default_name
        ordered = [keep] + sorted((l for l in labels if l != keep), key=str.casefold)
        grid = QGridLayout(self)
        grid.setContentsMargins(self.PAD, self.PAD, self.PAD, self.PAD)
        grid.setHorizontalSpacing(self.GAP)
        grid.setVerticalSpacing(self.VGAP)
        f12 = QFont()
        f12.setPixelSize(12)
        f12.setBold(True)
        fm = QFontMetrics(f12)
        lines = 1 if all(fm.horizontalAdvance(l) <= EditionTile.W - 6 for l in ordered) else 2
        plays_row = any(plays(l) for l in ordered)
        for i, l in enumerate(ordered):
            t = EditionTile(l, plays(l), poster(l), thumbs, cover_h, noun, show_name=not name_choice, lines=lines, plays_row=plays_row)
            t.clicked.connect(self.choose)
            t.apart_toggled.connect(self.toggle_apart)
            t.set_keep(i == 0)
            self.tiles.append(t)
            grid.addWidget(t, i // self.COLS, i % self.COLS)
        n = len(self.tiles)
        cols, rows = min(n, self.COLS), -(-n // self.COLS)
        self.name_box = None
        if name_choice:
            self.name_box = QComboBox()
            self.name_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            self.name_box.setMinimumContentsLength(8)       # a long name must not stretch the card's columns apart
            for l in ordered:
                self.name_box.addItem(l)
            if default_name:
                self.name_box.setCurrentText(default_name)               # the simplest name, whichever cover is kept
            self.name_box.activated.connect(lambda _: setattr(self, "_name_touched", True))
            nr = QWidget()
            nh = QHBoxLayout(nr)
            nh.setContentsMargins(0, 0, 0, 0)
            nh.addWidget(label("Name:", "muted"))
            nh.addWidget(self.name_box, 1)
            grid.addWidget(nr, rows, 0, 1, cols)
        grid.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)     # covers start at the same height in every card
        self.min_w = 2 * self.PAD + cols * EditionTile.W + (cols - 1) * self.GAP
        self.setMinimumWidth(self.min_w)
        self.natural_h = 2 * self.PAD + rows * self.tiles[0].height() + (rows - 1) * self.VGAP + ((self.VGAP + self.NAME) if name_choice else 0)
        self.setFixedHeight(self.natural_h)
        self._sync()

    # ---- state
    def _active(self):
        return [t for t in self.tiles if not t.apart]

    def separate(self):
        """Fewer than two copies left as duplicates of each other: nothing to merge."""
        return len(self._active()) < 2

    def _sync(self):
        sep = self.separate()
        for t in self.tiles:
            t.set_state("apart" if (sep or t.apart) else ("keep" if t.keep else "hide"))

    def choose(self, tile):
        """Keep this one: every copy is a duplicate again, and the others are hidden."""
        for t in self.tiles:
            t.apart = False
            t.set_keep(t is tile)
        self._sync()

    def toggle_apart(self, tile):
        tile.set_apart(not tile.apart)
        if tile.apart and tile.keep:
            tile.set_keep(False)
            rest = self._active()
            if rest:
                rest[0].set_keep(True)
        elif not tile.apart and not any(t.keep and not t.apart for t in self.tiles):
            tile.set_keep(True)
        self._sync()

    # ---- result
    def keep(self):
        """The label that stays, or None when the set is not a duplicate set."""
        if self.separate():
            return None
        return next(t.text for t in self.tiles if t.keep and not t.apart)

    def apart_labels(self):
        return [] if self.separate() else [t.text for t in self.tiles if t.apart]

    def chosen_name(self):
        return self.name_box.currentText() if self.name_box else self.default_name


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
        height = lambda c: getattr(c, "natural_h", c.height())
        rows, row = [], []
        for c in self.cards:                              # every row is full (the cards are sorted by size, so rows mostly match)
            if row and len(row) == cols:
                rows.append(row)
                row = []
            row.append(c)
        rows.append(row)
        y = 0
        for row in rows:
            rh = max(height(c) for c in row)
            for j, c in enumerate(row):
                c.setFixedHeight(rh)                      # one height per row, so the covers line up across cards
                c.setGeometry(j * (cw + self.gap), y, cw, rh)
            y += rh + self.gap
        self.setMinimumHeight(max(0, y - self.gap))


class DuplicatesDialog(Modal):
    """Titles that exist more than once. Pick the one to show; the others are moved to Hidden (not deleted), so you can
    open this again and pick a different one at any time."""

    def __init__(self, state, kind="albums", parent=None, edit=False, only=None):
        """edit=True also lists the sets that are already resolved, so an earlier choice can be changed.
        only: when given, just the sets that contain one of these titles."""
        noun = NOUNS[kind]
        lib = state.libs[kind]
        if kind == "albums":                              # hash the covers first (parallel; only new / changed ones are read)
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                covers.hash_posters(lib)
            finally:
                QApplication.restoreOverrideCursor()
        sets = [g for g in editions.groups(lib.items, kind, lib)
                if edit or sum(not lib.is_hidden(l) for l in g) > 1]     # at most one shown = already resolved (also when you hid the last one yourself)
        if only is not None:
            sets = [g for g in sets if any(l in only for l in g)]
        sets.sort(key=lambda g: (len(g), min(g, key=str.casefold).casefold()))     # fewest copies first, so same-sized cards share rows
        head = "Duplicate editions" if kind == "albums" else f"Duplicate {noun}s"
        super().__init__(parent, ("Edit " + head.lower()) if edit else head, 820 if sets else 340)
        self.state, self.kind, self.lib, self.sets = state, kind, lib, sets
        plays = lambda l: self.lib.meta.get(l).get("playcount", 0) or 0
        self.choices, self.changed = [], 0
        if not self.sets:
            self.body.addWidget(label(f"No duplicate {noun}s found.", "muted"))
            self.footer("Close", None, cancel_text=None)
            return
        self.body.addWidget(label(f"{len(self.sets)} {noun}s exist more than once (same name, same id, same artist and cover, or marked by you). Click a cover to keep it and hide the others, or mark one as a different " + noun + ".", "muted", wrap=True))
        cover_h = EditionTile.W if kind == "albums" else int(EditionTile.W * 1.5)
        grid = AdaptiveGrid()
        for g in self.sets:
            shown = [l for l in g if not self.lib.is_hidden(l)]
            keep = shown[0] if len(shown) == 1 else editions.keeper(g, self.lib.is_fav, plays, self.lib.poster)
            es = EditionSet(g, plays, self.lib, state.thumbs, keep, cover_h, name_choice=self._names_differ(g), noun=noun,
                            default_name=editions.simplest(g, kind))
            es.all_hidden_default = keep if not shown else None   # nothing shown (you hid them yourself): leave it unless you pick
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

    def _names_differ(self, g):
        """True when the titles are not just one name with a year / edition tag (so the name is worth choosing)."""
        key = editions.base_key if self.kind == "albums" else editions.video_key
        return len({key(l) for l in g}) > 1

    def merge(self):
        """The picked title is shown, the rest of its set is hidden. Nothing is deleted or renamed."""
        lib, kind = self.lib, self.kind
        rec = editions.load_dup_hidden(kind)
        for grp, g in zip(self.choices, self.sets):
            chosen = grp.keep()
            if chosen is not None and chosen == grp.all_hidden_default and not grp.apart_labels():
                continue                                          # still the untouched default of a set you had hidden entirely
            if chosen is None:                                    # really different titles: show all, do not offer again
                for l in g:
                    lib.set_hidden(l, False)
                    rec.discard(l)
                editions.mark_separate(kind, g)
                self.changed += 1
                continue
            apart = grp.apart_labels()
            if apart:                                             # not duplicates of the others: shown, and left alone from now on
                editions.mark_apart(kind, g, apart)
            for l in g:
                want = l != chosen and l not in apart
                if lib.is_hidden(l) != want:
                    lib.set_hidden(l, want)
                    self.changed += 1
                (rec.add if want else rec.discard)(l)
            name = grp.chosen_name()
            if name and name != chosen:                           # the kept title is called by the name you picked
                lib.meta.set_name(chosen, lib.name(name))
                self.changed += 1
            if any(lib.is_fav(l) for l in g if l not in apart):
                lib.set_fav(chosen, True)
        editions.save_dup_hidden(kind, rec)
        lib.save()
        self.accept()


class MetadataDialog(Modal):
    """Edit what is stored about one item: name, creator, year, genres, countries, languages (and studio / overview for
    shows and movies). Lists are typed separated by commas. Fields changed here are kept when you sync."""

    def __init__(self, state, kind, lbl, parent=None):
        super().__init__(parent, "Edit metadata", 560)
        self.lib, self.lbl, self.kind, self.changed = state.libs[kind], lbl, kind, False
        m = self.lib.meta.get(lbl)
        self.body.addWidget(label("Separate several values with commas. Changed fields are kept when you sync.", "muted", wrap=True))
        form = QGridLayout()                              # fixed row spacing; only the overview grows when the dialog is resized
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.setColumnStretch(1, 1)
        add_row = lambda text, w, top=False: (form.addWidget(label(text, "muted"), form.rowCount(), 0,
                                                             Qt.AlignmentFlag.AlignTop if top else Qt.AlignmentFlag.AlignVCenter),
                                              form.addWidget(w, form.rowCount() - 1, 1))
        joined = lambda key: ", ".join(str(x) for x in (m.get(key) or []))
        creator = {"albums": "Artist", "movies": "Director"}.get(kind, "Creators")
        self.name = QLineEdit(self.lib.name(lbl))
        self.creators = QLineEdit(joined("creators"))
        self.year = QLineEdit(str(m.get("year") or ""))
        self.genres = QLineEdit(joined("genres"))
        self.countries = QLineEdit(joined("countries"))
        self.languages = QLineEdit(joined("languages"))
        for text, w in (("Name", self.name), (creator, self.creators), ("Year", self.year), ("Genres", self.genres),
                        ("Countries", self.countries), ("Languages", self.languages)):
            add_row(text, w)
        self.studio = self.overview = None
        if kind != "albums":
            self.studio = QLineEdit(str(m.get("studio") or ""))
            add_row("Studio", self.studio)
            self.overview = QPlainTextEdit(str(m.get("overview") or ""))
            self.overview.setMinimumHeight(110)
            add_row("Overview", self.overview, top=True)
            form.setRowStretch(form.rowCount() - 1, 1)
        self.body.addLayout(form, 1 if self.overview else 0)
        if not self.overview:
            self.body.addStretch(1)
        self.error = label("", "muted")
        self.error.hide()                                 # only takes room when there is something to say
        self.body.addWidget(self.error)
        self.footer("Save", "check", self.save)

    def event(self, e):
        r = super().event(e)
        if e.type() == QEvent.Type.WindowActivate and not getattr(self, "_unfocused", False):
            self._unfocused = True                        # no field starts out focused / selected
            QTimer.singleShot(0, lambda: (w := self.focusWidget()) and w.clearFocus())
        return r

    def save(self):
        split = lambda w: [x.strip() for x in w.text().split(",") if x.strip()]
        year = self.year.text().strip()
        if year and not year.isdigit():
            self.error.setText("Year must be a number.")
            self.error.show()
            return
        fields = {"creators": split(self.creators), "year": int(year) if year else None, "genres": split(self.genres),
                  "countries": split(self.countries), "languages": split(self.languages)}
        if self.studio is not None:
            fields["studio"] = self.studio.text().strip()
            fields["overview"] = self.overview.toPlainText().strip()
        meta = self.lib.meta
        changed = meta.set_fields(self.lbl, fields)
        name = self.name.text().strip()
        if name and name != self.lib.name(self.lbl):
            meta.set_name(self.lbl, name)
            changed = True
        if changed:
            self.lib.save()
        self.changed = changed
        self.accept()

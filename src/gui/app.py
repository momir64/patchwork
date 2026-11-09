"""Main window + entry point of the GUI."""
import ctypes
import os
import sys
import threading

from PySide6.QtCore import QEvent, QObject, QPointF, QRect, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QHBoxLayout, QInputDialog, QMainWindow, QMenu, QStackedWidget, QVBoxLayout, QWidget

from ..core.config import DATA_DIR, RES, Config
from ..core import editions
from ..core.library import KINDS, LIBRARIES, Library
from ..sources import Sync
from ..sources.sync import Cancelled
from . import icons, theme
from .colorpicker import pick_color
from .chrome import EdgeResizer, Polisher, TitleBar, ask_text, round_window_corners
from .collage_page import CollagePage
from .common import Job
from .dialogs import DEFAULT_SYNC, LogDialog, SettingsDialog, SyncDialog
from .media_page import MediaPage
from .sidebar import COLOR_NAMES, FOLDER_COLORS, Sidebar
from .state import AppState

COMPACT_BELOW = 960


def swatch(color, size=16, selected=False):
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.GlobalColor.transparent)
    pm.setDevicePixelRatio(2.0)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(1, 1, size - 2, size - 2, 4, 4)
    if selected:                                   # white tick instead of a menu check box
        p.setPen(QPen(QColor("white"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolyline([QPointF(4.5, 8.5), QPointF(7, 11), QPointF(11.5, 5.5)])
    p.end()
    return QIcon(pm)


class LogBridge(QObject):
    """Lets the sync worker thread post log lines to the GUI thread."""
    message = Signal(str)
    stage = Signal(str)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Patchwork")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)      # the app draws its own title bar
        self.setWindowIcon(QIcon(str(RES / "assets" / "icon.png")))
        self.setMinimumSize(720, 480)
        self.state = AppState()
        self.log_lines, self.sync_job, self.current_key, self.last_status, self._pct = [], None, None, "", -1
        self.log_dialog = self.settings_dialog = None
        self.bridge = LogBridge()
        self.bridge.message.connect(self.add_log)
        self.bridge.stage.connect(self.on_stage)
        self.sync_stage, self.sync_cancel, self._live_jobs = "", None, []

        self.pages = QStackedWidget()
        self.page_for = {}                              # nav key -> widget
        self._stale = set()                             # media pages that need a reload before they are shown
        for kind in LIBRARIES:
            self._add_media_page(kind, MediaPage(self.state, kind=kind, lazy=True))
        self.collage = CollagePage(self.state)
        self.collage.log.connect(self.add_log)
        self.collage.loading.connect(lambda a, b: None if self.sync_job else self.sidebar.set_progress(a, b))
        self.collage.loaded.connect(lambda: None if (self.sync_job or self.sidebar.syncing) else self.sidebar.progress.hide())
        self._register("collage", self.collage)

        # ---- sidebar (libraries + groups, collage / sync / settings / log at the bottom)
        self.sidebar = Sidebar({k: self.state.libs[k].title for k in LIBRARIES})
        self.sidebar.navigate.connect(self.go)
        self.sidebar.new_group.connect(self.create_group)
        self.sidebar.group_menu.connect(self.group_context)
        self.sidebar.group_moved.connect(self.move_group)
        self.sidebar.sync_clicked.connect(lambda: self.start_sync(self.state.pref("sync", DEFAULT_SYNC)))
        self.sidebar.sync_options.connect(self.sync_options)
        self.sidebar.settings_clicked.connect(self.open_settings)
        self.sidebar.set_wide(self.state.pref("sidebar_width", self.sidebar.WIDE))
        self.sidebar.width_changed.connect(lambda w: self.state.set_pref("sidebar_width", w))
        self.sidebar.set_expanded(self.state.pref("groups_open", {}))
        self.sidebar.expanded_changed.connect(lambda k, on: self.state.set_pref("groups_open", {**self.state.pref("groups_open", {}), k: on}))
        self.sidebar.log_clicked.connect(self.show_log)

        body = QWidget()
        h = QHBoxLayout(body)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self.sidebar)
        h.addWidget(self.pages, 1)
        self.titlebar = TitleBar(self)
        root = QWidget()
        root.setObjectName("root")
        rv = QVBoxLayout(root)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        rv.addWidget(self.titlebar)
        rv.addWidget(body, 1)
        self.setCentralWidget(root)
        self.resizer = EdgeResizer(self, top_margin=3)
        self.polisher = Polisher()
        QApplication.instance().installEventFilter(self.polisher)

        self.group_pages = {}                           # (kind, name) -> MediaPage
        self.rebuild_groups()
        self.go("shows")

    # ------------------------------------------------------------ pages / navigation
    def _register(self, key, widget):
        self.pages.addWidget(widget)
        self.page_for[key] = widget

    def _add_media_page(self, key, page):
        page.data_changed.connect(self.data_changed)
        page.groups_changed.connect(self.rebuild_groups)
        page.log.connect(self.add_log)
        page.set_status(self.last_status)
        page.cancel_sync.connect(self.cancel_sync)
        page.set_syncing(bool(self.sync_job))
        self._register(key, page)
        if getattr(page, "lazy", False):
            self._stale.add(page)                       # filled in when you first open it

    def go(self, key, picks=True):
        page = self.page_for.get(key)
        if not page:
            return
        previous = self.page_for.get(self.current_key)
        if key == "collage" and picks and isinstance(previous, MediaPage):
            items, desc = previous.current_picks()      # the collage starts from what you were just looking at
            self.collage.use_picks(items, desc)
        self.pages.setCurrentWidget(page)
        self.sidebar.set_current(key)
        self.current_key = key
        tab = getattr(self.state, "tab", "all")
        if isinstance(page, MediaPage) and page.mode.value != tab:      # the All / Favorites / ... tab follows you between pages
            page.mode.set_value(tab, emit=False)
            self._stale.add(page)
        if page in self._stale:                       # reloaded lazily: only the page you look at pays for a change
            self._stale.discard(page)
            page.reload()

    def data_changed(self):
        for lib in self.state.libs.values():
            editions.sweep(lib)                       # duplicates hidden earlier come back once they are no longer duplicates
        shown = self.page_for.get(self.current_key)
        for p in self.all_media_pages():
            if p is shown:
                if getattr(p, "_self_updated", False):
                    p._self_updated = False               # it just updated itself (e.g. a star click): no full reload
                else:
                    p.reload()
                self._stale.discard(p)
            else:
                self._stale.add(p)
        self.update_counts()
        self.collage.reload_groups()

    def all_media_pages(self):
        return [p for p in self.page_for.values() if isinstance(p, MediaPage)]

    def update_counts(self):
        self.sidebar.set_counts({k: len(self.state.libs[k].shown_items()) for k in LIBRARIES})
        for k in LIBRARIES:
            self.sidebar.set_groups(k, self._group_rows(k))
        self.sidebar.set_current(self.current_key)

    # ------------------------------------------------------------ groups
    def _group_rows(self, kind):
        """(name, number of visible members, color) per group; hidden titles are not counted."""
        lib = self.state.libs[kind]
        return [(n, sum(not lib.is_hidden(l) for l in self.state.groups.members(kind, n)), self.state.group_color(kind, n))
                for n in self.state.groups.names(kind)]

    def move_group(self, kind, name, target, after):
        self.state.groups.move(kind, name, target, after)
        self.sidebar.set_groups(kind, self._group_rows(kind))
        self.sidebar.set_current(self.current_key)
        self.collage.reload_groups()

    def rebuild_groups(self):
        wanted = {(k, n) for k in LIBRARIES for n in self.state.groups.names(k)}
        for key in [g for g in self.group_pages if g not in wanted]:
            page = self.group_pages.pop(key)
            self.page_for.pop(f"group:{key[0]}:{key[1]}", None)
            self.pages.removeWidget(page)
            page.deleteLater()
        for key in sorted(wanted):
            if key in self.group_pages:
                pg = self.group_pages[key]
                if pg is self.page_for.get(self.current_key):
                    pg.reload()
                else:
                    self._stale.add(pg)
                continue
            page = MediaPage(self.state, group=key, lazy=True)
            page.group_deleted.connect(self.group_removed)
            page.group_renamed.connect(self.group_renamed)
            self._add_media_page(f"group:{key[0]}:{key[1]}", page)
            self.group_pages[key] = page
        for k in LIBRARIES:
            self.sidebar.set_groups(k, self._group_rows(k))
        for p in self.all_media_pages():
            if p.kind:
                p.reload_facets()
        self.collage.reload_groups()
        self.update_counts()
        self.go(self.current_key if self.current_key in self.page_for else "shows")

    def create_group(self, kind):
        title = self.state.libs[kind].title
        name = ask_text(self, "New group", f"Name of the new group in {title} (e.g. Sci-fi, Horror night):", "", "Create")
        if name:
            self.state.add_group(kind, name, [])
            self.rebuild_groups()
            self.go(f"group:{kind}:{name}")

    def group_removed(self, kind, name):
        self.state.set_group_color(kind, name, None)
        self.current_key = None
        self.rebuild_groups()
        self.go(kind)

    def group_renamed(self, kind, old, new):
        self.state.move_group_color(kind, old, new)
        self.rebuild_groups()
        self.go(f"group:{kind}:{new}")

    def group_context(self, kind, name, pos):
        menu = QMenu(self)
        key = f"group:{kind}:{name}"
        menu.addAction(icons.icon("mosaic", theme.MUTED, 16), "Make collage", lambda: (self.collage.use_group(kind, name), self.go("collage", picks=False)))
        colors = menu.addMenu(icons.icon("folder", self.state.group_color(kind, name), 16), "Color")
        current = self.state.group_color(kind, name)
        for col, cname in zip(FOLDER_COLORS, COLOR_NAMES):
            colors.addAction(swatch(col, selected=(col == current)), cname, lambda c=col: self.set_group_color(kind, name, c))
        colors.addSeparator()
        colors.addAction("Custom...", lambda: self.pick_group_color(kind, name))
        colors.addAction("Reset", lambda: self.set_group_color(kind, name, None))
        menu.addAction(icons.icon("edit", theme.MUTED, 16), "Rename...", lambda: (self.go(key), self.group_pages[(kind, name)].rename_group()))
        menu.addAction(icons.icon("trash", theme.DANGER, 16), "Delete...", lambda: (self.go(key), self.group_pages[(kind, name)].delete_group()))
        menu.exec(pos)

    def set_group_color(self, kind, name, color):
        self.state.set_group_color(kind, name, color)
        self.rebuild_groups()

    def pick_group_color(self, kind, name):
        c = pick_color(self, QColor(self.state.group_color(kind, name)), "Group color")
        if c:
            self.set_group_color(kind, name, c.name())

    # ------------------------------------------------------------ status / log
    def show_log(self):
        if self.log_dialog is not None:
            self.log_dialog.raise_()
            self.log_dialog.activateWindow()
            return
        self.log_dialog = LogDialog("\n".join(self.log_lines), self)
        self.log_dialog.finished.connect(lambda *_: setattr(self, "log_dialog", None))
        self.log_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.log_dialog.show()

    def add_log(self, text):
        self.log_lines.append(text)
        if getattr(self, "log_dialog", None):               # the log window is open: show the line live
            self.log_dialog.append(text)
        self.last_status = text
        if self.sync_job:                                # while syncing the status shows the step and its percentage
            return
        for p in self.all_media_pages():
            p.set_status(text)

    def show_status(self, text):
        """Only the bottom status row (not the log): progress of things that are not a sync."""
        self.last_status = text
        if not self.sync_job:
            for p in self.all_media_pages():
                p.set_status(text)

    # ------------------------------------------------------------ sync
    def sync_options(self):
        dlg = SyncDialog(self.state.cfg, self.state.pref("sync", DEFAULT_SYNC), self)
        dlg.exec()
        if dlg.choice:                                      # Start sync, or closed with X: the options are kept
            self.state.set_pref("sync", dlg.choice)
            if dlg.start:
                self.start_sync(dlg.choice)

    def start_sync(self, choice):
        if self.sync_job:
            return
        cfg = Config()
        self.state.cfg = cfg
        bridge = self.bridge

        self.sync_cancel = cancel = threading.Event()

        def work(progress):
            libs = {k: Library(k) for k in KINDS}      # own instances: this runs in a worker thread
            sync = Sync(cfg, libs, log=bridge.message.emit, progress=progress, stage=bridge.stage.emit, cancel=cancel)
            try:
                return sync.run(choice["sources"], choice["steps"], choice["kinds"], choice.get("force_meta", False))
            except Cancelled:
                for lib in libs.values():                # keep whatever was already fetched
                    lib.save()
                    lib.meta.save()
                return None

        self.sync_job = job = Job(work)
        self._live_jobs.append(job)                       # keep the thread object alive until it has really finished
        job.finished.connect(lambda j=job: self._live_jobs.remove(j) if j in self._live_jobs else None)
        self.sync_job.progress.connect(self.on_progress)
        self.sync_job.done.connect(lambda s: self.sync_finished("Sync cancelled" if s is None else "Sync finished: " + (", ".join(s) or "nothing to do")))
        self.sync_job.failed.connect(lambda m: self.sync_finished(f"Sync failed: {m}"))
        self.sidebar.set_syncing(True)
        self.sidebar.set_progress(0, 0)
        self.sync_stage, self._pct = "Starting sync", -1
        self.add_log("Sync started...")
        for p in self.all_media_pages():
            p.set_syncing(True)
        self.show_sync_status()
        self.sync_job.start()

    def on_stage(self, text):
        self.sync_stage, self._pct = text, -1
        self.show_sync_status()

    def on_progress(self, a, b):
        self.sidebar.set_progress(a, b)
        if b:
            pct = int(100 * a / b)
            if pct != self._pct:                         # show how far the current step is, not just what it is
                self._pct = pct
                self.show_sync_status()

    def show_sync_status(self):
        if not self.sync_job:
            return
        text = self.sync_stage + (f"  ·  {self._pct}%" if self._pct >= 0 else "...")
        for p in self.all_media_pages():
            p.set_status(text)

    def _import_busy(self, on, dlg):
        """A Spotify import is running: same loading line and cancel button as a sync."""
        self.sidebar.set_syncing(on or bool(self.sync_job), text="Importing..." if on else "Syncing...")
        if not self.sync_job:
            for p in self.all_media_pages():
                p.set_syncing(on)

    def cancel_sync(self):
        dlg = getattr(self, "settings_dialog", None)
        if not self.sync_cancel and dlg is not None and getattr(dlg, "importing", False):
            dlg.cancel_import()
            return
        if self.sync_cancel:
            self.sync_cancel.set()
            self.sync_stage, self._pct = "Cancelling", -1
            self.show_sync_status()
            for p in self.all_media_pages():
                p.set_syncing(False)

    def sync_finished(self, text):
        self.state.reload()
        shown = self.page_for.get(self.current_key)
        for p in self.all_media_pages():
            if p is shown:
                p.reload()
                self._stale.discard(p)
            else:
                self._stale.add(p)                      # reloaded when you open it
        self.rebuild_groups()
        self.update_counts()
        self.sidebar.set_syncing(False)
        self.sync_job = self.sync_cancel = None
        for p in self.all_media_pages():
            p.set_syncing(False)
        self.add_log(text)

    def open_settings(self):
        if getattr(self, "settings_dialog", None) is not None:
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()
            return
        dlg = self.settings_dialog = SettingsDialog(self.state.cfg, self)
        dlg.note.connect(self.add_log)
        dlg.status.connect(self.show_status)
        dlg.progress.connect(self.sidebar.set_progress)
        dlg.busy.connect(lambda on: self._import_busy(on, dlg))

        def closed(result):
            self.settings_dialog = None
            if result:
                self.add_log("Settings saved")
            if dlg.imported:
                self.sync_finished("Data imported")
            dlg.deleteLater()
        dlg.finished.connect(closed)
        dlg.show()

    # ------------------------------------------------------------ window behaviour
    def showEvent(self, e):
        super().showEvent(e)
        round_window_corners(self)

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.WindowStateChange:
            self.titlebar.sync_state()
            round_window_corners(self)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        compact = self.width() < COMPACT_BELOW
        if compact != self.sidebar.compact:
            self.sidebar.set_compact(compact)

    def restore_geometry(self) -> bool:
        """Put the window back where it was when it was last closed. False when nothing usable is saved."""
        g = self.state.pref("window", None)
        try:
            rect = QRect(int(g["x"]), int(g["y"]), int(g["w"]), int(g["h"]))
        except (TypeError, KeyError, ValueError):
            return False
        if not any(s.availableGeometry().intersects(rect) for s in QGuiApplication.screens()):   # monitor gone: start centered
            return False
        self.setGeometry(rect)
        if g.get("max"):
            self.showMaximized()
        return True

    def closeEvent(self, e):
        r = self.normalGeometry() if self.isMaximized() else self.geometry()      # the restored size, not the maximized one
        self.state.set_pref("window", {"x": r.x(), "y": r.y(), "w": r.width(), "h": r.height(), "max": self.isMaximized()})
        super().closeEvent(e)

    def center_on_cursor_screen(self):
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        w, h = min(1440, int(area.width() * 0.92)), min(900, int(area.height() * 0.92))
        self.resize(w, h)
        self.move(area.x() + (area.width() - w) // 2, area.y() + (area.height() - h) // 2)


def apply_theme(app):
    app.setStyle("Fusion")
    for fx in (Qt.UIEffect.UI_AnimateCombo, Qt.UIEffect.UI_AnimateMenu, Qt.UIEffect.UI_FadeMenu, Qt.UIEffect.UI_AnimateTooltip, Qt.UIEffect.UI_FadeTooltip):
        app.setEffectEnabled(fx, False)      # the roll / fade animations snapshot the popup first, which flashes with rounded masks
    pal = QPalette()
    for role, col in ((QPalette.ColorRole.Window, theme.BG), (QPalette.ColorRole.Base, theme.SURFACE2),
                      (QPalette.ColorRole.Text, theme.TEXT), (QPalette.ColorRole.WindowText, theme.TEXT),
                      (QPalette.ColorRole.Button, theme.SURFACE2), (QPalette.ColorRole.ButtonText, theme.TEXT),
                      (QPalette.ColorRole.Highlight, theme.ACCENT), (QPalette.ColorRole.ToolTipBase, theme.SURFACE2),
                      (QPalette.ColorRole.ToolTipText, theme.TEXT)):
        pal.setColor(role, QColor(col))
    app.setPalette(pal)
    app.setStyleSheet(theme.QSS)


def main():
    if sys.platform == "win32":      # own taskbar identity so the Patchwork icon shows (not python's)
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("patchwork.app")
        except Exception:
            pass
    try:                                  # a hard crash leaves its stack in data/crash.log, so it can be diagnosed
        import faulthandler
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        global _crash_log
        _crash_log = open(DATA_DIR / "crash.log", "a", encoding="utf-8")
        _crash_log.write("\n--- started ---\n")
        _crash_log.flush()
        faulthandler.enable(_crash_log, all_threads=True)
        sys.excepthook = lambda *a: (__import__("traceback").print_exception(*a, file=_crash_log), _crash_log.flush())
    except Exception:
        pass
    app = QApplication(sys.argv)
    app.setApplicationName("Patchwork")
    app.setWindowIcon(QIcon(str(RES / "assets" / "icon.png")))
    apply_theme(app)
    win = MainWindow()
    if not win.restore_geometry():
        win.center_on_cursor_screen()
    win.show()
    sys.exit(app.exec())

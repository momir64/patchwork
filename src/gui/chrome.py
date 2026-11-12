"""Window chrome drawn by the app itself: title bar with window buttons, edge resizing, and frameless modal dialogs
(plus small replacements for the stock input / message boxes)."""
from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFontMetrics, QGuiApplication, QPainterPath, QPixmap, QRegion
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QComboBox, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton,
                               QToolTip, QVBoxLayout, QWidget)

from ..core.config import RES
from . import icons, theme
from . import widgets
from .widgets import button, label


def window_button(icon, tip, role="winbtn"):
    b = QPushButton()
    b.setObjectName(role)
    b.setIcon(icons.icon(icon, theme.MUTED, 15))
    b.setIconSize(QSize(15, 15))
    b.setToolTip(tip)
    b.setCursor(Qt.CursorShape.ArrowCursor)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    if role == "winclose":                          # white cross on the red hover, so it stays readable
        normal, bright = icons.icon(icon, theme.MUTED, 15), icons.icon(icon, "#ffffff", 15)
        b.enterEvent = lambda e, b=b, i=bright, f=b.enterEvent: (b.setIcon(i), f(e))
        b.leaveEvent = lambda e, b=b, i=normal, f=b.leaveEvent: (b.setIcon(i), f(e))
    return b


class DragBar(QWidget):
    """Empty bar that moves its window when dragged (and maximizes on double click when `maximizable`)."""

    def __init__(self, maximizable=False):
        super().__init__()
        self.maximizable = maximizable
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.window().windowHandle():
            self.window().windowHandle().startSystemMove()
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if self.maximizable and e.button() == Qt.MouseButton.LeftButton:
            w = self.window()
            w.showNormal() if w.isMaximized() else w.showMaximized()


class TitleBar(DragBar):
    """App title bar: logo + name on the left, minimize / maximize / close on the right."""

    def __init__(self, win):
        super().__init__(maximizable=True)
        self.win = win
        self.setObjectName("titlebar")
        self.setFixedHeight(40)
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 0, 0, 0)
        h.setSpacing(10)
        logo = QLabel()
        pm = QPixmap(str(RES / "assets" / "logo.png")).scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatio,
                                                                Qt.TransformationMode.SmoothTransformation)
        pm.setDevicePixelRatio(2.0)
        logo.setPixmap(pm)
        logo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        name = label("Patchwork", "brand")
        name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        h.addWidget(logo)
        h.addWidget(name)
        h.addStretch()
        self.btn_min = window_button("minus", "Minimize")
        self.btn_max = window_button("square", "Maximize")
        self.btn_close = window_button("x", "Close", "winclose")
        self.btn_min.clicked.connect(win.showMinimized)
        self.btn_max.clicked.connect(lambda: win.showNormal() if win.isMaximized() else win.showMaximized())
        self.btn_close.clicked.connect(win.close)
        for b in (self.btn_min, self.btn_max, self.btn_close):
            h.addWidget(b)

    def sync_state(self):
        maxed = self.win.isMaximized()
        self.btn_max.setIcon(icons.icon("restore" if maxed else "square", theme.MUTED, 15))
        self.btn_max.setToolTip("Restore" if maxed else "Maximize")


class EdgeResizer(QWidget):
    """Lets a frameless top-level window be resized from its edges and corners (done by hand: works the same everywhere).
    `inset` is the transparent margin around the visible frame (the shadow area of a dialog)."""

    def __init__(self, win, inset=(0, 0, 0, 0), margin=6, top_margin=None):
        super().__init__(win)
        self.hide()
        self.win, self.inset, self.margin = win, inset, margin
        self.top_margin = margin if top_margin is None else top_margin
        self.active, self.drag = False, None
        QGuiApplication.instance().installEventFilter(self)
        self.timer = QTimer(self, interval=30)
        self.timer.timeout.connect(self.update_cursor)
        self.timer.start()

    def release(self):
        """The window is closed: stop watching the whole app and give the cursor back."""
        self.timer.stop()
        QGuiApplication.instance().removeEventFilter(self)
        self.drag = None
        if self.active:
            QGuiApplication.restoreOverrideCursor()
            self.active = False

    def frame(self):
        l, t, r, b = self.inset
        return self.win.geometry().adjusted(l, t, -r, -b)

    def edges(self, pos=None):
        w = self.win
        if w.isMaximized() or w.isFullScreen() or not w.isVisible():
            return Qt.Edge(0)
        pos = pos or QCursor.pos()
        under = QGuiApplication.instance().widgetAt(pos)
        if under is None or under.window() is not w:
            return Qt.Edge(0)
        r, m = self.frame(), self.margin
        if not r.contains(pos):
            return Qt.Edge(0)
        e = Qt.Edge(0)
        if pos.x() - r.left() < m:
            e |= Qt.Edge.LeftEdge
        if r.right() - pos.x() < m:
            e |= Qt.Edge.RightEdge
        if pos.y() - r.top() < self.top_margin:
            e |= Qt.Edge.TopEdge
        if r.bottom() - pos.y() < m:
            e |= Qt.Edge.BottomEdge
        return e

    @staticmethod
    def shape(e):
        horiz = bool(e & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge))
        vert = bool(e & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge))
        if horiz and vert:
            main = e in (Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.Edge.RightEdge | Qt.Edge.BottomEdge)
            return Qt.CursorShape.SizeFDiagCursor if main else Qt.CursorShape.SizeBDiagCursor
        return Qt.CursorShape.SizeHorCursor if horiz else Qt.CursorShape.SizeVerCursor

    def update_cursor(self):
        if self.drag:
            return
        e = self.edges()
        if e:
            if self.active:
                QGuiApplication.changeOverrideCursor(QCursor(self.shape(e)))
            else:
                QGuiApplication.setOverrideCursor(QCursor(self.shape(e)))
                self.active = True
        elif self.active:
            QGuiApplication.restoreOverrideCursor()
            self.active = False

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
            e = self.edges(ev.globalPosition().toPoint())
            if e:
                self.drag = (e, ev.globalPosition().toPoint(), self.win.geometry())
                return True
        elif self.drag and t == QEvent.Type.MouseMove:
            self.resize_to(ev.globalPosition().toPoint())
            return True
        elif self.drag and t == QEvent.Type.MouseButtonRelease:
            self.drag = None
            return True
        return False

    def resize_to(self, pos):
        e, start, g0 = self.drag
        d = pos - start
        hint = self.win.minimumSizeHint()                # an explicit minimum size wins; otherwise what the content needs
        mw, mh = self.win.minimumWidth() or hint.width(), self.win.minimumHeight() or hint.height()
        g = g0.adjusted(0, 0, 0, 0)
        if e & Qt.Edge.LeftEdge:
            g.setLeft(min(g0.left() + d.x(), g0.right() - mw + 1))
        if e & Qt.Edge.RightEdge:
            g.setRight(max(g0.right() + d.x(), g0.left() + mw - 1))
        if e & Qt.Edge.TopEdge:
            g.setTop(min(g0.top() + d.y(), g0.bottom() - mh + 1))
        if e & Qt.Edge.BottomEdge:
            g.setBottom(max(g0.bottom() + d.y(), g0.top() + mh - 1))
        self.win.setGeometry(g)


def round_window_corners(win):
    """Windows 11: round the corners of a frameless window and keep its thin system border - but not when it fills
    the screen (maximized / fullscreen), where both would show as a gap or an outline at the screen edge."""
    try:
        import ctypes
        full = win.isMaximized() or win.isFullScreen()
        pref = ctypes.c_int(1 if full else 2)                       # DWMWCP_DONOTROUND / DWMWCP_ROUND
        border = ctypes.c_uint(0xFFFFFFFE if full else 0xFFFFFFFF)  # DWMWA_COLOR_NONE / DWMWA_COLOR_DEFAULT
        hwnd = int(win.winId())
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), 4)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(border), 4)
    except Exception:
        pass


WM_NCCALCSIZE = 0x0083


def enable_snapping(win):
    """Windows: dragging the title bar to a screen edge snaps the window (half, quarter, maximize) only for windows that have a
    sizing frame and min / max buttons in their style. A frameless window gets those here; the frame itself stays invisible
    because the client area is made to cover the whole window (see nc_calc_size). Other systems do their own thing."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        get, put = user32.GetWindowLongPtrW, user32.SetWindowLongPtrW
        get.restype, get.argtypes = ctypes.c_ssize_t, (wintypes.HWND, ctypes.c_int)
        put.restype, put.argtypes = ctypes.c_ssize_t, (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
        hwnd = wintypes.HWND(int(win.winId()))
        style = get(hwnd, -16)                                              # GWL_STYLE
        want = style | 0x00040000 | 0x00010000 | 0x00020000                 # WS_THICKFRAME | WS_MAXIMIZEBOX | WS_MINIMIZEBOX
        if want != style:
            put(hwnd, -16, want)
            user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020)   # no move / size / z-order / activate, frame changed
    except Exception:
        pass


def nc_calc_size(win, message) -> bool:
    """WM_NCCALCSIZE for a window made snappable by enable_snapping: the client area is the whole window (no visible frame).
    Maximized, Windows lays the window out a frame's width beyond the screen, so that part is cut off. True when handled."""
    try:
        import ctypes
        from ctypes import wintypes
        msg = wintypes.MSG.from_address(int(message))
        if msg.message != WM_NCCALCSIZE or not msg.wParam:
            return False
        user32 = ctypes.windll.user32
        hwnd = wintypes.HWND(msg.hwnd)                                        # (not win.winId(): that would come back in here)
        if user32.IsZoomed(hwnd):
            rect = wintypes.RECT.from_address(msg.lParam)                     # first of the proposed rectangles
            dpi = user32.GetDpiForWindow(hwnd) or 96
            frame = user32.GetSystemMetricsForDpi(32, dpi) + user32.GetSystemMetricsForDpi(92, dpi)   # SM_CXSIZEFRAME + SM_CXPADDEDBORDER
            rect.left += frame
            rect.top += frame
            rect.right -= frame
            rect.bottom -= frame
        return True
    except Exception:
        return False


class Polisher(QObject):
    """Application-wide touches: menus / dropdown popups get rounded translucent windows, and buttons only take keyboard
    focus once the user starts using the keyboard (so a dialog never opens with a highlighted button)."""

    def __init__(self):
        super().__init__()
        self.keys = False

    @staticmethod
    def release_combo(combo):
        """After a pick with the mouse the dropdown lets go of the focus (once the popup has finished closing)."""
        if widgets.KEYBOARD:
            return
        for ms in (0, 80):
            QTimer.singleShot(ms, lambda c=combo: c.clearFocus() if not c.view().isVisible() else None)

    TIP_WIDTH = 230

    @classmethod
    def wrap_tip(cls, text):
        """Plain tooltips are broken into lines of at most TIP_WIDTH pixels (existing line breaks stay)."""
        fm = QFontMetrics(QToolTip.font())
        out = []
        for para in text.split("\n"):
            line = ""
            for word in para.split(" "):
                trial = f"{line} {word}" if line else word
                if line and fm.horizontalAdvance(trial) > cls.TIP_WIDTH:
                    out.append(line)
                    line = word
                else:
                    line = trial
            out.append(line)
        return "\n".join(out)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Type.ToolTip and isinstance(obj, QWidget) and obj.toolTip() and "<" not in obj.toolTip():
            QToolTip.showText(ev.globalPos(), self.wrap_tip(obj.toolTip()), obj)         # a narrow tooltip instead of one long line
            return True
        if t == QEvent.Type.Polish and isinstance(obj, QWidget):
            if isinstance(obj, QMenu) and not obj.property("_rounded"):    # menus: rounded, translucent popup window
                obj.setProperty("_rounded", True)
                obj.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
                obj.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
                obj.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            if isinstance(obj, QComboBox) and not obj.property("_rounded"):
                obj.setProperty("_rounded", True)
                box = obj.view().window()               # the popup frame: rounded with a mask, so no window changes are needed
                box.installEventFilter(self)
                obj.activated.connect(lambda _=0, c=obj: self.release_combo(c))        # mouse users: no focus left behind
        elif t == QEvent.Type.Hide and isinstance(obj, QWidget) and obj.metaObject().className() == "QComboBoxPrivateContainer":
            if isinstance(obj.parentWidget(), QComboBox):         # the popup closed: Qt hands the focus back to the dropdown
                self.release_combo(obj.parentWidget())
        elif t in (QEvent.Type.Show, QEvent.Type.Resize) and isinstance(obj, QWidget) and                 obj.metaObject().className() == "QComboBoxPrivateContainer":
            path = QPainterPath()
            path.addRoundedRect(QRectF(obj.rect()), theme.RADIUS, theme.RADIUS)
            obj.setMask(QRegion(path.toFillPolygon().toPolygon()))
        elif t == QEvent.Type.MouseButtonPress and isinstance(obj, QWidget):
            combo = QApplication.focusWidget()                  # a click anywhere else lets go of a focused dropdown
            while combo is not None and not isinstance(combo, QComboBox):
                combo = combo.parentWidget()
            if combo is not None:
                w, inside = obj, False
                while w is not None and not inside:
                    inside = w is combo or w is combo.view().window()
                    w = w.parentWidget()
                if not inside:
                    combo.clearFocus()
        elif t == QEvent.Type.KeyPress and not self.keys and ev.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self.keys = True
            for w in QGuiApplication.instance().allWidgets():
                if isinstance(w, QPushButton) and w.focusPolicy() == Qt.FocusPolicy.NoFocus and w.objectName() not in ("winbtn", "winclose", "dlgclose"):
                    w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            widgets.KEYBOARD = True
        return False


# ====================================================================== modal dialogs
class Modal(QDialog):
    """Frameless rounded dialog with its own title bar and a soft shadow. Put content into `self.body`."""

    def __init__(self, parent, title, width=480, resizable=True, modal=True):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(modal)                            # modal=False: the main window stays usable while this is open
        self.setWindowTitle(title)
        self._placed = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 24)
        frame = QFrame()
        frame.setObjectName("dialog")
        shadow = QGraphicsDropShadowEffect(frame)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 190))
        frame.setGraphicsEffect(shadow)
        outer.addWidget(frame)
        fv = QVBoxLayout(frame)
        fv.setContentsMargins(0, 0, 0, 0)
        fv.setSpacing(0)
        bar = DragBar()
        bar.setObjectName("dlgbar")
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(22, 14, 14, 6)
        self.title_lbl = label(title, "dlgtitle")
        self.title_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.title_lbl.setFixedHeight(32)               # same height as the close button, so both centre on one line
        self.title_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        close = window_button("x", "Close", "dlgclose")
        close.clicked.connect(self.reject)
        bh.addWidget(self.title_lbl, 1, Qt.AlignmentFlag.AlignVCenter)
        bh.addWidget(close, 0, Qt.AlignmentFlag.AlignVCenter)
        fv.addWidget(bar)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(22, 6, 22, 20)
        self.body.setSpacing(12)
        fv.addLayout(self.body, 1)
        self.setMinimumWidth(min(width, 360) + 40)
        self.resize(width + 40, 100)
        if resizable:
            self.resizer = EdgeResizer(self, inset=(20, 16, 20, 24), margin=6)

    def done(self, result):
        r = getattr(self, "resizer", None)
        if r is not None:
            r.release()
        super().done(result)

    def footer(self, ok_text="OK", ok_icon=None, on_ok=None, on_cancel=None, extra=None, danger=False, cancel_text="Cancel"):
        self.body.addSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(8)
        if extra:
            extra.setContentsMargins(0, 0, 0, 0)
            extra.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft)
            row.addWidget(extra, 0, Qt.AlignmentFlag.AlignBottom)
        row.addStretch()
        cancel = None
        if cancel_text:
            cancel = button(cancel_text, None)
            cancel.clicked.connect(on_cancel or self.reject)
            row.addWidget(cancel)
        ok = button(ok_text, ok_icon, "dangerfill" if danger else "primary")
        ok.clicked.connect(on_ok or self.accept)
        row.addWidget(ok)
        width = max(116, ok.sizeHint().width() + 8, cancel.sizeHint().width() + 8 if cancel else 0)
        for b in (cancel, ok):                          # same width, with comfortable padding
            if b:
                b.setFixedWidth(width)
                b.setAutoDefault(False)
        ok.setDefault(True)
        self.body.addLayout(row)
        return ok

    def showEvent(self, e):
        super().showEvent(e)
        if not self._placed:                      # center over the main window, keep inside the screen
            self._placed = True
            hint = self.sizeHint()                       # grow to fit the content, but never shrink below the size asked for
            self.resize(max(self.width(), hint.width()), max(self.height(), hint.height()))
            par = self.parentWidget().window() if self.parentWidget() else None
            screen = (par.screen() if par else QGuiApplication.primaryScreen()).availableGeometry()
            if par:                                       # never bigger than about 90% of the main window
                self.resize(min(self.width(), int(par.width() * 0.9) + 40), min(self.height(), int(par.height() * 0.9) + 40))
            if self.width() > screen.width() - 40:
                self.resize(screen.width() - 60, self.height())
            if self.height() > screen.height() - 40:
                self.resize(self.width(), screen.height() - 60)
            c = par.frameGeometry().center() if par else screen.center()
            self.move(max(screen.left(), min(c.x() - self.width() // 2, screen.right() - self.width())),
                      max(screen.top(), min(c.y() - self.height() // 2, screen.bottom() - self.height())))


def _fit(text, minimum=420, maximum=None):
    """Dialog content width that shows `text` (possibly several lines) without wrapping, up to `maximum` (longer lines wrap)."""
    from PySide6.QtGui import QFontMetrics
    fm = QFontMetrics(QGuiApplication.font())
    width = max(minimum, max(fm.horizontalAdvance(line) for line in text.splitlines() or [""]) + 48)
    return min(width, maximum) if maximum else width


def _by_sentence(text):
    """One sentence per line (the first line, which may hold a title with dots in it, is left alone)."""
    import re
    first, *rest = text.split(chr(10))
    return chr(10).join([first] + [s for line in rest for s in re.split(r"(?<=[.!?])\s+", line)])


def confirm(parent, title, text, ok="OK", danger=False) -> bool:
    text = _by_sentence(text)
    d = Modal(parent, title, _fit(text, 380, 440), resizable=False)       # long messages wrap instead of widening the dialog
    d.body.addWidget(label(text, None, wrap=True))
    d.footer(ok, None, danger=danger)
    return bool(d.exec())


def notify(parent, title, text):
    text = _by_sentence(text)
    d = Modal(parent, title, _fit(text, 380, 440), resizable=False)
    d.body.addWidget(label(text, None, wrap=True))
    d.footer("OK", None, cancel_text=None)
    d.exec()


def ask_text(parent, title, prompt, text="", ok="OK"):
    """Single-line input. Returns the entered text, or None when cancelled / empty."""
    d = Modal(parent, title, _fit(prompt), resizable=False)
    d.body.addWidget(label(prompt, "muted"))
    edit = QLineEdit(text)
    edit.selectAll()
    edit.returnPressed.connect(d.accept)
    d.body.addWidget(edit)
    d.footer(ok, None)
    edit.setFocus()
    if d.exec() and edit.text().strip():
        return edit.text().strip()
    return None

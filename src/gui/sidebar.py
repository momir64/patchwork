"""Left navigation: libraries with their groups as subfolders, then Collage / Sync / Settings / Log at the bottom.
Collapses to icons on narrow windows."""
import zlib

from PySide6.QtCore import QMimeData, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QPainter, QPixmap
from PySide6.QtWidgets import (QBoxLayout, QButtonGroup, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from . import icons, theme
from .widgets import Btn, ProgressLine, section_header

FOLDER_COLORS = ["#ff5252", "#ff8c42", "#ffc933", "#7bd88f", "#40c9c6", "#5aa9ff", "#8b6cff", "#c77dff", "#ff6b9d"]     # rainbow order
COLOR_NAMES = ["Red", "Orange", "Amber", "Green", "Teal", "Blue", "Violet", "Orchid", "Pink"]
KIND_ICON = {"shows": "tv", "movies": "film", "albums": "disc", "images": "image"}


def folder_color(name: str) -> str:
    return FOLDER_COLORS[zlib.crc32(name.encode()) % len(FOLDER_COLORS)]


class BigNav(Btn):
    """Same look as the Sync button but a little taller; the filled accent look shows while its page is open."""

    def __init__(self, text, icon):
        super().__init__(text, icon, "bignav", height=40)
        self.setCheckable(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.name = text

    def set_compact(self, compact):
        self.setText("" if compact else self.name)


class ElidedLabel(QLabel):
    """A label that can be squeezed to any width: the text is cut with an ellipsis instead of widening the panel."""

    def __init__(self, text=""):
        super().__init__(text)
        self.full = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def setText(self, text):
        self.full = text
        self._elide()

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.full) + 2, super().sizeHint().height())

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()

    def _elide(self):
        shown = self.fontMetrics().elidedText(self.full, Qt.TextElideMode.ElideRight, max(0, self.width()))
        if shown != super().text():
            super().setText(shown)


class NavItem(QPushButton):
    """A nav row: icon + text + count (+ optional "+" button). Labels are children so spacing is exact."""
    plus_clicked = Signal()
    dropped = Signal(str, bool)           # name of the dragged group, dropped on the lower half of this row
    MIME = "application/x-patchwork-group"

    def __init__(self, text, icon, tint=None, role="nav", plus_tip=None, indent=12, drag_group=None):
        super().__init__()
        self.drag_group, self._press, self._drop = drag_group, None, None      # drag_group = (kind, name): this row can be dragged
        self.setAcceptDrops(drag_group is not None)
        self.setObjectName(role)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(text)
        self.icon_name, self.tint, self.sub, self.indent = icon, tint, role == "navsub", indent
        self.setFixedHeight(32 if role == "navsub" else 38)
        self.icon_size = 16 if self.sub else 19
        h = QHBoxLayout(self)
        h.setContentsMargins(indent, 0, 8, 0)
        h.setSpacing(10)
        self.ic, self.txt, self.cnt = QLabel(), ElidedLabel(text), QLabel("")
        self.cnt.setObjectName("count")
        self.ic.setFixedSize(20, 20)
        self.ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for w in (self.ic, self.txt, self.cnt):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        h.addWidget(self.ic)
        h.addWidget(self.txt, 1)
        h.addWidget(self.cnt)
        self.plus = None
        if plus_tip:
            self.plus = QPushButton()                       # expand / collapse the groups of this media type
            self.plus.setObjectName("mini")
            self.plus.setIcon(icons.icon("chevron-down", theme.MUTED, 15))
            self.plus.setToolTip(plus_tip)
            self.plus.setCursor(Qt.CursorShape.PointingHandCursor)
            self.plus.clicked.connect(self.plus_clicked)
            h.addWidget(self.plus)
        self._hover = self._held = False
        self.toggled.connect(lambda _: self._paint())
        self._paint()

    def _paint(self):
        checked = self.isChecked()
        self.ic.setPixmap(icons.pixmap(self.icon_name, self.tint or (theme.ACCENT_H if checked else theme.MUTED), self.icon_size))
        hl = self.objectName() == "navhl"
        on = checked or self._hover or self._held or hl
        weight = "font-weight: 600;" if (checked or hl) and not self.sub else ""
        self.txt.setStyleSheet(f"color: {theme.TEXT if on else theme.MUTED}; background: transparent; {weight}")
        self.cnt.setStyleSheet(f"color: {theme.MUTED if on else theme.DIM}; background: transparent;")

    def set_expanded(self, expanded):
        if self.plus:
            self.plus.setIcon(icons.icon("chevron-down" if expanded else "chevron-right", theme.MUTED, 15))
            self.plus.setToolTip("Hide groups" if expanded else "Show groups")

    def hold(self, on):
        """Keep the hovered look while this item's context menu is open (the menu steals the mouse)."""
        self._held = on
        self.setProperty("held", on)
        self.style().unpolish(self)
        self.style().polish(self)
        self._paint()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if (self.drag_group and self._press is not None and e.buttons() & Qt.MouseButton.LeftButton
                and (e.position().toPoint() - self._press).manhattanLength() > 8):
            self._press = None
            mime = QMimeData()
            mime.setData(self.MIME, f"{self.drag_group[0]}\n{self.drag_group[1]}".encode())
            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.setPixmap(self.grab())
            drag.setHotSpot(e.position().toPoint())
            self.setDown(False)
            drag.exec(Qt.DropAction.MoveAction)
            return
        super().mouseMoveEvent(e)

    def _dragged(self, e):
        """The group being dragged, if it is a sibling of this row (same media type)."""
        if not (self.drag_group and e.mimeData().hasFormat(self.MIME)):
            return None
        kind, _, name = bytes(e.mimeData().data(self.MIME)).decode().partition("\n")
        return name if kind == self.drag_group[0] and name != self.drag_group[1] else None

    def dragEnterEvent(self, e):
        if self._dragged(e):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if self._dragged(e):
            e.acceptProposedAction()
            drop = "after" if e.position().y() > self.height() / 2 else "before"
            if drop != self._drop:
                self._drop = drop
                self.update()

    def dragLeaveEvent(self, e):
        self._drop = None
        self.update()

    def dropEvent(self, e):
        name, after = self._dragged(e), self._drop == "after"
        self._drop = None
        self.update()
        if name:
            e.acceptProposedAction()
            self.dropped.emit(name, after)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._drop:                                   # insertion line where the dragged group will land
            p = QPainter(self)
            p.setPen(QColor(theme.ACCENT_H))
            y = 1 if self._drop == "before" else self.height() - 2
            p.drawLine(self.indent, y, self.width() - 8, y)

    def enterEvent(self, e):
        self._hover = True
        self._paint()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self._paint()
        super().leaveEvent(e)

    def sizeHint(self):                      # QPushButton would otherwise insist on a minimum width of ~80px
        return QSize(self.layout().sizeHint().width(), self.height())

    def minimumSizeHint(self):
        return QSize(self.layout().minimumSize().width(), self.height())

    def set_count(self, n):
        self.cnt.setText("" if n is None else str(n))

    def set_compact(self, compact):
        self.txt.setVisible(not compact)
        self.cnt.setVisible(not compact)
        if self.plus:
            self.plus.setVisible(not compact)
        h = self.layout()
        h.setContentsMargins(0, 0, 0, 0) if compact else h.setContentsMargins(self.indent, 0, 8, 0)
        if compact:
            h.setAlignment(self.ic, Qt.AlignmentFlag.AlignCenter)


class Grip(QWidget):
    """Invisible strip on the right edge of the panel: drag it to change the panel's width."""
    W = 6

    def __init__(self, bar):
        super().__init__(bar)
        self.bar, self.start = bar, None
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.setToolTip("Drag to resize")

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.start = (e.globalPosition().x(), self.bar.width())

    def mouseMoveEvent(self, e):
        if self.start:
            x0, w0 = self.start
            self.bar.set_wide(w0 + e.globalPosition().x() - x0)

    def mouseReleaseEvent(self, e):
        if self.start:
            self.start = None
            self.bar.width_changed.emit(self.bar.wide)


class Sidebar(QWidget):
    navigate = Signal(str)
    new_group = Signal(str)                # kind
    expanded_changed = Signal(str, bool)   # kind, groups shown
    group_menu = Signal(str, str, QPoint)  # kind, name, global pos
    group_moved = Signal(str, str, str, bool)   # kind, dragged group, target group, after the target
    sync_clicked = Signal()
    sync_options = Signal()
    settings_clicked = Signal()
    log_clicked = Signal()
    WIDE, NARROW = 256, 68
    MIN_WIDE, MAX_WIDE, STACK_BELOW = 200, 420, 232
    width_changed = Signal(int)             # the panel was dragged to a new width (saved by the app)

    def __init__(self, titles):
        super().__init__()
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)     # custom QWidget subclasses ignore QSS backgrounds without this
        self.compact = False
        self.wide = self.WIDE
        self.grip = Grip(self)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.items, self.group_items, self.group_boxes = {}, {}, {}
        self.expanded = {}

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 14, 12, 12)
        v.setSpacing(2)

        # ---- libraries, each with its groups underneath like subfolders
        self.sec_lib = section_header("Library")
        v.addWidget(self.sec_lib)
        v.addSpacing(4)
        nav = QVBoxLayout()
        nav.setContentsMargins(0, 0, 0, 0)
        nav.setSpacing(2)
        for kind, icon in KIND_ICON.items():
            it = NavItem(titles[kind], icon, plus_tip="Hide groups")
            it.clicked.connect(lambda _=False, k=kind: self.navigate.emit(k))
            it.plus_clicked.connect(lambda k=kind: self.toggle_groups(k))
            it.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            it.customContextMenuRequested.connect(lambda pos, w=it, k=kind: self._kind_menu(w, k, pos))
            self.group.addButton(it)
            self.items[kind] = it
            nav.addWidget(it)
            box = QVBoxLayout()
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(1)
            nav.addLayout(box)
            self.group_boxes[kind] = box
        nav.addStretch()
        inner = QWidget()
        inner.setLayout(nav)
        inner.setAutoFillBackground(False)
        inner.setObjectName("navinner")
        inner.setStyleSheet("QWidget#navinner { background: transparent; }")     # let the sidebar color show through the scroll area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(inner)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        v.addWidget(self.scroll, 1)
        v.addSpacing(8)

        # ---- bottom block: collage, sync, status, settings + log
        self.collage_btn = BigNav("Collage", "mosaic")          # same look as the library rows above, so selected states match
        self.collage_btn.setToolTip("Build a collage")
        self.collage_btn.clicked.connect(lambda: self.navigate.emit("collage"))
        self.group.addButton(self.collage_btn)
        self.items["collage"] = self.collage_btn
        v.addWidget(self.collage_btn)
        v.addSpacing(8)

        self.syncing = False
        self.sync_btn = Btn("Sync", "sync", height=40)
        self.sync_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.sync_btn.clicked.connect(self.sync_clicked)
        self.opts_btn = Btn("", "sliders", "icon", "Choose what to sync...", height=40)
        self.opts_btn.clicked.connect(self.sync_options)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.sync_btn, 1)
        row.addWidget(self.opts_btn)
        v.addLayout(row)

        self.progress = ProgressLine()
        sp = self.progress.sizePolicy()
        sp.setRetainSizeWhenHidden(True)                 # the line's slot stays reserved, so nothing below it jumps
        self.progress.setSizePolicy(sp)
        self.progress.hide()
        v.addSpacing(6)
        v.addWidget(self.progress)
        v.addSpacing(2)

        self.settings_btn = Btn("Settings", "settings", "ghost")
        self.log_btn = Btn("Logs", "list", "ghost", "Show the activity logs")
        for b in (self.settings_btn, self.log_btn):
            b.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)      # share the width whatever it is: never widen the panel
        self.settings_btn.clicked.connect(self.settings_clicked)
        self.log_btn.clicked.connect(self.log_clicked)
        self.foot = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.foot.setSpacing(4)
        self.foot.addWidget(self.settings_btn, 1)
        self.foot.addWidget(self.log_btn, 1)
        v.addLayout(self.foot)
        self.set_compact(False)

    # ------------------------------------------------------------ content
    def set_counts(self, counts):
        for k, n in counts.items():
            self.items[k].set_count(n)

    def set_groups(self, kind, groups):
        """groups: [(name, count, color)] of one category."""
        for key in [k for k in self.group_items if k.startswith(f"group:{kind}:")]:
            it = self.group_items.pop(key)
            self.group.removeButton(it)
            it.deleteLater()
        for name, n, color in groups:
            it = NavItem(name, "folder", tint=color, role="navsub", indent=34, drag_group=(kind, name))
            it.dropped.connect(lambda src, after, k=kind, nme=name: self.group_moved.emit(k, src, nme, after))
            it.set_count(n)
            key = f"group:{kind}:{name}"
            it.clicked.connect(lambda _=False, k=key: self.navigate.emit(k))
            it.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            it.customContextMenuRequested.connect(lambda pos, w=it, k=kind, nme=name: self._open_menu(w, k, nme, pos))
            it.set_compact(self.compact)
            self.group.addButton(it)
            self.group_items[key] = it
            self.group_boxes[kind].addWidget(it)
        self._apply_expanded()

    def toggle_groups(self, kind):
        self.expanded[kind] = not self.expanded.get(kind, True)
        self._apply_expanded()
        self.expanded_changed.emit(kind, self.expanded[kind])

    def set_expanded(self, state: dict):
        self.expanded.update(state)
        self._apply_expanded()

    def _apply_expanded(self):
        """Each media type shows or hides its groups with its own chevron."""
        for key, it in self.group_items.items():
            it.setVisible(self.expanded.get(key.split(":")[1], True))
        for kind, item in self.items.items():
            if kind in self.group_boxes:
                item.set_expanded(self.expanded.get(kind, True))

    def _kind_menu(self, item, kind, pos):
        item.hold(True)
        menu = QMenu(self)
        menu.addAction(icons.icon("plus", theme.MUTED, 16), "New group...", lambda: self.new_group.emit(kind))
        open_ = self.expanded.get(kind, True)
        menu.addAction(icons.icon("chevron-right" if open_ else "chevron-down", theme.MUTED, 16),
                       "Hide groups" if open_ else "Show groups", lambda: self.toggle_groups(kind))
        menu.exec(item.mapToGlobal(pos))
        item.hold(False)

    def _open_menu(self, item, kind, name, pos):
        item.hold(True)
        self.group_menu.emit(kind, name, item.mapToGlobal(pos))     # blocks until the menu closes
        item.hold(False)

    def set_current(self, key):
        it = self.items.get(key) or self.group_items.get(key)
        if it:
            it.setChecked(True)

    def set_syncing(self, busy, cancelling=False, text="Syncing..."):
        self.syncing = busy
        self.busy_text = text
        self.sync_btn.setEnabled(not busy)
        self.opts_btn.setEnabled(not busy)
        if not self.compact:
            self.sync_btn.setText(text if busy else "Sync")
        if not busy:
            self.progress.hide()

    def set_progress(self, a, b):
        self.progress.show()
        self.progress.setRange(0, b)
        self.progress.setValue(a)

    def set_wide(self, w):
        """Width of the full (not compact) panel."""
        self.wide = max(self.MIN_WIDE, min(self.MAX_WIDE, int(w)))
        if not self.compact:
            self.setFixedWidth(self.wide)
            self._foot_direction()

    def _foot_direction(self):
        """Settings and Log sit side by side while there is room for both labels, else one above the other."""
        side = not self.compact and self.wide >= self.STACK_BELOW
        self.foot.setDirection(QBoxLayout.Direction.LeftToRight if side else QBoxLayout.Direction.TopToBottom)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.grip.setGeometry(self.width() - Grip.W, 0, Grip.W, self.height())
        self.grip.raise_()

    def set_compact(self, compact):
        self.compact = compact
        self.grip.setVisible(not compact)
        self.setFixedWidth(self.NARROW if compact else self.wide)
        for w in (self.sec_lib, self.opts_btn):
            w.setVisible(not compact)
        self.sync_btn.setText("" if compact else (getattr(self, "busy_text", "Syncing...") if self.syncing else "Sync"))
        self.collage_btn.set_compact(compact)
        self.settings_btn.setText("" if compact else "Settings")
        self.log_btn.setText("" if compact else "Logs")
        self._foot_direction()
        for it in (*(i for k, i in self.items.items() if k != "collage"), *self.group_items.values()):
            it.set_compact(compact)
        self.layout().setContentsMargins(*((10, 14, 10, 12) if compact else (12, 14, 12, 12)))

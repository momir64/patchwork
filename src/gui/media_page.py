"""Poster wall - one component for a media library (Shows / Movies / Albums) and for a group (mixed kinds)."""
import math
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QTimer, QModelIndex, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListView,
                               QMenu, QMessageBox, QPushButton, QSizePolicy, QSlider, QStackedLayout, QStyle, QStyledItemDelegate,
                               QVBoxLayout, QWidget)

from ..core import covers, editions
from ..core.library import title_from_label
from ..core.names import norm_key, safe_filename, sort_key
from . import icons, theme
from .chrome import ask_text, confirm, notify
from .widgets import Btn, FlowLayout, SearchCombo, SearchBox, Segmented, StatusLabel, button, label

ROLE_KIND = Qt.ItemDataRole.UserRole
ROLE_LABEL = ROLE_KIND + 1
ROLE_FAV = ROLE_KIND + 2
ROLE_SEL = ROLE_KIND + 3
ROLE_PIX = ROLE_KIND + 4
ROLE_SUB = ROLE_KIND + 5
ALL = "__all__"
KIND_ICON = {"shows": "tv", "movies": "film", "albums": "disc"}


def display_title(lib, label):
    return lib.name(label)


def display_sub(lib, label):
    m = lib.meta.get(label)
    if lib.kind == "albums":
        return (m.get("creators") or [""])[0]
    bits = [str(m["year"]) if m.get("year") else "", (lib.meta.values(label, "genre") or [""])[0]]
    return "  ·  ".join(b for b in bits if b)


def tooltip(lib, label):
    m = lib.meta.get(label)
    lines = [f"<b>{display_title(lib, label)}</b>"]
    for key, name in (("year", "Year"), ("genres", "Genres"), ("countries", "Countries"), ("languages", "Languages"),
                      ("creators", {"albums": "Artist", "movies": "Director"}.get(lib.kind, "Creators")), ("studio", "Studio")):
        v = lib.meta.values(label, "genre") if (key == "genres" and lib.kind == "albums") else m.get(key)
        if v:
            lines.append(f"<span style='color:{theme.MUTED}'>{name}:</span> {', '.join(v) if isinstance(v, list) else v}")
    try:
        r = float(m.get("rating") or 0)
    except (TypeError, ValueError):
        r = 0
    if r > 0:
        lines.append(f"<span style='color:{theme.MUTED}'>Rating:</span> {r:.1f}")
    return "<br>".join(lines)


class ItemModel(QAbstractListModel):
    def __init__(self, state):
        super().__init__()
        self.state, self.items, self.sel, self.rows_by_path = state, [], set(), {}
        state.thumbs.loaded.connect(self._thumb_ready)

    def set_items(self, items):
        self.beginResetModel()
        self.items, self.rows_by_path = items, {}
        for r, (k, l) in enumerate(items):
            p = self.state.poster(k, l)
            if p:
                self.rows_by_path.setdefault(str(p), []).append(r)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        kind, label_ = self.items[index.row()]
        lib = self.state.libs[kind]
        if role == Qt.ItemDataRole.DisplayRole:
            return display_title(lib, label_)
        if role == ROLE_KIND:
            return kind
        if role == ROLE_LABEL:
            return label_
        if role == ROLE_SUB:
            return display_sub(lib, label_)
        if role == Qt.ItemDataRole.ToolTipRole:
            return tooltip(lib, label_)
        if role == ROLE_FAV:
            return lib.is_fav(label_)
        if role == ROLE_SEL:
            return (kind, label_) in self.sel
        if role == ROLE_PIX:
            p = lib.poster(label_)
            return self.state.thumbs.get(p) if p else None
        return None

    def touch(self, row):
        i = self.index(row)
        self.dataChanged.emit(i, i)

    def touch_all(self):
        if self.items:
            self.dataChanged.emit(self.index(0), self.index(len(self.items) - 1))

    def _thumb_ready(self, key):
        for r in self.rows_by_path.get(key, []):
            self.touch(r)


def star_path(cx, cy, r):
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.45
        pts.append(QPointF(cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    path = QPainterPath(pts[0])
    for p in pts[1:]:
        path.lineTo(p)
    path.closeSubpath()
    return path


def two_lines(fm, text, w):
    words, line, i = text.split(), "", 0
    while i < len(words) and fm.horizontalAdvance((line + " " + words[i]).strip()) <= w:
        line = (line + " " + words[i]).strip()
        i += 1
    if not line:
        return [fm.elidedText(text, Qt.TextElideMode.ElideRight, w)]
    rest = " ".join(words[i:])
    return [line] + ([fm.elidedText(rest, Qt.TextElideMode.ElideRight, w)] if rest else [])


SORTS = {
    "video": (("Title A–Z", "az"), ("Title Z–A", "za"), ("Released: newest", "year_new"), ("Released: oldest", "year_old"),
              ("Highest rated", "rating"), ("Added: newest", "added_new"), ("Added: oldest", "added_old"), ("Favorites first", "favs")),
    "albums": (("Title A–Z", "az"), ("Title Z–A", "za"), ("Artist A–Z", "artist"), ("Most played", "plays_most"),
               ("Least played", "plays_least"), ("Added: newest", "added_new"), ("Added: oldest", "added_old"), ("Color: rainbow", "hue"), ("Color: dark to light", "bright"),
               ("Favorites first", "favs")),
}


class CardDelegate(QStyledItemDelegate):
    PAD, GAP, TEXT_H = 8, 8, 54

    def __init__(self, square: bool):
        super().__init__()
        self.square, self.width, self.base = square, 170, 170     # width = actual card width, base = chosen size
        self.hover_row = -1                                        # the card under the mouse (set by the view)
        self._title_font = QFont()
        self._title_font.setPixelSize(13)
        self._title_font.setWeight(QFont.Weight.DemiBold)
        self._title_fm = QFontMetrics(self._title_font)
        self._sub_font = QFont()
        self._sub_font.setPixelSize(11)
        self._lines_cache, self._scaled = {}, OrderedDict()        # wrapped captions, poster pixmaps already scaled to the card

    def poster_h(self):
        return self.width if self.square else int(self.width * 1.5)

    def cell_size(self):
        return QSize(self.width + 2 * self.PAD, self.poster_h() + self.GAP + self.TEXT_H + 2 * self.PAD)

    def sizeHint(self, option, index):
        return self.cell_size()

    def poster_rect(self, cell):
        return QRect(cell.left() + self.PAD, cell.top() + self.PAD, self.width, self.poster_h())

    def caption_h(self, index):
        """Height the caption really needs (1-2 title lines, plus the small line when there is one)."""
        n = len(self.lines(index.data() or "", self.width - 4))
        return 17 * max(1, n) + (16 if index.data(ROLE_SUB) else 0)

    def lines(self, text, w):
        key = (text, w)
        out = self._lines_cache.get(key)
        if out is None:
            if len(self._lines_cache) > 4000:
                self._lines_cache.clear()
            out = self._lines_cache[key] = two_lines(self._title_fm, text, w)
        return out

    def scaled(self, pm, size, mode):
        key = (pm.cacheKey(), size.width(), size.height(), mode)
        s = self._scaled.get(key)
        if s is None:
            s = pm.scaled(size, mode, Qt.TransformationMode.SmoothTransformation)
            self._scaled[key] = s
            while len(self._scaled) > 300:
                self._scaled.popitem(last=False)
        else:
            self._scaled.move_to_end(key)
        return s

    def hit_rect(self, cell, index=None):
        """The visible card (poster + the caption text); the padding and unused caption space belong to the empty space."""
        cap = self.caption_h(index) if index is not None else self.TEXT_H
        return QRect(cell.left() + self.PAD, cell.top() + self.PAD, self.width, self.poster_h() + self.GAP + cap)

    def star_rect(self, cell):
        pr = self.poster_rect(cell)
        return QRect(pr.right() - 36, pr.top() + 8, 28, 28)

    def paint(self, p: QPainter, opt, index):
        p.save()
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.TextAntialiasing)
        pr = self.poster_rect(opt.rect)
        shape = QPainterPath()
        shape.addRoundedRect(QRectF(pr), 7, 7)
        p.fillPath(shape, QColor(theme.SURFACE2))
        pm = index.data(ROLE_PIX)
        kind = index.data(ROLE_KIND)
        if pm is not None and not pm.isNull():
            p.setClipPath(shape)
            mode = Qt.AspectRatioMode.KeepAspectRatio if (kind == "albums" and not self.square) else Qt.AspectRatioMode.KeepAspectRatioByExpanding
            s = self.scaled(pm, pr.size(), mode)
            p.drawPixmap(pr.left() + (pr.width() - s.width()) // 2, pr.top() + (pr.height() - s.height()) // 2, s)
            p.setClipping(False)
        else:
            ic = icons.pixmap("image", theme.DIM, 28)
            p.drawPixmap(pr.center().x() - 14, pr.center().y() - 22, ic)
            f = QFont(p.font())
            f.setPixelSize(11)
            p.setFont(f)
            p.setPen(QColor(theme.DIM))
            p.drawText(QRect(pr.left(), pr.center().y() + 10, pr.width(), 18), Qt.AlignmentFlag.AlignCenter,
                       "loading..." if index.data(ROLE_PIX) is None and self._has_poster(index) else "no poster")
        hovered = index.row() == self.hover_row
        selected = index.data(ROLE_SEL)
        if selected:
            p.fillPath(shape, QColor(139, 108, 255, 60))
            p.setPen(QPen(QColor(theme.ACCENT), 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(pr).adjusted(1.5, 1.5, -1.5, -1.5), 6, 6)
            c = QRectF(pr.left() + 9, pr.top() + 9, 22, 22)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.ACCENT))
            p.drawEllipse(c)
            p.setPen(QPen(QColor("white"), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline([QPointF(c.left() + 6, c.top() + 11.5), QPointF(c.left() + 9.5, c.top() + 15), QPointF(c.left() + 16, c.top() + 7.5)])
        elif hovered:
            p.setPen(QPen(QColor(255, 255, 255, 60), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(pr).adjusted(1, 1, -1, -1), 6, 6)
        fav = index.data(ROLE_FAV)
        if fav or hovered:
            sr = self.star_rect(opt.rect)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(10, 12, 18, 170))
            p.drawEllipse(sr)
            sp = star_path(sr.center().x() + 0.5, sr.center().y() + 0.5, 8.5)
            col = QColor(theme.GOLD) if fav else QColor(255, 255, 255, 150)
            if fav:
                p.setPen(QPen(col, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                p.setBrush(col)
            else:
                p.setPen(QPen(col, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(sp)
        # ---- text
        tx, tw = pr.left() + 2, pr.width() - 4
        p.setFont(self._title_font)
        y = pr.bottom() + self.GAP
        p.setPen(QColor(theme.TEXT if selected else "#d5d9e6"))
        for line in self.lines(index.data() or "", tw):
            p.drawText(QRect(tx, y, tw, 17), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, line)
            y += 17
        y += 1
        sub = index.data(ROLE_SUB)
        if sub:
            p.setFont(self._sub_font)
            p.setPen(QColor(theme.DIM))
            p.drawText(QRect(tx, y, tw, 15), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       QFontMetrics(self._sub_font).elidedText(sub, Qt.TextElideMode.ElideRight, tw))
        p.restore()

    @staticmethod
    def _has_poster(index):
        return True


class CardView(QListView):
    cardClicked = Signal(QModelIndex, object)
    starClicked = Signal(QModelIndex)
    emptyClicked = Signal()

    def __init__(self, delegate):
        super().__init__()
        self.card = delegate
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setSelectionMode(QListView.SelectionMode.NoSelection)
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)
        self.setItemDelegate(delegate)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(48)
        self.setFrameShape(QListView.Shape.NoFrame)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def apply_zoom(self):
        """Cards are at least the chosen size; the leftover width is shared out so every row fills the view."""
        d = self.card
        avail = max(1, self.width() - 2 * self.frameWidth() - 18)     # 18 = room for the scrollbar
        cols = max(1, avail // (d.base + 2 * d.PAD))
        d.width = max(60, avail // cols - 2 * d.PAD)
        if self.gridSize() != d.cell_size():
            self.setGridSize(d.cell_size())
            self.doItemsLayout()
        self.viewport().update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.apply_zoom()

    def item_at(self, pos):
        """Index of the card under pos, or an invalid index over empty space (gaps, padding, below the last row)."""
        idx = self.indexAt(pos)
        if idx.isValid() and self.card.hit_rect(self.visualRect(idx), idx).contains(pos):
            return idx
        return QModelIndex()

    def _set_hover(self, row):
        if row != self.card.hover_row:
            self.card.hover_row = row
            self.viewport().update()

    def mouseMoveEvent(self, e):
        self._set_hover(self.item_at(e.position().toPoint()).row())
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self._set_hover(-1)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            pos = e.position().toPoint()
            idx = self.item_at(pos)
            if idx.isValid():
                if self.card.star_rect(self.visualRect(idx)).contains(pos):
                    self.starClicked.emit(idx)
                else:
                    self.cardClicked.emit(idx, e.modifiers())
            else:
                self.emptyClicked.emit()
            return
        super().mousePressEvent(e)


class MediaPage(QWidget):
    """kind=... shows one library; group=(kind, name) shows the members of one group (a group has one category)."""
    data_changed = Signal()
    groups_changed = Signal()
    group_deleted = Signal(str, str)
    group_renamed = Signal(str, str, str)
    log = Signal(str)
    cancel_sync = Signal()

    def __init__(self, state, kind=None, group=None, lazy=False):
        super().__init__()
        self.state, self.kind, self.group = state, kind, group
        self.cat = kind or group[0]                     # the category (shows / movies / albums) of everything on this page
        self.lib = state.libs[self.cat]
        self.sel, self.last_row, self.last_on = set(), None, True
        self._sel_now, self._sel_history, self._sel_redo = frozenset(), [], []        # for Ctrl+Z
        self.model = ItemModel(state)
        self.model.sel = self.sel
        self.delegate = CardDelegate(square=(self.cat == "albums"))
        self.delegate.base = state.pref("zoom", 170)
        self.view = CardView(self.delegate)
        self.view.setModel(self.model)
        self.view.cardClicked.connect(self.on_card)
        self.view.starClicked.connect(self.on_star)
        self.view.customContextMenuRequested.connect(self.on_menu)
        self.view.emptyClicked.connect(self.clear_selection)

        # ------------------------------------------------ header
        self.icon_lbl = QLabel()
        self.icon_lbl.setPixmap(icons.pixmap(KIND_ICON[self.cat], theme.ACCENT, 24) if kind else icons.pixmap("folder", state.group_color(self.cat, group[1]), 24))
        self.title = label(self.lib.title if kind else group[1], "h1")
        self.count = label("", "chip")
        self.search = SearchBox("Search title, genre, country, creator...")
        self.search.setMinimumWidth(330)
        self.search.setMaximumWidth(460)
        self._search_timer = QTimer(self)                         # wait for a pause in typing instead of filtering on every key
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(120)
        self._search_timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda *_: self._search_timer.start())
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(self.icon_lbl)
        head.addWidget(self.title)
        head.addWidget(self.count)
        head.addStretch(3)
        self.zoom_box = self._zoom_box()
        head.addWidget(self.zoom_box)
        head.addWidget(self.search, 1)
        if kind:
            dup = button("Duplicates", "layers", tip="Find items that exist more than once (editions, with / without a year) and merge them")
            dup.clicked.connect(self.merge_duplicates)
            head.addWidget(dup)
        if kind:
            add = button("Add", "plus", tip="Add an item by hand")
            add.clicked.connect(self.add_item)
            head.addWidget(add)
            lf = button("", "external", "icon", "Show the list as a txt file (hidden items left out)")
            lf.clicked.connect(self.open_list_file)
            head.addWidget(lf)
        else:
            for ic, fn, tip in (("edit", self.rename_group, "Rename group"),
                                ("external", self.open_group_file, "Show the group's txt file"),
                                ("trash", self.delete_group, "Delete group")):
                b = button("", ic, "icon", tip)
                b.clicked.connect(fn)
                head.addWidget(b)

        # ------------------------------------------------ toolbar (wraps when narrow)
        self.mode = Segmented([("All", "all"), ("Favorites", "favs"), ("Selected", "sel"), ("No poster", "nopic"), ("Hidden", "hidden"), ("Duplicates", "dups")], "all")
        self.mode.set_value(getattr(state, "tab", "all"), emit=False)     # the tab is shared by every page
        self.mode.changed.connect(lambda v: setattr(state, "tab", v))
        self.mode.changed.connect(self.refresh)
        bar = QWidget()
        flow = FlowLayout(bar, 8)
        flow.addWidget(self.mode)
        self.sort_cb = QComboBox()
        self.sort_cb.setMinimumWidth(150)
        for text, key in SORTS["albums" if self.cat == "albums" else "video"]:
            self.sort_cb.addItem(text, key)
        self.sort_cb.setToolTip("Sort order")
        self.sort_cb.currentIndexChanged.connect(self.refresh)
        flow.addWidget(self.sort_cb)
        self.facets = {}
        for facet in ("genre", "country", "language"):
            cb = SearchCombo()
            cb.setMinimumWidth(140)
            cb.currentIndexChanged.connect(self.refresh)
            self.facets[facet] = cb
            flow.addWidget(cb)
        self.group_cb = QComboBox()
        self.group_cb.setMinimumWidth(140)
        self.group_cb.currentIndexChanged.connect(self.refresh)
        if kind:
            flow.addWidget(self.group_cb)

        # ------------------------------------------------ body (wall + empty state)
        self.empty = label("", "muted", wrap=True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack = QStackedLayout()
        self.stack.addWidget(self.view)
        self.stack.addWidget(self.empty)

        # ------------------------------------------------ action bar: count + clear, then the actions, all on the left
        self.info = label("", "muted")
        self.btn_all = button("Select all", "check", tip="Select / unselect everything currently shown")
        self.btn_fav = button("Favorite", "star", tip="Toggle favorite for the selected items")
        self.btn_group = button("Add to group", "folder", tip="Add the selected items to a group")
        self.btn_unlink = button("Remove from group", "minus-circle", tip="Remove the selected items from this group")
        self.btn_fav.clicked.connect(self.toggle_fav_selected)
        self.btn_group.clicked.connect(self.group_menu)
        self.btn_unlink.clicked.connect(self.remove_from_group)
        self.btn_all.clicked.connect(self.toggle_select_all)
        sc = QShortcut(QKeySequence.StandardKey.SelectAll, self)       # Ctrl+A (a text field that has focus keeps its own select-all)
        sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc.activated.connect(self.select_all)
        undo = QShortcut(QKeySequence.StandardKey.Undo, self)          # Ctrl+Z: back to the previous selection
        undo.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        undo.activated.connect(self.undo_selection)
        redo = QShortcut(QKeySequence.StandardKey.Redo, self)          # Ctrl+Y / Ctrl+Shift+Z
        redo.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        redo.activated.connect(lambda: self.undo_selection(redo=True))
        self.btn_unlink.setVisible(bool(group))
        actions = QWidget()
        actions.setObjectName("bar")
        self.actions_bar = actions
        ah = self.ah = QHBoxLayout(actions)
        ah.setContentsMargins(24, 12, 24, 12)
        ah.setSpacing(8)
        self.status = StatusLabel()
        self.cancel_btn = Btn("", "x", "ghost", "Cancel the sync", size=14, height=28, pad=0)
        self.cancel_btn.setFixedSize(28, 28)
        self.cancel_btn.clicked.connect(self.cancel_sync)
        self.cancel_btn.hide()
        ah.addWidget(self.cancel_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        ah.addWidget(self.status, 1, Qt.AlignmentFlag.AlignVCenter)                    # latest message (sync, saved, favorites...) on the left
        ah.addWidget(self.info)
        ah.addSpacing(8)
        for b in (self.btn_all, self.btn_fav, self.btn_group, self.btn_unlink):
            ah.addWidget(b)
        self.compact = False

        body = QVBoxLayout()
        body.setContentsMargins(24, 20, 6, 0)            # the scrollbar sits close to the window edge
        body.setSpacing(16)
        top = QVBoxLayout()                              # header and filter bar keep the full right margin
        top.setContentsMargins(0, 0, 18, 0)
        top.setSpacing(16)
        top.addLayout(head)
        top.addWidget(bar)
        body.addLayout(top)
        body.addLayout(self.stack, 1)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addLayout(body, 1)
        root.addWidget(actions)
        self.view.apply_zoom()
        self.lazy = lazy                                  # lazy: the first reload waits until the page is shown
        if not lazy:
            self.reload()

    def _zoom_box(self):
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 4, 0)
        h.setSpacing(8)
        small, big = QLabel(), QLabel()
        small.setPixmap(icons.pixmap("grid", theme.DIM, 14))
        big.setPixmap(icons.pixmap("grid", theme.DIM, 20))
        zoom = QSlider(Qt.Orientation.Horizontal)
        zoom.setRange(60, 260)
        zoom.setValue(self.delegate.base)
        zoom.setFixedSize(100, 34)
        zoom.setToolTip("Poster size")
        zoom.valueChanged.connect(self.set_zoom)
        self.zoom = zoom
        self.state.zoom_changed.connect(self._zoom_from_other)
        for w in (small, zoom, big):
            h.addWidget(w)
        return box

    # ------------------------------------------------------------ source of items
    def all_items(self, hidden=False, dups=False):
        """The items of this page. Normally the shown ones; hidden=True gives the ones you hid yourself; dups=True gives
        the ones the duplicates dialog hid."""
        have = set(self.lib.items)
        names = self.lib.items if self.kind else [l for l in self.state.groups.members(*self.group) if l in have]
        auto = {norm_key(l) for l in editions.load_dup_hidden(self.cat)} if self.lib.hidden else set()   # hidden by the duplicates dialog
        if dups:
            return [(self.cat, l) for l in names if self.lib.is_hidden(l) and norm_key(l) in auto]
        if hidden:
            return [(self.cat, l) for l in names if self.lib.is_hidden(l) and norm_key(l) not in auto]
        return [(self.cat, l) for l in names if not self.lib.is_hidden(l)]

    def reload(self):
        """Re-read everything (after sync, rename, group changes...)."""
        if self.group:
            self.icon_lbl.setPixmap(icons.pixmap("folder", self.state.group_color(self.cat, self.group[1]), 24))
        self.sel &= set(self.all_items()) | set(self.all_items(hidden=True)) | set(self.all_items(dups=True))     # gone items drop out; filtered / hidden ones stay
        self.reload_facets()
        self.refresh()

    def reload_facets(self):
        labels = [l for _, l in self.all_items()]
        for facet, cb in self.facets.items():
            cur = cb.currentData()
            cb.blockSignals(True)
            cb.clear()
            cb.addItem({"genre": "Any genre", "country": "Any country", "language": "Any language"}[facet], ALL)
            for name, n in sorted(self.lib.meta.facet_counts(labels, facet).items(), key=lambda kv: (-kv[1], kv[0])):
                cb.addItem(f"{name}  ({n})", name)
            cb.setCurrentIndex(max(0, cb.findData(cur)))
            cb.blockSignals(False)
            cb.refit()
        if self.kind:
            cur = self.group_cb.currentData()
            self.group_cb.blockSignals(True)
            self.group_cb.clear()
            self.group_cb.addItem("Any group", ALL)
            for n in self.state.groups.names(self.cat):
                self.group_cb.addItem(n, n)
            self.group_cb.setCurrentIndex(max(0, self.group_cb.findData(cur)))
            self.group_cb.blockSignals(False)

    # ------------------------------------------------------------ filtering
    def matches(self, label, text):
        """Search the name you see (a kept / renamed title), not the original label it was merged or renamed from."""
        t = text.casefold()
        shown = display_title(self.lib, label)
        if t in shown.casefold() or (self.cat == "albums" and t in display_sub(self.lib, label).casefold()):
            return True
        custom = bool(self.lib.meta.get(label).get("name"))            # a name you chose: the original label is not searched
        return self.lib.meta.matches(label, text, by_label=not custom)

    def visible(self):
        text, mode = self.search.text().strip(), self.mode.value
        want = {f: cb.currentData() for f, cb in self.facets.items() if cb.currentData() not in (None, ALL)}
        members = None
        if self.kind and self.group_cb.currentData() not in (None, ALL):
            members = set(self.state.groups.members(self.cat, self.group_cb.currentData()))
        out = []
        for kind, l in self.all_items(hidden=mode == "hidden", dups=mode == "dups"):
            if text and not self.matches(l, text):
                continue
            if mode == "favs" and not self.lib.is_fav(l):
                continue
            if mode == "sel" and (kind, l) not in self.sel:
                continue
            if mode == "nopic" and self.lib.has_poster(l):
                continue
            if members is not None and l not in members:
                continue
            if any(v not in self.lib.meta.values(l, f) for f, v in want.items()):
                continue
            out.append((kind, l))
        return self.sorted_items(out)

    def sorted_items(self, items):
        key = self.sort_cb.currentData() or "az"
        meta = self.lib.meta

        def num(l, field):
            try:
                return float(meta.get(l).get(field))
            except (TypeError, ValueError):
                return None

        def by(field, high_first):
            # missing values always go last; ties keep A-Z order (the sort is stable)
            have = [it for it in items if num(it[1], field) is not None]
            rest = [it for it in items if num(it[1], field) is None]
            have.sort(key=lambda it: num(it[1], field), reverse=high_first)
            return have + rest

        name = (lambda it: display_title(self.lib, it[1]).casefold()) if self.cat != "albums" else (lambda it: it[1].casefold())   # the name you see

        if key == "za":
            return sorted(items, key=name, reverse=True)
        if key == "favs":
            return sorted(items, key=lambda it: not self.lib.is_fav(it[1]))
        if key == "artist":
            return sorted(items, key=lambda it: ((meta.get(it[1]).get("creators") or ["~"])[0].casefold(), it[1].casefold()))
        if key in ("year_new", "year_old"):
            return by("year", key == "year_new")
        if key in ("hue", "bright"):                        # by cover color; the colors are worked out in parallel once, then cached
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                covers.warm_colors(self.lib)
            finally:
                QApplication.restoreOverrideCursor()
            return sorted(items, key=lambda it: covers.color_key(self.lib, it[1], key))
        if key in ("added_new", "added_old"):
            def added(it):                                  # when it joined the library; older items fall back to their poster's date
                t = meta.get(it[1]).get("added")
                if not t:
                    p = self.lib.poster(it[1])
                    try:
                        t = p.stat().st_mtime if p else 0
                    except OSError:
                        t = 0
                return t
            return sorted(items, key=added, reverse=key == "added_new")
        if key == "rating":
            return by("rating", True)
        if key in ("plays_most", "plays_least"):
            return by("playcount", key == "plays_most")
        return sorted(items, key=name)

    def refresh(self, *_):
        items = self.visible()
        self.model.set_items(items)
        total = len(self.all_items(hidden=self.mode.value == "hidden", dups=self.mode.value == "dups"))
        self.count.setText(f"{len(items)} of {total}" if len(items) != total else f"{total}")
        if not items:
            if self.mode.value == "hidden" and total == 0:
                self.empty.setText("No hidden items.\nRight-click an item and choose Hide to tuck it away.")
            elif self.mode.value == "dups" and total == 0:
                self.empty.setText("No hidden duplicates.")
            elif total == 0:
                self.empty.setText("No items yet." + ("\nPress Sync to import from your sources, or use Add." if self.kind else
                                                       f"\nSelect titles in {self.lib.title} and choose Add to group."))
            else:
                self.empty.setText("Nothing matches the current filters.")
        self.stack.setCurrentIndex(0 if items else 1)
        self.update_bar()

    def set_zoom(self, w):
        if w == self.delegate.base:
            return
        self.delegate.base = w
        self.view.apply_zoom()
        self.state.set_pref("zoom", w)
        self.state.zoom_changed.emit(w)

    def _zoom_from_other(self, w):
        if w != self.delegate.base:
            self.zoom.setValue(w)                 # moves the slider, which resizes this page too

    # ------------------------------------------------------------ action bar
    def selected(self):
        """Everything selected, including items the current filters / tab hide: they stay selected."""
        return sorted(self.sel, key=lambda m: sort_key(m[1])) if self.sel else []

    def _label(self, btn, text, icon=None):
        btn.setText("" if self.compact else text)
        if icon:
            btn.set_icon_name(icon)

    def undo_selection(self, redo=False):
        src, dst = (self._sel_redo, self._sel_history) if redo else (self._sel_history, self._sel_redo)
        if not src:
            return
        dst.append(self._sel_now)
        prev = src.pop()
        self._sel_now = prev
        self.sel.clear()
        self.sel.update(prev)
        if self.mode.value == "sel":
            self.refresh()
        self.model.touch_all()
        self.update_bar()

    def update_bar(self):
        now = frozenset(self.sel)
        if now != self._sel_now:                      # every selection change passes through here: remember the old one
            self._sel_history.append(self._sel_now)
            self._sel_redo.clear()                    # a new change ends the redo chain
            del self._sel_history[:-50]
            self._sel_now = now
        n, shown = len(self.sel), len(self.model.items)
        self.info.setText(f"{n} selected" if n else f"{shown} shown")
        self.info.setToolTip("Click posters to select (shift-click for a range), click the star to favorite")
        for b in (self.btn_fav, self.btn_group, self.btn_unlink):
            b.setEnabled(n > 0)
        self.btn_all.setEnabled(shown > 0)
        sel = self.selected()
        self._fav_state = bool(sel) and all(self.lib.is_fav(l) for _, l in sel)
        self._all_selected = shown > 0 and set(self.model.items) <= self.sel
        self._label(self.btn_fav, "Unfavorite" if self._fav_state else "Favorite")
        self._label(self.btn_all, "Unselect all" if self._all_selected else "Select all", "x" if self._all_selected else "check")
        self._label(self.btn_group, "Add to group")
        self._label(self.btn_unlink, "Remove from group")

    def set_syncing(self, busy):
        self.cancel_btn.setVisible(busy)
        left = 24
        if busy:                                         # the X icon sits as far from the left edge as from the top / bottom
            gap = (self.actions_bar.sizeHint().height() - 14) / 2
            left = max(8, round(gap - (self.cancel_btn.width() - 14) / 2))
        self.ah.setContentsMargins(left, 12, 24, 12)

    def set_status(self, text):
        self.status.set_message(text)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.zoom_box.setVisible(self.width() >= 1000)           # make room for the search field on narrow windows
        wide = self.width() >= 900
        self.search.setMinimumWidth(330 if wide else 180)
        self.search.edit.setPlaceholderText("Search title, genre, country, creator..." if wide else "Search...")
        compact = self.width() < 760
        if compact != self.compact:
            self.compact = compact
            self.update_bar()

    # ------------------------------------------------------------ selection / favorites
    def on_card(self, idx, mods):
        row, item = idx.row(), (idx.data(ROLE_KIND), idx.data(ROLE_LABEL))
        if mods & Qt.KeyboardModifier.ShiftModifier and self.last_row is not None:
            a, b = sorted((self.last_row, row))
            span = set(self.model.items[a:b + 1])
            if self.last_on:                                  # the range follows what the last plain click did
                self.sel |= span
            else:
                self.sel -= span
                if self.mode.value == "sel":
                    self.refresh()
        else:
            self.sel.symmetric_difference_update({item})
            self.last_row, self.last_on = row, item in self.sel
        self.model.touch_all()
        self.update_bar()

    def select_all(self):
        self.sel |= set(self.model.items)
        self.model.touch_all()
        self.update_bar()

    def toggle_select_all(self):
        shown = set(self.model.items)
        if shown and shown <= self.sel:
            self.sel -= shown
            if self.mode.value == "sel":
                self.refresh()
        else:
            self.sel |= shown
        self.model.touch_all()
        self.update_bar()

    def clear_selection(self):
        self.sel.clear()
        if self.mode.value == "sel":
            self.refresh()
        self.model.touch_all()
        self.update_bar()

    def on_star(self, idx):
        label_ = idx.data(ROLE_LABEL)
        self.lib.set_fav(label_, not self.lib.is_fav(label_))
        self.lib.save()
        self.model.touch(idx.row())
        self.update_bar()
        self._self_updated = self.mode.value != "favs" and (self.sort_cb.currentData() != "favs")   # current already, unless the filter / sort depends on favorites
        self.data_changed.emit()

    def toggle_fav_selected(self):
        sel = self.selected()
        value = not self._fav_state
        if len(sel) > 1:                                # changing many at once is easy to do by accident: confirm
            if not confirm(self, "Favorites", f"{'Add' if value else 'Remove'} {len(sel)} items {'to' if value else 'from'} your favorites?", "Yes"):
                return
        for _, l in sel:
            self.lib.set_fav(l, value)
        self.lib.save()
        self.log.emit(f"{len(sel)} item(s) {'added to' if value else 'removed from'} favorites")
        self.refresh()
        self.data_changed.emit()

    # ------------------------------------------------------------ groups (each belongs to this page's category)
    def _ask_group(self, text=""):
        return ask_text(self, "New group", f"Group name in {self.lib.title} (e.g. Sci-fi, Horror night):", text, "Create")

    def group_menu(self):
        menu = QMenu(self)
        own = self.group[1] if self.group else None
        names = [n for n in self.state.groups.names(self.cat) if n != own]
        for name in names:
            menu.addAction(icons.icon("folder", self.state.group_color(self.cat, name), 16), name, lambda n=name: self.add_to_group(self.selected(), n))
        if names:
            menu.addSeparator()
        menu.addAction(icons.icon("plus", theme.MUTED, 16), "New group...", lambda: self.add_to_group(self.selected(), None))
        menu.exec(self.btn_group.mapToGlobal(QPointF(0, -menu.sizeHint().height() - 6).toPoint()))

    def add_to_group(self, items, name):
        name = name or self._ask_group()
        if name and items:
            n = self.state.groups.add(self.cat, name, [l for _, l in items])
            self.log.emit(f"Group '{name}': +{n} item(s)")
            self.groups_changed.emit()

    def remove_from_group(self):
        sel = self.selected()
        if sel and self.group:
            self.state.groups.remove_items(self.cat, self.group[1], [l for _, l in sel])
            self.sel.clear()
            self.groups_changed.emit()
            self.reload()

    def rename_group(self):
        new = ask_text(self, "Rename group", f"New name for the group ‘{self.group[1]}’ (the items in it are not changed):", self.group[1], "Rename")
        if new and new != self.group[1]:
            if self.state.groups.rename(self.cat, self.group[1], new):
                self.group_renamed.emit(self.cat, self.group[1], new)
            else:
                notify(self, "Rename group", "A group with that name already exists.")

    def delete_group(self):
        if confirm(self, "Delete group", f"Delete the group '{self.group[1]}'?\nThe items themselves are not touched.", "Delete", danger=True):
            self.state.groups.delete(self.cat, self.group[1])
            self.group_deleted.emit(self.cat, self.group[1])

    def open_list_file(self):
        """A txt with the items you see (hidden ones left out), written next to the library's data."""
        import os
        path = self.lib.json_path.with_name("shown.txt")
        lines = [f"{display_sub(self.lib, l)} - {display_title(self.lib, l)}" if self.cat == "albums" and display_sub(self.lib, l)
                 else display_title(self.lib, l) for l in self.lib.shown_items()]            # the names you see, renames included
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.startfile(path)

    def open_group_file(self):
        import os
        path = self.lib.json_path.with_name(f"group_{safe_filename(self.group[1])}.txt")       # a readable copy of the group
        path.write_text("\n".join(self.state.groups.members(self.cat, self.group[1])) + "\n", encoding="utf-8")
        os.startfile(path)

    # ------------------------------------------------------------ hand-off to the collage page
    def current_picks(self):
        """What a collage started from this page should contain: the selection, otherwise everything shown."""
        items = self.selected() or list(self.model.items)
        what = f"{len(self.sel)} selected in {self.title.text()}" if self.sel else f"{len(items)} shown in {self.title.text()}"
        return items, what

    # ------------------------------------------------------------ context menu / item management
    def on_menu(self, pos):
        idx = self.view.item_at(pos)
        if not idx.isValid():
            return                                          # right click on empty space leaves the selection alone
        target = (idx.data(ROLE_KIND), idx.data(ROLE_LABEL))
        if target in self.sel and len(self.sel) > 1:        # right click inside a multi-selection acts on all of it
            items = self.selected()
        else:                                               # on anything else it selects just that item first
            if self.sel != {target}:
                self.sel.clear()
                self.sel.add(target)
                self.model.touch_all()
                self.update_bar()
            items = [target]
        labels = [l for _, l in items]
        many = len(items) > 1
        menu = QMenu(self)
        all_fav = all(self.lib.is_fav(l) for l in labels)
        menu.addAction(icons.icon("star", theme.GOLD if not all_fav else theme.MUTED, 16, filled=not all_fav),
                       ("Remove from favorites" if all_fav else "Add to favorites") + (f" ({len(items)})" if many else ""),
                       lambda: self.set_favs(labels, not all_fav))
        hid = all(self.lib.is_hidden(l) for l in labels)
        menu.addAction(icons.icon("eye" if hid else "eye-off", theme.MUTED, 16),
                       ("Unhide" if hid else "Hide") + (f" ({len(items)})" if many else ""),
                       lambda: self.set_hidden(labels, not hid))
        if many:
            menu.addAction(icons.icon("layers", theme.MUTED, 16), f"Mark {len(items)} as duplicates", lambda: self.mark_duplicates(labels))
        sub = menu.addMenu(icons.icon("folder", theme.MUTED, 16), "Add to group")
        for name in self.state.groups.names(self.cat):
            sub.addAction(name, lambda n=name: self.add_to_group(items, n))
        sub.addAction("New group...", lambda: self.add_to_group(items, None))
        if self.group:
            menu.addAction(icons.icon("minus-circle", theme.MUTED, 16), f"Remove from '{self.group[1]}'",
                           lambda: (self.state.groups.remove_items(self.cat, self.group[1], labels), self.sel.clear(), self.groups_changed.emit(), self.reload()))
        menu.addSeparator()
        if not many:
            menu.addAction(icons.icon("image", theme.MUTED, 16), "Replace poster...", lambda: self.replace_poster(labels[0]))
            menu.addAction(icons.icon("edit", theme.MUTED, 16), "Rename...", lambda: self.rename(labels[0]))
        menu.addAction(icons.icon("trash", theme.DANGER, 16), f"Remove {len(items)} from list" if many else "Remove from list",
                       lambda: self.remove_many(labels))
        menu.exec(self.view.viewport().mapToGlobal(pos))

    def set_favs(self, labels, value):
        if len(labels) > 1 and not confirm(self, "Favorites", f"{'Add' if value else 'Remove'} {len(labels)} items {'to' if value else 'from'} your favorites?", "Yes"):
            return
        for l in labels:
            self.lib.set_fav(l, value)
        self.lib.save()
        self.refresh()
        self.data_changed.emit()

    def mark_duplicates(self, labels):
        """The selected items are the same one: add them as a set and open the duplicates dialog to pick which to keep."""
        editions.mark_duplicates(self.cat, labels)
        self.sel.clear()
        self.model.touch_all()
        self.update_bar()
        self.merge_duplicates()

    def set_hidden(self, labels, value):
        """Hidden items disappear from every list (except the Hidden filter) and are left out of collages."""
        for l in labels:
            self.lib.set_hidden(l, value)
            self.sel.discard((self.cat, l))
        self.lib.save()
        self.log.emit(f"{len(labels)} item(s) {'hidden' if value else 'shown again'}")
        self.reload_facets()
        self.refresh()
        self.data_changed.emit()

    def remove_many(self, labels):
        if len(labels) == 1:
            return self.remove(labels[0])
        if not confirm(self, "Remove items", f"Remove {len(labels)} items?\nThis deletes them and their posters. Hide them instead to keep them out of sight.", "Remove", danger=True):
            return
        for l in labels:
            self.lib.forget(l)
            self.state.groups.remove_member(self.cat, l)
        self.lib.save()
        self.sel.clear()
        self.data_changed.emit()
        self.groups_changed.emit()

    def merge_duplicates(self):
        from .dialogs import DuplicatesDialog
        d = DuplicatesDialog(self.state, self.kind, self)
        if d.exec() and d.changed:
            self.log.emit(f"Duplicates resolved: {d.changed} change(s)")
            self.state.changed.emit()
            self.data_changed.emit()
            self.groups_changed.emit()

    def replace_poster(self, label_):
        path, _ = QFileDialog.getOpenFileName(self, "Choose poster", "", "Images (*.jpg *.jpeg *.png *.webp)")
        if path:
            if self.lib.poster(label_):
                self.state.thumbs.invalidate(self.lib.poster(label_))
            self.state.thumbs.invalidate(self.lib.set_poster(label_, Path(path)))
            self.refresh()

    def rename(self, label_):
        """Give an item the name you want it to have. Only the shown name changes: the item keeps its label, poster,
        groups and hidden / duplicate state, and syncs keep matching it by its source name."""
        shown = display_title(self.lib, label_)
        new = ask_text(self, "Rename", "New name:", shown, "Rename")
        if new and new.strip() and new.strip() != shown:
            self.lib.meta.set_name(label_, new.strip())
            self.lib.save()
            self.state.changed.emit()
            self.data_changed.emit()

    def remove(self, label_):
        if confirm(self, "Remove", f"Remove '{display_title(self.lib, label_)}'?\nThis deletes it and its poster. Hide it instead to keep it out of sight.", "Remove", danger=True):
            self.lib.forget(label_)
            self.lib.save()
            in_groups = bool(self.state.groups.groups_of(self.cat, label_))
            self.state.groups.remove_member(self.cat, label_)
            self.sel.discard((self.cat, label_))
            self.data_changed.emit()
            if in_groups:
                self.groups_changed.emit()

    def add_item(self):
        title = ask_text(self, f"Add to {self.lib.title}", f"Title to add to {self.lib.title} (a poster is fetched on the next sync):", "", "Add")
        if not title:
            return
        self.lib.unforget(title)                     # adding by hand overrides an earlier removal
        if not self.lib.add(title):
            notify(self, "Add", "That item is already in the list.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Choose a poster (optional)", "", "Images (*.jpg *.jpeg *.png *.webp)")
        if path:
            self.lib.set_poster(title, Path(path))
        self.lib.save()
        self.data_changed.emit()

"""Collage builder: source + shape + style on the right, live preview on the left, full-size render at the bottom."""
import os

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QScrollArea,
                               QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

from ..collage import render
from ..core import editions
from ..core.config import OUTPUT_DIR
from .colorpicker import pick_color
from . import icons, theme
from .common import Job, pil_to_qimage
from .widgets import Btn, ProgressLine, UnitSpin, Chips, Segmented, button, divider, form_row, label, section_header, stacked_row

ALL_MEDIA = "All media"
SOURCES = {"Albums": ["albums"], ALL_MEDIA: ["shows", "movies", "albums"], "Movies": ["movies"], "Shows": ["shows"]}   # Albums is the default
SCOPES = (("Favorites", "favs"), ("Group", "group"), ("Selection", "picks"))      # after the default "All items", A-Z
COLOR_FROM = (("Average", "average"), ("Dominant", "dominant"), ("Accent", "accent"))
KIND_TITLES = {"shows": "Shows", "movies": "Movies", "albums": "Albums"}
RATIOS = (("Free", ""), ("16:9", "16:9"), ("2:3", "2:3"), ("3:4", "3:4"), ("4:5", "4:5"), ("1:1", "1:1"))   # Free, then farthest from square to square
PREVIEW_WIDTH = 1500


def spin(lo, hi, val, suffix="", special=None):
    s = UnitSpin(suffix.strip())
    s.setRange(lo, hi)
    s.setValue(val)
    if special:
        s.setSpecialValueText(special)
    return s


class PreviewArea(QWidget):
    """The collage preview. Fits the space at first; scroll to zoom towards the cursor, drag to move, double-click to
    jump between "fit" and actual size. The preview itself is small (PREVIEW_WIDTH); once you zoom past it, the part
    you are looking at is rendered again from the full-size layout, so it is as sharp as the saved image will be."""
    MAX_ZOOM = 16.0
    detail_wanted = Signal(object, float, int)       # region (in preview pixels), render pixels per preview pixel, generation

    def __init__(self):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setMinimumSize(120, 120)
        self.setMouseTracking(True)
        self.pix, self.text = None, ""
        self.zoom, self.cx, self.cy = 1.0, 0.5, 0.5          # zoom 1 = fits the area; (cx, cy) = image point shown in the middle
        self._drag = None
        self.src, self.gen, self.detail = None, 0, None      # src = (paths, full-size layout, background); detail = (image, region)
        self.dtimer = QTimer(self, singleShot=True, interval=180)
        self.dtimer.timeout.connect(self._want_detail)
        self.setToolTip("Scroll to zoom, drag to move, double-click to reset")

    # ---- content
    def show_pixmap(self, pm, src=None):
        first = self.pix is None
        self.pix, self.text = pm, ""
        if src is not None:
            self.src, self.detail = src, None
            self.gen += 1
            self._schedule()
        if first:
            self.zoom, self.cx, self.cy = 1.0, 0.5, 0.5       # a new preview of the same collage keeps your view
        self._clamp()
        self._cursor()
        self.update()

    def show_text(self, text):
        self.pix, self.text, self.detail = None, text, None
        self.update()

    # ---- sharp detail while zoomed in
    def _schedule(self):
        if self.src and self.pix:
            self.dtimer.start()

    def _want_detail(self):
        if not (self.src and self.pix):
            return
        layout = self.src[1]
        sc = self._scale()
        f = layout.width / self.pix.width()                    # full-size pixels per preview pixel
        s = min(f, sc * self.devicePixelRatioF())              # no point rendering finer than the screen or the saved image
        if s < 1.15:
            return
        ox, oy = self._origin()
        m = 0.25                                               # a margin around the view, so small drags stay sharp
        x0, y0 = max(0.0, -ox / sc - self.width() * m / sc), max(0.0, -oy / sc - self.height() * m / sc)
        x1 = min(float(self.pix.width()), (self.width() - ox) / sc + self.width() * m / sc)
        y1 = min(float(self.pix.height()), (self.height() - oy) / sc + self.height() * m / sc)
        if x1 <= x0 or y1 <= y0:
            return
        side = max((x1 - x0) * s, (y1 - y0) * s)
        if side > 3200:
            s *= 3200 / side
        self.detail_wanted.emit(QRectF(x0, y0, x1 - x0, y1 - y0), s, self.gen)

    def show_detail(self, img, region, gen):
        if gen == self.gen and self.pix:
            self.detail = (QPixmap.fromImage(img), region)
            self.update()

    # ---- geometry
    def _fit_scale(self):
        w, h = max(1, self.width() - 2), max(1, self.height() - 2)
        return min(w / self.pix.width(), h / self.pix.height())

    def _scale(self):
        return self._fit_scale() * self.zoom

    def _clamp(self):
        if not self.pix:
            return
        sc = self._scale()
        for axis, size, view in (("cx", self.pix.width(), self.width()), ("cy", self.pix.height(), self.height())):
            shown = size * sc
            half = min(0.5, (view / 2) / shown) if shown else 0.5
            v = min(max(getattr(self, axis), half), 1 - half) if shown > view else 0.5
            setattr(self, axis, v)

    def _origin(self):
        sc = self._scale()
        return self.width() / 2 - self.cx * self.pix.width() * sc, self.height() / 2 - self.cy * self.pix.height() * sc

    def _cursor(self):
        zoomed = bool(self.pix) and self.zoom > 1.0001
        self.setCursor(Qt.CursorShape.ClosedHandCursor if self._drag else Qt.CursorShape.OpenHandCursor if zoomed else Qt.CursorShape.ArrowCursor)

    def _zoom_to(self, zoom, at):
        """Change the zoom so the image point under `at` (widget coordinates) stays under it."""
        zoom = min(max(zoom, 1.0), self.MAX_ZOOM)
        ox, oy = self._origin()
        old = self._scale()
        px, py = (at.x() - ox) / old, (at.y() - oy) / old
        self.zoom = zoom
        new = self._scale()
        self.cx = (self.width() / 2 - (at.x() - px * new)) / (self.pix.width() * new)
        self.cy = (self.height() / 2 - (at.y() - py * new)) / (self.pix.height() * new)
        self._clamp()
        self._cursor()
        self.update()
        self._schedule()

    # ---- events
    def wheelEvent(self, e):
        if self.pix:
            self._zoom_to(self.zoom * 1.18 ** (e.angleDelta().y() / 120), e.position())
        e.accept()

    def mousePressEvent(self, e):
        if self.pix and e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.position()
            self._cursor()

    def mouseMoveEvent(self, e):
        if self._drag is not None and self.pix:
            d = e.position() - self._drag
            self._drag = e.position()
            sc = self._scale()
            self.cx -= d.x() / (self.pix.width() * sc)
            self.cy -= d.y() / (self.pix.height() * sc)
            self._clamp()
            self.update()
            self._schedule()

    def mouseReleaseEvent(self, e):
        self._drag = None
        self._cursor()

    def mouseDoubleClickEvent(self, e):
        if not self.pix:
            return
        actual = 1.0 / self._fit_scale()                       # zoom at which one image pixel is one screen pixel
        if self.zoom > 1.0001:
            self._zoom_to(1.0, e.position())
        else:
            self._zoom_to(max(actual, 2.0), e.position())

    def keyPressEvent(self, e):
        if self.pix and e.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal, Qt.Key.Key_Minus, Qt.Key.Key_0):
            c = QPointF(self.width() / 2, self.height() / 2)
            self._zoom_to(1.0 if e.key() == Qt.Key.Key_0 else self.zoom * (1.3 if e.key() != Qt.Key.Key_Minus else 1 / 1.3), c)
        else:
            super().keyPressEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._clamp()
        self._schedule()

    def paintEvent(self, e):
        p = QPainter(self)
        if not self.pix:
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(self.rect()).adjusted(20, 20, -20, -20), int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap), self.text)
            return
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        sc = self._scale()
        ox, oy = self._origin()
        p.drawPixmap(QRectF(ox, oy, self.pix.width() * sc, self.pix.height() * sc), self.pix, QRectF(self.pix.rect()))
        if self.detail and sc > 1.0:                             # the sharp patch on top
            img, r = self.detail
            p.drawPixmap(QRectF(ox + r.x() * sc, oy + r.y() * sc, r.width() * sc, r.height() * sc), img, QRectF(img.rect()))
        if self.zoom > 1.0001:                                   # small badge so you know you are zoomed
            txt = f"{round(100 * sc)}%"
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            r = QRectF(self.width() - 64, 10, 54, 22)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(8, 10, 14, 200))
            p.drawRoundedRect(r, 6, 6)
            p.setPen(QColor(theme.TEXT))
            p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), txt)


class CollagePage(QWidget):
    log = Signal(str)
    loading = Signal(int, int)       # building a collage: progress for the sidebar's loading line
    loaded = Signal()

    def __init__(self, state):
        super().__init__()
        self.state = state
        self.bg, self.seed, self.token = QColor(0, 0, 0), 1, 0
        self.running, self.rerun, self.jobs = None, False, []
        self.timer = QTimer(self, singleShot=True, interval=400)
        self.timer.timeout.connect(self.start_preview)
        self.detail_job, self.detail_next = None, None

        # ------------------------------------------------ controls
        self.source = QComboBox()
        self.source.addItems(SOURCES)
        self.scope = QComboBox()
        self.group = QComboBox()
        self.picks_lbl = label("", "muted", wrap=True)
        self.order = Segmented([("A–Z", "az"), ("Z–A", "za"), ("Shuffle", "shuffle"), ("Color", "hue"), ("Light", "bright")], "az")
        self.direction = Segmented([("Vertical", "vertical"), ("Horizontal", "horizontal"), ("Diagonal", "diagonal")], "vertical")
        self.direction.setToolTip("Which way the colors run across the collage")
        self.color_from = Segmented(list(COLOR_FROM), "average")
        self.color_from.setToolTip(chr(10).join(f"{t}: {render.COLOR_MODES[k]}" for t, k in COLOR_FROM))
        self.reverse = Btn("", "sort", "toggle", "Reverse the order", size=16, pad=0)
        self.reverse.setCheckable(True)
        self.reverse.setFixedWidth(theme.HEIGHT + 2)
        self.fit = Segmented([("Keep shape", "keep"), ("Fill (crop)", "crop")], "keep")
        self.fit.setToolTip("Keep shape: posters are only resized, never cropped or stretched. Fill: every poster fills its cell exactly (crops edges).")
        self.order.buttons["shuffle"].setToolTip("Click again to shuffle again")
        self.order.reclicked.connect(lambda v: self.new_seed() if v == "shuffle" else None)

        self.mode = Segmented([("Justified rows", "justified"), ("Even grid", "grid")], "justified")
        self.ratio = Chips(RATIOS, "3:4")
        self.orient = Segmented([("Portrait", "portrait"), ("Landscape", "landscape")], "portrait",
                                {"portrait": "portrait", "landscape": "landscape"})
        self.row_h = spin(60, 2000, 300, " px")
        self.cols = spin(0, 200, 0, "", "Auto")
        self.dedupe = QCheckBox("One cover per album")
        self.dedupe.setChecked(True)
        self.dedupe.setToolTip("Albums that exist as Deluxe / Remastered / Explicit editions appear only once (the favorite or most played one)")
        self.balance = QCheckBox("Auto-balance rows")
        self.balance.setChecked(True)
        self.balance.setToolTip("Tries many row heights and keeps the one where all rows, including the last, match best")
        self.equal = QCheckBox("Equal row heights (crops a little)")
        self.equal.setChecked(True)
        self.width_ = spin(600, 30000, 4000, " px")
        self.gap = spin(0, 100, 0, " px")
        self.margin = spin(0, 400, 0, " px")
        self.color = button("", None)
        self.color.align_left()
        self.color.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.color.clicked.connect(self.pick_color)
        self.fmt = Segmented([("PNG", "PNG"), ("JPEG", "JPEG")], "PNG")
        self.quality = spin(50, 100, 92)

        # ------------------------------------------------ right panel
        panel = QWidget()
        panel.setObjectName("panel")
        v = QVBoxLayout(panel)
        v.setContentsMargins(20, 20, 18, 20)
        v.setSpacing(10)
        v.addWidget(section_header("Source"))
        v.addWidget(form_row("Media", self.source))
        v.addWidget(form_row("Include", self.scope))
        self.row_group = form_row("Group", self.group)
        v.addWidget(self.row_group)
        v.addWidget(self.picks_lbl)
        v.addWidget(self.dedupe)
        v.addWidget(stacked_row("Order", self.order))
        self.row_from = stacked_row("Color from", self.color_from)
        v.addWidget(self.row_from)
        dir_row = QWidget()
        dh = QHBoxLayout(dir_row)
        dh.setContentsMargins(0, 0, 0, 0)
        dh.setSpacing(8)
        dh.addWidget(self.direction, 1)
        dh.addWidget(self.reverse)
        self.row_dir = stacked_row("Color direction", dir_row)
        v.addWidget(self.row_dir)
        v.addSpacing(6)
        v.addWidget(divider())
        v.addSpacing(6)
        v.addWidget(section_header("Shape"))
        v.addWidget(self.mode)
        v.addWidget(stacked_row("Posters", self.fit))
        v.addWidget(label("Aspect ratio", "muted"))
        v.addWidget(self.ratio)
        v.addWidget(self.orient)
        self.row_rowh = form_row("Row height", self.row_h)
        self.row_cols = form_row("Columns", self.cols)
        v.addWidget(self.row_rowh)
        v.addWidget(self.row_cols)
        v.addWidget(self.balance)
        v.addWidget(self.equal)
        v.addSpacing(6)
        v.addWidget(divider())
        v.addSpacing(6)
        v.addWidget(section_header("Size & style"))
        v.addWidget(form_row("Width", self.width_))
        v.addWidget(form_row("Gap", self.gap))
        v.addWidget(form_row("Margin", self.margin))
        v.addWidget(form_row("Background", self.color))
        v.addSpacing(6)
        v.addWidget(divider())
        v.addSpacing(6)
        v.addWidget(section_header("Output"))
        v.addWidget(self.fmt)
        self.row_quality = form_row("Quality", self.quality)
        v.addWidget(self.row_quality)
        v.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setMinimumWidth(330)
        scroll.setMaximumWidth(390)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea {{ background: {theme.SURFACE}; border-left: 1px solid {theme.BORDER}; }}")
        scroll.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        # ------------------------------------------------ header + preview
        self.title = label("Collage", "h1")
        self.summary = label("", "chip")
        head = QHBoxLayout()
        head.setSpacing(12)
        icon = QLabel()
        icon.setPixmap(icons.pixmap("mosaic", theme.ACCENT, 24))
        head.addWidget(icon)
        head.addWidget(self.title)
        head.addWidget(self.summary)
        head.addStretch()
        self.preview = PreviewArea()
        self.preview.detail_wanted.connect(self.render_detail)
        frame = QWidget()
        frame.setObjectName("card")
        frame.setStyleSheet(f"QWidget#card {{ background: {theme.SURFACE}; border: 1px solid {theme.BORDER}; border-radius: 12px; }}")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(10, 10, 10, 10)
        fl.addWidget(self.preview)
        left = QVBoxLayout()
        left.setContentsMargins(24, 20, 20, 16)
        left.setSpacing(16)
        left.addLayout(head)
        left.addWidget(frame, 1)

        # ------------------------------------------------ footer
        self.info = label("", "muted")
        self.open_btn = button("Output folder", "folder", "ghost")
        self.open_btn.clicked.connect(lambda: os.startfile(OUTPUT_DIR))
        self.make = button("Generate collage", "download", "primary")
        self.make.clicked.connect(self.generate)
        foot = QWidget()
        foot.setObjectName("bar")
        fh = QHBoxLayout(foot)
        fh.setContentsMargins(24, 12, 24, 12)
        fh.setSpacing(12)
        fh.addWidget(self.info, 1)
        fh.addWidget(self.open_btn)
        fh.addWidget(self.make)

        body = QHBoxLayout()
        body.setSpacing(0)
        lw = QWidget()
        lw.setLayout(left)
        body.addWidget(lw, 1)
        body.addWidget(scroll)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addLayout(body, 1)
        root.addWidget(foot)

        self.source.currentIndexChanged.connect(self.source_changed)
        self.scope.currentIndexChanged.connect(self.scope_changed)
        for w in (self.scope, self.group):
            w.currentIndexChanged.connect(self.changed)
        for w in (self.order, self.direction, self.color_from, self.fit, self.mode, self.ratio, self.orient, self.fmt):
            w.changed.connect(self.changed)
        for w in (self.balance, self.equal, self.reverse, self.dedupe):
            w.toggled.connect(self.changed)
        for w in (self.row_h, self.cols, self.width_, self.gap, self.margin, self.quality):
            w.valueChanged.connect(self.changed)
        self.set_color(self.bg)
        self.refresh_scopes()
        self.reload_groups()

    # ------------------------------------------------------------ hooks from other pages
    def refresh_scopes(self):
        """'All items' is the default; 'Selection' is only offered when the page you came from handed over some items."""
        cur = self.scope.currentData() or "all"
        self.scope.blockSignals(True)
        self.scope.clear()
        self.scope.addItem("All items", "all")
        for t, k in SCOPES:
            if k != "picks" or self.state.picks:
                self.scope.addItem(t, k)
        self.scope.setCurrentIndex(max(0, self.scope.findData(cur)))
        self.scope.blockSignals(False)

    def use_picks(self, items, desc):
        """Called when you open Collage from a library / group page: selected items, else everything shown there."""
        self.state.picks, self.state.picks_desc = items, desc
        self.refresh_scopes()
        self.picks_lbl.setText(desc)
        self.changed()

    def use_group(self, kind, name):
        self.state.picks = []
        self.refresh_scopes()
        self.source.setCurrentText(KIND_TITLES[kind])
        self.scope.setCurrentIndex(self.scope.findData("group"))
        self.group.setCurrentIndex(max(0, self.group.findData(f"{kind}|{name}")))

    def source_changed(self, *_):
        """Choosing another media type while 'Selection' is active goes back to 'All items'; the selection itself is kept
        and can be chosen again (which switches the media dropdown back to what it contains)."""
        covered = SOURCES[self.source.currentText()]
        if self.scope.currentData() == "picks" and not {k for k, _ in self.state.picks} <= set(covered):
            self.scope.blockSignals(True)
            self.scope.setCurrentIndex(0)
            self.scope.blockSignals(False)
        self.reload_groups()

    def scope_changed(self, *_):
        if self.scope.currentData() == "picks" and self.state.picks:
            self.picks_lbl.setText(self.state.picks_desc)
            kinds = {k for k, _ in self.state.picks}
            if not kinds <= set(SOURCES[self.source.currentText()]):       # only switch media when it can't hold the selection
                self.source.blockSignals(True)
                self.source.setCurrentText(KIND_TITLES[next(iter(kinds))] if len(kinds) == 1 else ALL_MEDIA)
                self.source.blockSignals(False)
                self.reload_groups()

    def group_value(self):
        data = self.group.currentData()
        return tuple(data.split("|", 1)) if data else None

    def reload_groups(self, *_):
        """Groups belong to one category, so the list follows the chosen media type."""
        cur = self.group.currentData()
        kinds = SOURCES[self.source.currentText()]
        self.group.blockSignals(True)
        self.group.clear()
        names = [n for k in kinds for n in self.state.groups.names(k)]
        for k in kinds:
            for n in self.state.groups.names(k):
                self.group.addItem(n if names.count(n) == 1 else f"{n} ({KIND_TITLES[k]})", f"{k}|{n}")
        if not self.group.count():
            self.group.addItem("No groups yet", None)
        self.group.setCurrentIndex(max(0, self.group.findData(cur)))
        self.group.blockSignals(False)
        self.changed()

    # ------------------------------------------------------------ settings -> options
    def new_seed(self):
        self.seed += 1
        self.changed()

    def pick_color(self):
        c = pick_color(self, self.bg, "Background color")
        if c:
            self.set_color(c)
            self.changed()

    def set_color(self, c):
        self.bg = c
        self.color.setText(c.name().upper())
        pm = QPixmap(36, 36)                      # swatch with a light outline so dark colors stay visible
        pm.fill(Qt.GlobalColor.transparent)
        pm.setDevicePixelRatio(2.0)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(theme.DIM), 1))
        p.setBrush(c)
        p.drawRoundedRect(1, 1, 16, 16, 4, 4)
        p.end()
        self.color.set_pixmap(pm)

    def options(self) -> render.Options:
        return render.Options(
            mode=self.mode.value, width=self.width_.value(), gap=self.gap.value(), margin=self.margin.value(),
            row_height=self.row_h.value(), auto_balance=self.balance.isChecked(), equal_rows=self.equal.isChecked(),
            columns=self.cols.value(), aspect=render.aspect_from(self.ratio.value, self.orient.value == "landscape"),
            order=self.order.value, direction=self.direction.value, color_mode=self.color_from.value, reverse=self.reverse.isChecked(),
            fit=self.fit.value, seed=self.seed, bg=(self.bg.red(), self.bg.green(), self.bg.blue()),
            fmt=self.fmt.value, quality=self.quality.value())

    def pool(self):
        items = self.state.pool(SOURCES[self.source.currentText()], self.scope.currentData(), self.group_value())
        if self.dedupe.isChecked():
            lib = self.state.libs["albums"]
            items = editions.dedupe(items, lib.is_fav, lambda l: lib.meta.get(l).get("playcount", 0) or 0)
        return items

    def relabel_ratios(self):
        """Portrait shows short:long (2:3), landscape long:short (3:2); the value behind each chip never changes."""
        land = self.orient.value == "landscape"
        for val, b in self.ratio.buttons.items():
            if val:
                short, long_ = sorted(int(x) for x in val.split(":"))
                b.setText(f"{long_}:{short}" if land else f"{short}:{long_}")

    def changed(self, *_):
        self.relabel_ratios()
        scope = self.scope.currentData()
        free, square = not self.ratio.value, self.ratio.value == "1:1"
        grid = self.mode.value == "grid"
        self.row_group.setVisible(scope == "group")
        self.picks_lbl.setVisible(scope == "picks")
        colored = self.order.value in ("hue", "bright")
        self.row_dir.setVisible(colored)
        self.row_from.setVisible(self.order.value == "hue")
        crop = self.fit.value == "crop"
        self.dedupe.setVisible("albums" in SOURCES[self.source.currentText()])
        self.orient.setEnabled(not free and not square)
        self.row_rowh.setVisible(not grid and free)
        self.balance.setVisible(not grid and free)
        self.equal.setVisible(not grid and free and crop)
        self.row_cols.setVisible(grid)
        self.row_quality.setVisible(self.fmt.value == "JPEG")
        self.timer.start()

    # ------------------------------------------------------------ rendering
    def _prepare(self, pool, o):
        by_key = {f"{k}:{l}": p for k, l, p in pool if render.readable(p)}
        order = render.order_items(list(by_key), o.order, o.seed, by_key, o.color_mode, o.reverse)
        paths = [by_key[k] for k in order]
        layout = render.make_layout(paths, o)
        if o.order in ("hue", "bright"):
            paths = render.arrange(paths, layout, o.direction)
        return paths, layout

    def showEvent(self, e):
        super().showEvent(e)
        if getattr(self, "_stale_preview", False):
            self._stale_preview = False
            self.timer.start()

    def start_preview(self):
        if not self.isVisible():                          # nobody is looking: build the preview when the page is opened
            self._stale_preview = True
            return
        if self.running:
            self.rerun = True
            return
        pool, o = self.pool(), self.options()
        self.summary.setText(f"{len(pool)} items")
        if not pool:
            self.preview.show_text("Nothing to show yet.\nPick another source or group, or open Collage from a page with titles.")
            self.info.setText("")
            return

        def work(progress):
            progress(0, 1)
            paths, layout = self._prepare(pool, o)
            small = layout.scaled(min(1.0, PREVIEW_WIDTH / layout.width))
            return layout, pil_to_qimage(render.render(paths, small, o.bg, progress)), (paths, layout, o.bg)

        self._run(work, self.preview_done, self.preview.show_text, lambda a, b: self.info.setText(f"Building preview... {100 * a // max(1, b)}%"))
        self.info.setText("Building preview... 0%")

    def preview_done(self, res):
        layout, qimg, src = res
        self.preview.show_pixmap(QPixmap.fromImage(qimg), src)
        crop = f"  ·  crop up to {layout.spread:.1%}" if layout.spread else ""
        self.info.setText(f"{len(layout.cells)} items  ·  {layout.rows} rows  ·  {layout.width} × {layout.height}px  ·  ratio {layout.width / layout.height:.2f}{crop}")

    def render_detail(self, region, s, gen):
        """Re-render the zoomed-in part of the preview from the full-size layout (one at a time, newest request wins)."""
        if self.detail_job:
            self.detail_next = (region, s, gen)
            return
        paths, layout, bg = self.preview.src
        f = self.preview.pix.width() / layout.width                  # preview pixels per full-size pixel
        scaled = layout.scaled(s * f)                                # render pixels per full-size pixel
        box = (round(region.x() * s), round(region.y() * s), max(1, round(region.width() * s)), max(1, round(region.height() * s)))
        job = Job(lambda _p: pil_to_qimage(render.render_region(paths, scaled, box, bg)))
        self.detail_job = job

        def finish():
            self.detail_job = None
            nxt, self.detail_next = self.detail_next, None
            if nxt and nxt[2] == self.preview.gen:
                self.render_detail(*nxt)

        job.done.connect(lambda img: self.preview.show_detail(img, region, gen))
        job.finished.connect(finish)
        job.finished.connect(job.deleteLater)
        job.start()

    def _run(self, fn, ok, bad, progress=None):
        job = Job(fn)
        self.running = job
        self.jobs.append(job)

        def moved(a, b):                                  # drives the sidebar's loading line
            self.loading.emit(a, b if a else 0)           # still at 0%: the sliding "running" segment instead of an empty bar

        def finish():
            self.running = None
            if job in self.jobs:
                self.jobs.remove(job)
            if self.rerun:
                self.rerun = False
                self.timer.start()
            else:
                self.loaded.emit()

        job.done.connect(ok)
        job.failed.connect(bad)
        job.progress.connect(moved)
        if progress:
            job.progress.connect(progress)
        job.finished.connect(finish)
        moved(0, 0)
        job.start()

    def generate(self):
        pool, o = self.pool(), self.options()
        if not pool:
            return
        scope = self.scope.currentData()
        name = "_".join([self.source.currentText().lower().replace(" + ", "-").replace(" ", "-"),
                         (self.group_value() or ("", ""))[1] if scope == "group" else scope])

        def work(progress):
            paths, layout = self._prepare(pool, o)
            return render.save(render.render(paths, layout, o.bg, progress), name, o), layout

        def done(res):
            path, layout = res
            self.make.setEnabled(True)
            self.info.setText(f"Saved {path.name}  ({layout.width} × {layout.height})")
            self.log.emit(f"Collage saved: {path}")
            os.startfile(path)

        def bad(msg):
            self.make.setEnabled(True)
            self.info.setText("Failed: " + msg)

        def prog(a, b):
            self.info.setText(f"Rendering full size... {100 * a // max(1, b)}%")

        if self.running:
            self.info.setText("Wait for the preview to finish, then try again.")
            return
        self.make.setEnabled(False)
        self.info.setText("Rendering full size... 0%")
        self._run(work, done, bad, prog)

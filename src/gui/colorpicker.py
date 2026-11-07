"""Own color picker (replaces the stock Windows dialog): saturation/brightness field, hue bar, hex input, presets."""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from . import theme
from .chrome import Modal
from .sidebar import FOLDER_COLORS
from .widgets import label

PRESETS = list(FOLDER_COLORS) + ["#000000", "#232323", "#808080", "#ffffff"]


class Field(QWidget):
    """Saturation (x) / brightness (y) square for the current hue."""
    changed = Signal(float, float)

    def __init__(self):
        super().__init__()
        self.h, self.s, self.v = 0.0, 1.0, 1.0
        self.setMinimumSize(240, 170)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        clip = QPainterPath()
        clip.addRoundedRect(r, 8, 8)
        p.setClipPath(clip)
        p.fillRect(r, QColor.fromHsvF(self.h, 1, 1))
        g = QLinearGradient(r.left(), 0, r.right(), 0)
        g.setColorAt(0, QColor(255, 255, 255))
        g.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(r, g)
        g = QLinearGradient(0, r.top(), 0, r.bottom())
        g.setColorAt(0, QColor(0, 0, 0, 0))
        g.setColorAt(1, QColor(0, 0, 0))
        p.fillRect(r, g)
        p.setClipping(False)
        c = QPointF(r.left() + self.s * r.width(), r.top() + (1 - self.v) * r.height())
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 160), 3))
        p.drawEllipse(c, 7, 7)
        p.setPen(QPen(QColor("white"), 2))
        p.drawEllipse(c, 7, 7)

    def pick(self, pos):
        r = self.rect()
        self.s = min(1.0, max(0.0, pos.x() / max(1, r.width())))
        self.v = 1.0 - min(1.0, max(0.0, pos.y() / max(1, r.height())))
        self.update()
        self.changed.emit(self.s, self.v)

    def mousePressEvent(self, e):
        self.pick(e.position())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton:
            self.pick(e.position())


class HueBar(QWidget):
    changed = Signal(float)

    def __init__(self):
        super().__init__()
        self.h = 0.0
        self.setFixedHeight(18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 3, -1, -3)
        g = QLinearGradient(r.left(), 0, r.right(), 0)
        for i in range(7):
            g.setColorAt(i / 6, QColor.fromHsvF(min(i / 6, 0.999), 1, 1))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawRoundedRect(r, 6, 6)
        x = r.left() + self.h * r.width()
        p.setBrush(QColor.fromHsvF(min(self.h, 0.999), 1, 1))
        p.setPen(QPen(QColor("white"), 2))
        p.drawEllipse(QPointF(x, self.height() / 2), 7, 7)

    def pick(self, pos):
        self.h = min(1.0, max(0.0, pos.x() / max(1, self.width())))
        self.update()
        self.changed.emit(self.h)

    def mousePressEvent(self, e):
        self.pick(e.position())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton:
            self.pick(e.position())


class Swatch(QFrame):
    clicked = Signal(str)

    def __init__(self, color, size=26):
        super().__init__()
        self.color = color
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"QFrame {{ background: {color}; border: 1px solid #3a4160; border-radius: 6px; }}"
                           f"QFrame:hover {{ border: 2px solid white; }}")

    def mousePressEvent(self, e):
        self.clicked.emit(self.color)


class ColorDialog(Modal):
    def __init__(self, parent, initial, title="Choose a color"):
        super().__init__(parent, title, 380, resizable=False)
        self.field, self.hue = Field(), HueBar()
        self.body.addWidget(self.field, 1)
        self.body.addWidget(self.hue)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.preview = QFrame()
        self.preview.setFixedSize(46, 36)
        self.hex = QLineEdit()
        self.hex.setMaxLength(7)
        self.hex.setPlaceholderText("#rrggbb")
        row.addWidget(self.preview)
        row.addWidget(self.hex, 1)
        self.body.addLayout(row)
        self.body.addWidget(label("Presets", "dim"))
        grid = QHBoxLayout()
        grid.setSpacing(6)
        for c in PRESETS[:12]:
            sw = Swatch(c)
            sw.clicked.connect(self.set_color)
            grid.addWidget(sw)
        grid.addStretch()
        self.body.addLayout(grid)
        self.field.changed.connect(lambda s, v: self._from_hsv(self.hue.h, s, v))
        self.hue.changed.connect(lambda h: self._from_hsv(h, self.field.s, self.field.v))
        self.hex.textEdited.connect(self._from_hex)
        self.footer("Select", None)
        self.color = QColor(initial)
        self.set_color(self.color.name())

    def _from_hsv(self, h, s, v):
        self.color = QColor.fromHsvF(min(h, 0.999), s, v)
        self.field.h = h
        self.field.update()
        self._refresh(hex_too=True)

    def _from_hex(self, text):
        c = QColor(text if text.startswith("#") else "#" + text)
        if c.isValid() and len(text.lstrip("#")) in (3, 6):
            self.set_color(c.name(), keep_text=True)

    def set_color(self, name, keep_text=False):
        c = QColor(name)
        h = c.hsvHueF()
        h = self.hue.h if h < 0 else h                     # grays have no hue: keep the current one
        self.color = c
        self.hue.h, self.field.h, self.field.s, self.field.v = h, h, c.hsvSaturationF(), c.valueF()
        self.hue.update()
        self.field.update()
        self._refresh(hex_too=not keep_text)

    def _refresh(self, hex_too=True):
        self.preview.setStyleSheet(f"QFrame {{ background: {self.color.name()}; border: 1px solid #3a4160; border-radius: 6px; }}")
        if hex_too:
            self.hex.setText(self.color.name().upper())


def pick_color(parent, initial, title="Choose a color"):
    """Returns the chosen QColor, or None when cancelled."""
    d = ColorDialog(parent, initial, title)
    return d.color if d.exec() else None

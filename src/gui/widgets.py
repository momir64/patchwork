"""Small reusable widgets: wrapping layout, buttons with icons, segmented control, section headers."""
from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSizePolicy, QSpinBox,
                               QSpacerItem, QVBoxLayout, QWidget)

from ..core.names import fold
from . import icons, theme


class SearchCombo(QComboBox):
    """A dropdown you search in place: click it and the field itself turns into the search box (the current choice shows as a
    dim hint), the list below narrows to the entries containing what you type. Up / Down move, Enter or a click picks, Esc or
    clicking elsewhere cancels. When closed it is a normal dropdown: the text can not be selected or edited."""

    def __init__(self):
        super().__init__()
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setCompleter(None)
        le = self.lineEdit()
        le.setReadOnly(True)
        le.setCursor(Qt.CursorShape.ArrowCursor)
        le.setStyleSheet(f"QLineEdit {{ background: transparent; border: none; padding: 0; selection-background-color: transparent; "
                         f"selection-color: {theme.TEXT}; }}")
        le.installEventFilter(self)
        le.textChanged.connect(self._filter)
        self._pop = self._list = None

    def refit(self):
        """Make the box wide enough for its widest entry, so the box and the list that opens from it are the same width."""
        fm = self.fontMetrics()
        widest = max((fm.horizontalAdvance(self.itemText(i)) for i in range(self.count())), default=0)
        self.setMinimumWidth(max(140, widest + 12 + 8 + 28 + 14 + 8))      # text padding, drop-down arrow, scroll bar in the list, air

    # ---- the search state
    def _searching(self):
        return self._pop is not None

    def showPopup(self):
        if self._searching():
            return
        le = self.lineEdit()
        pop = QFrame(self.window(), Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        pop.setObjectName("searchpop")
        pop.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        pop.setStyleSheet(f"QFrame#searchpop {{ background: {theme.SURFACE2}; border: 1px solid #333a50; border-radius: {theme.RADIUS}px; }}"
                          f"QListWidget {{ background: transparent; border: none; outline: 0; }}"
                          f"QListWidget::item {{ min-height: 26px; padding: 0 8px; border-radius: 5px; color: {theme.TEXT}; }}"
                          f"QListWidget::item:selected {{ background: {theme.ACCENT_SOFT}; }}"
                          f"QListWidget::item:hover {{ background: #232839; }}")
        v = QVBoxLayout(pop)
        v.setContentsMargins(4, 4, 4, 4)
        lst = QListWidget()
        lst.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lst.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for i in range(self.count()):
            it = QListWidgetItem(self.itemText(i))
            it.setData(Qt.ItemDataRole.UserRole, i)
            lst.addItem(it)
        v.addWidget(lst)
        lst.itemClicked.connect(self._pick)
        self._pop, self._list, self._shown_text = pop, lst, self.currentText()
        le.setReadOnly(False)
        le.setPlaceholderText(self._shown_text)
        le.clear()
        lst.setCurrentRow(max(0, self.currentIndex()))
        self._place()
        pop.show()
        le.setFocus()
        lst.scrollToItem(lst.currentItem())
        QApplication.instance().installEventFilter(self)

    def _place(self):
        """Size the list from what is really in it: the row height Qt reports, the widest entry, and the visible row count."""
        lst = self._list
        shown = sum(not lst.item(r).isHidden() for r in range(lst.count()))
        row = max(26, lst.sizeHintForRow(0))
        rows = max(1, min(shown, 9))
        screen = self.screen().availableGeometry()
        w = min(self.width(), screen.width() - 20)                # the list is exactly as wide as the box (the box fits its widest entry)
        h = rows * row + 2 * lst.frameWidth() + 8 + 2 + 2
        self._pop.setFixedSize(w, h)
        pos = self.mapToGlobal(QPoint(0, self.height() + 2))
        if pos.x() + w > screen.right():
            pos.setX(screen.right() - w - 4)
        if pos.y() + h > screen.bottom():
            pos = self.mapToGlobal(QPoint(0, -h - 2))
            pos.setX(min(pos.x(), screen.right() - w - 4))
        self._pop.move(pos)

    def _filter(self, text):
        if not self._searching():
            return
        t = fold(text.strip())
        lst = self._list
        for r in range(lst.count()):
            lst.item(r).setHidden(bool(t) and t not in fold(lst.item(r).text()))
        for r in range(lst.count()):
            if not lst.item(r).isHidden():
                lst.setCurrentRow(r)
                break
        self._place()

    def _pick(self, item=None):
        item = item or self._list.currentItem()
        if item is None or item.isHidden():
            return
        idx = item.data(Qt.ItemDataRole.UserRole)
        self._close()
        self.setCurrentIndex(idx)
        if not KEYBOARD:                                  # picked with the mouse: the field does not stay focused
            QTimer.singleShot(0, lambda: (self.lineEdit().clearFocus(), self.clearFocus()))

    def _close(self):
        if not self._searching():
            return
        QApplication.instance().removeEventFilter(self)
        pop, self._pop, self._list = self._pop, None, None
        pop.close()
        pop.deleteLater()
        le = self.lineEdit()
        le.setReadOnly(True)
        le.setPlaceholderText("")
        le.setText(self.itemText(self.currentIndex()))
        le.deselect()

    def eventFilter(self, obj, ev):
        t = ev.type()
        le = self.lineEdit()
        if obj is le:
            if t in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
                if self._searching():
                    self._close()
                else:
                    self.showPopup()
                return True
            if t in (QEvent.Type.MouseButtonRelease, QEvent.Type.MouseMove) and not self._searching():
                return True                                                 # no dragging a text selection
            if t == QEvent.Type.FocusOut and self._searching() and ev.reason() != Qt.FocusReason.PopupFocusReason:
                self._close()
            if t == QEvent.Type.KeyPress and self._searching():
                k = ev.key()
                if k in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                    step, r, lst = (1 if k == Qt.Key.Key_Down else -1), self._list.currentRow(), self._list
                    while 0 <= r + step < lst.count():
                        r += step
                        if not lst.item(r).isHidden():
                            lst.setCurrentRow(r)
                            break
                    return True
                if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._pick()
                    return True
                if k == Qt.Key.Key_Escape:
                    self._close()
                    return True
        elif t == QEvent.Type.MouseButtonPress and self._searching():       # a click anywhere else cancels the search
            w = obj if isinstance(obj, QWidget) else None
            if w is not None and not (self._pop.isAncestorOf(w) or w is self._pop or self.isAncestorOf(w) or w is self):
                self._close()
        return super().eventFilter(obj, ev)

    def hidePopup(self):
        pass


class FlowLayout(QLayout):
    """Lays widgets out left to right and wraps to the next line when the window gets narrow."""

    def __init__(self, parent=None, spacing=8):
        super().__init__(parent)
        self.items, self._space = [], spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, i):
        return self.items[i] if 0 <= i < len(self.items) else None

    def takeAt(self, i):
        return self.items.pop(i) if 0 <= i < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._layout(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for i in self.items:
            s = s.expandedTo(i.minimumSize())
        m = self.contentsMargins()
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _layout(self, rect, test):
        x, y, line_h = rect.x(), rect.y(), 0
        for it in self.items:
            if it.isEmpty():
                continue
            hint = it.sizeHint()
            if x + hint.width() > rect.right() + 1 and line_h > 0:
                x, y, line_h = rect.x(), y + line_h + self._space, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._space
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


KEYBOARD = False        # set once the user presses Tab; until then buttons never show a focus ring


class Btn(QPushButton):
    """Button whose icon and text are separate labels: exact 8px gap, both centered on the same line."""
    GAP = 8

    def __init__(self, text="", icon=None, role=None, tip=None, size=17, height=None, pad=None, color=None):
        super().__init__()
        if role:
            self.setObjectName(role)
        self.role, self.icon_name, self.icon_size, self.fixed_color = role, icon, size, color
        self.full, self._hover, self._pixmap = text, False, None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus if KEYBOARD else Qt.FocusPolicy.NoFocus)
        self.setFixedHeight(height or theme.HEIGHT + 2)      # +2: the border, so it matches inputs and dropdowns
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)     # natural width unless a layout stretches it
        if tip:
            self.setToolTip(tip)
        self.lay = QHBoxLayout(self)
        pad = (0 if role == "icon" else 10 if role == "ghost" else 12) if pad is None else pad
        self.lay.setContentsMargins(pad, 0, pad, 0)
        self.lay.setSpacing(0)
        self.lead = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.trail = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.ic, self.tx = QLabel(), QLabel(text)
        self.ic.setFixedSize(size, size)
        self.ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tx.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        for w in (self.ic, self.tx):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.lay.addItem(self.lead)
        self.lay.addWidget(self.ic)
        self.lay.addWidget(self.tx)
        self.lay.addItem(self.trail)
        if role == "icon":
            self.setFixedWidth(self.height())
        self.toggled.connect(lambda _: self._paint())
        self._sync()

    # ---- content
    def setText(self, text):
        self.full_shown = text
        self.tx.setText(text)
        self._sync()

    def text(self):
        return self.tx.text()

    def set_icon_name(self, name):
        self.icon_name = name
        self._sync()

    def set_pixmap(self, pm):
        self._pixmap = pm
        self._sync()

    def align_left(self):
        self.lead.changeSize(0, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        self.lay.invalidate()

    def _sync(self):
        has_text = bool(self.tx.text())
        has_icon = bool(self.icon_name or self._pixmap)
        self.tx.setVisible(has_text)
        self.ic.setVisible(has_icon)
        self.tx.setContentsMargins(self.GAP if has_icon else 0, 0, 0, 3)     # 3px: the font has more room below the baseline than above the caps
        self._paint()
        self.updateGeometry()

    def _color(self):
        if self.fixed_color:
            return self.fixed_color
        if not self.isEnabled():
            return "#8a85ad" if self.role in ("primary", "dangerfill") else theme.DIM
        if self.role in ("primary", "dangerfill"):
            return "#ffffff"
        if self.role == "seg":
            return theme.TEXT if (self.isChecked() or self._hover) else theme.MUTED
        if self.role == "toggle" and self.isChecked():
            return theme.ACCENT_H
        if self.role == "bignav" and self.isChecked():
            return "#ffffff"
        if self.role == "ghost":
            return theme.TEXT if self._hover else theme.MUTED
        return theme.TEXT

    def _paint(self):
        col = self._color()
        self.tx.setStyleSheet(f"color: {col}; background: transparent;" + (" font-weight: 600;" if self.role in ("primary", "dangerfill") or (self.role == "bignav" and self.isChecked()) else ""))
        if self._pixmap is not None:
            self.ic.setPixmap(self._pixmap)
        elif self.icon_name:
            self.ic.setPixmap(icons.pixmap(self.icon_name, col, self.icon_size))

    def enterEvent(self, e):
        self._hover = True
        self._paint()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self._paint()
        super().leaveEvent(e)

    def changeEvent(self, e):
        if e.type() == QEvent.Type.EnabledChange:
            self._paint()
        super().changeEvent(e)

    def sizeHint(self):
        return QSize(self.lay.sizeHint().width(), self.height())

    def minimumSizeHint(self):
        return self.sizeHint()


def button(text="", icon=None, role=None, tip=None, color=None, size=17) -> Btn:
    return Btn(text, icon, role, tip, size=size, color=color)


class Segmented(QFrame):
    """Rounded container with flat toggle buttons, exactly one active. Emits changed(value)."""
    changed = Signal(object)
    reclicked = Signal(object)              # the already active segment was clicked again

    def __init__(self, options, value=None, icons_=None):
        super().__init__()
        self.setObjectName("segbar")
        self.setFixedHeight(theme.HEIGHT + 2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = {}
        h = QHBoxLayout(self)
        h.setContentsMargins(3, 3, 3, 3)
        h.setSpacing(2)
        for text, val in options:
            b = Btn(text, (icons_ or {}).get(val), "seg", size=16, height=theme.HEIGHT - 6, pad=12)
            b.setCheckable(True)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.clicked.connect(lambda _=False, v=val: self.reclicked.emit(v) if v == self.value else self.set_value(v))
            self.group.addButton(b)
            h.addWidget(b, 1)
            self.buttons[val] = b
        self.value = value if value in self.buttons else options[0][1]
        self.buttons[self.value].setChecked(True)

    def set_value(self, v, emit=True):
        if v not in self.buttons:
            return
        changed = v != self.value
        self.value = v
        self.buttons[v].setChecked(True)
        if emit and changed:
            self.changed.emit(v)

    def set_enabled_for(self, value, enabled):
        self.buttons[value].setEnabled(enabled)


class Chips(QWidget):
    """Wrapping row of pill toggles (exclusive)."""
    changed = Signal(object)

    def __init__(self, options, value=None):
        super().__init__()
        self.flow = FlowLayout(self, 5)
        self.group = QButtonGroup(self)
        self.buttons = {}
        for text, val in options:
            b = QPushButton(text)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, v=val: self.set_value(v))
            self.group.addButton(b)
            self.flow.addWidget(b)
            self.buttons[val] = b
        self.value = value if value in self.buttons else options[0][1]
        self.buttons[self.value].setChecked(True)

    def set_value(self, v, emit=True):
        self.value = v
        self.buttons[v].setChecked(True)
        if emit:
            self.changed.emit(v)


def label(text, role=None, wrap=False) -> QLabel:
    l = QLabel(text)
    if role:
        l.setObjectName(role)
    l.setWordWrap(wrap)
    return l


def divider() -> QFrame:
    f = QFrame()
    f.setObjectName("divider")
    return f


def section_header(text) -> QLabel:
    l = QLabel(text.upper())
    l.setObjectName("section")
    l.setContentsMargins(0, 0, 0, 0)
    return l


def form_row(name, widget, label_w=84) -> QWidget:
    """Label on the left, control on the right - every row uses the same label width."""
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(12)
    l = QLabel(name)
    l.setObjectName("muted")
    l.setFixedWidth(label_w)
    h.addWidget(l)
    h.addWidget(widget, 1)
    return w


def stacked_row(name, widget) -> QWidget:
    """Label above a full-width control (for wide controls)."""
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(6)
    v.addWidget(label(name, "muted"))
    v.addWidget(widget)
    return w


class StatusLabel(QLabel):
    """One-line message that elides with ... instead of forcing the window wider."""

    def __init__(self):
        super().__init__()
        self.setObjectName("muted")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.full = ""

    def set_message(self, text):
        self.full = text.splitlines()[0] if text else ""
        self.setToolTip(text)
        self._elide()

    def _elide(self):
        self.setText(self.fontMetrics().elidedText(self.full, Qt.TextElideMode.ElideRight, max(0, self.width())))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()


class SearchBox(QFrame):
    """Input look-alike with a vertically centered magnifier and a clear button."""
    textChanged = Signal(str)

    def __init__(self, placeholder="Search..."):
        super().__init__()
        self.setObjectName("search")
        h = QHBoxLayout(self)
        h.setContentsMargins(11, 0, 4, 0)
        h.setSpacing(8)
        ic = QLabel()
        ic.setPixmap(icons.pixmap("search", theme.DIM, 16))
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setStyleSheet("QLineEdit { background: transparent; border: none; padding: 0; min-height: 30px; }")
        self.edit.textChanged.connect(self.textChanged)
        self.edit.installEventFilter(self)
        h.addWidget(ic)
        h.addWidget(self.edit, 1)
        self.clear_btn = QPushButton()                 # own clear button: centered, same muted look as the magnifier
        self.clear_btn.setObjectName("mini")
        self.clear_btn.setIcon(icons.icon("x", theme.DIM, 14))
        self.clear_btn.setIconSize(QSize(14, 14))
        self.clear_btn.setFixedSize(24, 24)
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clear_btn.setToolTip("Clear")
        self.clear_btn.clicked.connect(self.edit.clear)
        self.clear_btn.setVisible(False)
        self.edit.textChanged.connect(lambda t: self.clear_btn.setVisible(bool(t)))
        h.addWidget(self.clear_btn)

    def text(self):
        return self.edit.text()

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self.setProperty("focus", ev.type() == QEvent.Type.FocusIn)
            self.style().unpolish(self)
            self.style().polish(self)
        return False


def vbox(*widgets, spacing=8, margins=(0, 0, 0, 0)) -> QVBoxLayout:
    v = QVBoxLayout()
    v.setSpacing(spacing)
    v.setContentsMargins(*margins)
    for w in widgets:
        v.addWidget(w) if isinstance(w, QWidget) else v.addLayout(w)
    return v


def hbox(*widgets, spacing=8, margins=(0, 0, 0, 0)) -> QHBoxLayout:
    h = QHBoxLayout()
    h.setSpacing(spacing)
    h.setContentsMargins(*margins)
    for w in widgets:
        if w == "stretch":
            h.addStretch()
        elif isinstance(w, QWidget):
            h.addWidget(w)
        else:
            h.addLayout(w)
    return h


class UnitSpin(QSpinBox):
    """Number input whose unit (px, %...) is shown right-aligned inside the field, outside the editable text,
    so typing never has to deal with it."""

    def __init__(self, unit="", singular=None):
        """singular: the unit shown while the value is 1 ('song' for 'songs')."""
        super().__init__()
        self.unit, self.singular = unit, singular
        self.unit_lbl = QLabel(unit, self.lineEdit())
        self.unit_lbl.setStyleSheet(f"color: {theme.DIM}; background: transparent;")
        self.unit_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        w = self.unit_lbl.fontMetrics().horizontalAdvance(unit) + 4 if unit else 0
        self.lineEdit().setTextMargins(0, 0, w, 0)
        self.valueChanged.connect(self._place)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def _place(self, *_):
        le = self.lineEdit()
        self.unit_lbl.setText(self.singular if self.singular and self.value() == 1 else self.unit)
        self.unit_lbl.adjustSize()
        self.unit_lbl.move(le.width() - self.unit_lbl.width() - 2, (le.height() - self.unit_lbl.height()) // 2)
        self.unit_lbl.setVisible(not (self.specialValueText() and self.value() == self.minimum()))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place()

    def showEvent(self, e):
        super().showEvent(e)
        self._place()


class ProgressLine(QWidget):
    """Thin rounded progress bar. Everything, including the sliding "working..." segment, is clipped to the rounded track,
    so nothing ever sticks out over the corners (QProgressBar's busy chunk does)."""

    def __init__(self):
        super().__init__()
        self.lo, self.hi, self.val, self.phase = 0, 100, 0, 0.0
        self.setFixedHeight(6)
        self.timer = QTimer(self, interval=16)
        self.timer.timeout.connect(self._tick)

    def setRange(self, lo, hi):
        self.lo, self.hi = lo, hi
        self._timer()
        self.update()

    def setValue(self, v):
        self.val = v
        self.update()

    def _timer(self):
        on = self.hi <= self.lo and self.isVisible()
        if on and not self.timer.isActive():
            self.timer.start()
        elif not on:
            self.timer.stop()

    def showEvent(self, e):
        super().showEvent(e)
        self._timer()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.timer.stop()

    def _tick(self):
        self.phase = (self.phase + 0.012) % 1.0
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        track = QPainterPath()
        track.addRoundedRect(r, r.height() / 2, r.height() / 2)
        p.fillPath(track, QColor(theme.SURFACE2))
        p.setClipPath(track)
        if self.hi > self.lo:
            w = r.width() * (self.val - self.lo) / (self.hi - self.lo)
            if w > 0:
                p.fillRect(QRectF(0, 0, w, r.height()), QColor(theme.ACCENT))
        else:
            seg = r.width() * 0.3
            x = -seg + (r.width() + seg) * self.phase
            p.fillRect(QRectF(x, 0, seg, r.height()), QColor(theme.ACCENT))

"""Design tokens + the application stylesheet (dark). 8px spacing grid, 8px control radius, 34px control height."""
from ..core.config import RES

BG, SURFACE, SURFACE2, BORDER = "#0d0f14", "#14171f", "#1b1f2b", "#262b3b"
SIDEBAR = "#080a0e"      # darker than the content area, so the bottom bar never merges into it
TEXT, MUTED, DIM = "#e8eaf0", "#8b93a7", "#5d657a"
ACCENT, ACCENT_H, ACCENT_SOFT, GOLD = "#8b6cff", "#9d83ff", "#2a2450", "#ffc933"
DANGER = "#ff6b81"
ASSETS = (RES / "assets").as_posix()
RADIUS, HEIGHT, GAP = 8, 34, 8
FONT = '"Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif'

QSS = f"""
* {{ font-family: {FONT}; font-size: 13px; color: {TEXT}; outline: 0; }}
QMainWindow, QDialog, QWidget#root {{ background: {BG}; }}
QWidget {{ selection-background-color: {ACCENT}; }}
QToolTip {{ background: {SURFACE2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 6px 8px; border-radius: 5px; }}

/* ---------- layout surfaces */
QWidget#sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER}; }}
QWidget#panel {{ background: {SURFACE}; }}
QWidget#bar {{ background: {SURFACE}; border-top: 1px solid {BORDER}; }}
QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame#divider {{ background: {BORDER}; max-height: 1px; min-height: 1px; border: none; }}

/* ---------- text */
QLabel {{ background: transparent; }}
QLabel#h1 {{ font-size: 22px; font-weight: 700; }}
QLabel#cardtitle {{ font-size: 13.5px; font-weight: 700; }}
QLabel#brand {{ font-size: 15px; font-weight: 700; }}
QLabel#status {{ font-size: 11.5px; color: {DIM}; }}
QLabel#section {{ font-size: 11px; font-weight: 700; color: {DIM}; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#dim {{ color: {DIM}; }}
QLabel#chip {{ background: {SURFACE2}; border-radius: 9px; padding: 2px 10px; color: {MUTED}; font-size: 12px; }}

/* ---------- buttons (icon + text live in child labels, see widgets.Btn) */
QPushButton, QToolButton {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: {RADIUS}px;
    padding: 0 14px; min-height: {HEIGHT}px; }}
QPushButton:hover, QToolButton:hover {{ background: #232839; border-color: #333a50; }}
QPushButton:pressed, QToolButton:pressed {{ background: #2a3047; }}
QPushButton:disabled, QToolButton:disabled {{ color: {DIM}; background: {SURFACE}; border-color: {SURFACE2}; }}
QPushButton:focus {{ border-color: {ACCENT}; }}
QPushButton#primary {{ background: {ACCENT}; border: 1px solid {ACCENT}; color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background: {ACCENT_H}; border-color: {ACCENT_H}; }}
QPushButton#primary:disabled {{ background: #35305c; border-color: #35305c; color: #8a85ad; }}
QPushButton#ghost, QToolButton#ghost {{ background: transparent; border: 1px solid transparent; color: {MUTED}; min-height: 0; }}
QPushButton#ghost:hover, QToolButton#ghost:hover {{ background: {SURFACE2}; color: {TEXT}; }}
QPushButton#ghost:disabled {{ background: transparent; border-color: transparent; }}
QPushButton#danger:hover {{ background: #3a1f29; border-color: {DANGER}; }}
QPushButton#icon, QToolButton#icon {{ padding: 0; }}
QPushButton#toggle:checked {{ background: {ACCENT_SOFT}; border-color: {ACCENT}; }}
QPushButton#mini {{ background: transparent; border: none; border-radius: 5px; min-height: 22px; min-width: 22px; padding: 0; }}
QPushButton#mini:hover {{ background: #2e3550; }}

/* segmented control: one rounded container, flat buttons inside */
QFrame#segbar {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: {RADIUS}px; }}
QPushButton#seg {{ background: transparent; border: 1px solid transparent; border-radius: {RADIUS - 3}px; min-height: 0; padding: 0; }}
QPushButton#seg:hover {{ background: #232839; }}
QPushButton#seg:checked {{ background: {ACCENT_SOFT}; border-color: {ACCENT}; }}
QPushButton#seg:disabled {{ background: transparent; border-color: transparent; }}
QPushButton#chip {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; min-height: 28px; padding: 0 10px; color: {MUTED}; }}
QPushButton#chip:hover {{ color: {TEXT}; background: {SURFACE2}; }}
QPushButton#chip:checked {{ background: {ACCENT_SOFT}; border-color: {ACCENT}; color: {TEXT}; font-weight: 600; }}

QFrame#search {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: {RADIUS}px; min-height: {HEIGHT}px; max-height: {HEIGHT}px; }}
QFrame#search:hover {{ border-color: #333a50; }}
QFrame#search[focus="true"] {{ border-color: {ACCENT}; }}

/* ---------- navigation */
QPushButton#nav {{ background: transparent; border: none; border-radius: {RADIUS}px; text-align: left; padding: 0 12px;
    color: {MUTED}; min-height: 38px; font-size: 13.5px; }}
QPushButton#nav:hover {{ background: {SURFACE2}; color: {TEXT}; }}
QPushButton#nav:checked {{ background: {ACCENT_SOFT}; color: {TEXT}; font-weight: 600; }}
QPushButton#bignav:checked {{ background: {ACCENT}; border: 1px solid {ACCENT}; }}
QPushButton#bignav:checked:hover {{ background: {ACCENT_H}; border-color: {ACCENT_H}; }}
QPushButton#navhl {{ background: #1a1640; border: 1px solid {ACCENT_SOFT}; border-radius: {RADIUS}px; text-align: left; padding: 0 12px; }}
QPushButton#navhl:hover {{ background: {ACCENT_SOFT}; border-color: {ACCENT}; }}
QPushButton#navhl:checked {{ background: {ACCENT_SOFT}; border-color: {ACCENT}; }}
QPushButton#navsub {{ background: transparent; border: none; border-radius: 6px; text-align: left; padding: 0 12px;
    color: {MUTED}; min-height: 32px; }}
QPushButton#navsub:hover, QPushButton#navsub[held="true"] {{ background: {SURFACE2}; color: {TEXT}; }}
QPushButton#navsub:checked {{ background: {ACCENT_SOFT}; color: {TEXT}; }}

QPushButton QLabel#count {{ color: {DIM}; font-size: 12px; font-weight: 400; }}

/* ---------- inputs */
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: {RADIUS}px;
    padding: 0 12px; min-height: {HEIGHT}px; selection-background-color: {ACCENT}; }}
QPlainTextEdit {{ padding: 8px 12px; }}
QLineEdit:hover, QSpinBox:hover, QComboBox:hover {{ border-color: #333a50; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{ color: {DIM}; background: {SURFACE}; }}
QComboBox {{ padding-right: 8px; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{ image: url({ASSETS}/chevron_down.svg); width: 12px; height: 12px; }}
QComboBox {{ combobox-popup: 0; }}
QComboBox QAbstractItemView {{ background: {SURFACE2}; border: 1px solid #333a50; border-radius: {RADIUS}px; padding: 4px 2px 4px 4px;
    selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT}; outline: 0; }}
QComboBox QAbstractItemView::item {{ min-height: 28px; padding: 0 8px; border-radius: 5px; }}
QComboBox QAbstractItemView::item:hover {{ background: #232839; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}

QCheckBox {{ spacing: 10px; min-height: 26px; background: transparent; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid #3a4160; background: {SURFACE2}; }}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url({ASSETS}/check.svg); }}
QRadioButton {{ spacing: 10px; min-height: 26px; background: transparent; }}
QRadioButton::indicator {{ width: 16px; height: 16px; border-radius: 9px; border: 1px solid #3a4160; background: {SURFACE2}; }}
QRadioButton::indicator:hover {{ border-color: {ACCENT}; }}
QRadioButton::indicator:checked {{ border: 5px solid {ACCENT}; background: white; }}
QCheckBox::indicator:disabled {{ background: {SURFACE}; border-color: {BORDER}; }}

QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: white; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}

/* ---------- scrolling */
QScrollArea {{ border: none; background: transparent; }}
QListView, QListWidget {{ background: transparent; border: none; }}
QListWidget {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: {RADIUS}px; padding: 4px; }}
QListWidget::item {{ min-height: 32px; border-radius: 5px; padding: 0 8px; }}
QListWidget::item:selected {{ background: {ACCENT_SOFT}; }}
QListWidget#settingsnav {{ background: transparent; border: none; border-right: 1px solid {BORDER}; border-radius: 0; padding: 0 12px 0 0; }}
QListWidget#settingsnav::item {{ min-height: 36px; padding: 0 12px; border-radius: 6px; color: {MUTED}; }}
QListWidget#settingsnav::item:hover {{ background: {SURFACE2}; color: {TEXT}; }}
QListWidget#settingsnav::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; font-weight: 600; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}   /* any margin along the bar's length makes Qt drop the handle's rounded corners */
QScrollBar::handle:vertical {{ background: #2c3249; border: 0px; border-radius: 3px; min-height: 40px; margin: 0 2px; }}
QScrollBar::handle:vertical:hover {{ background: #404868; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #2c3249; border: 0px; border-radius: 3px; min-width: 40px; margin: 2px 0; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QProgressBar {{ background: {SURFACE2}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}

QMenu {{ background: {SURFACE2}; border: 1px solid #333a50; border-radius: {RADIUS}px; padding: 5px; }}
QMenu::item {{ padding: 7px 14px 7px 12px; margin: 0 1px; border-radius: 5px; min-width: 150px; }}
QMenu::icon {{ padding-left: 6px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; }}
QMenu::item:disabled {{ color: {DIM}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 6px 8px; }}
QDialog {{ background: {BG}; }}

/* ---------- own window chrome */
QWidget#titlebar {{ background: {SIDEBAR}; border-bottom: 1px solid {BORDER}; }}
QPushButton#winbtn, QPushButton#winclose {{ background: transparent; border: none; border-radius: 0; padding: 0;
    min-width: 46px; max-width: 46px; min-height: 40px; max-height: 40px; }}
QPushButton#winbtn:hover {{ background: {SURFACE2}; }}
QPushButton#winclose:hover {{ background: #c42b1c; }}
QFrame#dialog {{ background: {BG}; border: 1px solid #333a50; border-radius: {RADIUS}px; }}
QWidget#dlgbar {{ background: transparent; }}
QLabel#dlgtitle {{ font-size: 17px; font-weight: 700; }}
QPushButton#dlgclose {{ background: transparent; border: none; border-radius: 8px; padding: 0; min-width: 32px; max-width: 32px;
    min-height: 32px; max-height: 32px; }}
QPushButton#dlgclose:hover {{ background: {SURFACE2}; }}
QPushButton#dangerfill {{ background: #d64560; border: 1px solid #d64560; font-weight: 600; }}
QPushButton#dangerfill:hover {{ background: #e5566f; border-color: #e5566f; }}
QPushButton#dangerfill QLabel {{ color: white; }}
QWidget#scrollinner {{ background: transparent; }}
"""

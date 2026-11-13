"""Calm traffic-light look: a quiet off-white / charcoal app where colour only ever means safety.

Green = safe to delete, amber = your choice, red = keep. The one blue is for buttons that do things.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette

from ..knowledge import CHOICE, KEEP, SAFE

LIGHT = {
    "bg": "#f4f5f7", "panel": "#ffffff", "side": "#eceef2", "text": "#1b2129", "muted": "#5b6470",
    "faint": "#8b939e", "border": "#e0e3e8", "hover": "#f0f3f8", "select": "#e6edfb",
    "accent": "#2457c5", "accent_text": "#ffffff", "accent_hover": "#1d4aab",
    "danger": "#c4321f", "danger_hover": "#a82a19",
    SAFE: "#14804a", SAFE + "_bg": "#e2f4e9", CHOICE: "#9a5a00", CHOICE + "_bg": "#fcefd6",
    KEEP: "#b42318", KEEP + "_bg": "#fde6e3", "bar": "#c9d2e0", "bar_bg": "#edf0f4",
}
DARK = {
    "bg": "#111317", "panel": "#181b20", "side": "#14161a", "text": "#e8ebf0", "muted": "#a1a9b4",
    "faint": "#6e7682", "border": "#272b32", "hover": "#1f232a", "select": "#1f2b44",
    "accent": "#5d8dff", "accent_text": "#0b1020", "accent_hover": "#7aa2ff",
    "danger": "#ff6b5e", "danger_hover": "#ff8478",
    SAFE: "#4fd18b", SAFE + "_bg": "#13301f", CHOICE: "#f2b552", CHOICE + "_bg": "#35280f",
    KEEP: "#ff7b72", KEEP + "_bg": "#3a1715", "bar": "#3a4558", "bar_bg": "#20242b",
}

current = dict(LIGHT)


def is_dark(choice):
    if choice == "dark":
        return True
    if choice == "light":
        return False
    hints = QGuiApplication.styleHints()
    return hasattr(hints, "colorScheme") and hints.colorScheme() == Qt.ColorScheme.Dark


def color(key):
    return QColor(current[key])


def apply(app, choice):
    current.clear()
    current.update(DARK if is_dark(choice) else LIGHT)
    c = current
    pal = QPalette()
    for role, key in ((QPalette.ColorRole.Window, "bg"), (QPalette.ColorRole.Base, "panel"),
                      (QPalette.ColorRole.AlternateBase, "hover"), (QPalette.ColorRole.Text, "text"),
                      (QPalette.ColorRole.WindowText, "text"), (QPalette.ColorRole.Button, "panel"),
                      (QPalette.ColorRole.ButtonText, "text"), (QPalette.ColorRole.Highlight, "select"),
                      (QPalette.ColorRole.HighlightedText, "text"), (QPalette.ColorRole.ToolTipBase, "panel"),
                      (QPalette.ColorRole.ToolTipText, "text"), (QPalette.ColorRole.PlaceholderText, "faint")):
        pal.setColor(role, QColor(c[key]))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(c["faint"]))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(c["faint"]))
    app.setPalette(pal)
    app.setStyleSheet(QSS % c)


QSS = """
* { font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif; font-size: 10pt; color: %(text)s; }
QMainWindow, QDialog, #page { background: %(bg)s; }
QToolTip { background: %(panel)s; color: %(text)s; border: 1px solid %(border)s; padding: 6px; }
#sidebar { background: %(side)s; border-right: 1px solid %(border)s; }
#brand { font-size: 17pt; font-weight: 700; }
#brandSub { color: %(muted)s; font-size: 9pt; }
#nav { background: transparent; border: none; outline: none; }
#nav::item { padding: 9px 12px; border-radius: 8px; margin: 1px 8px; color: %(muted)s; }
#nav::item:hover { background: %(hover)s; color: %(text)s; }
#nav::item:selected { background: %(panel)s; color: %(text)s; font-weight: 600; }
#h1 { font-size: 18pt; font-weight: 700; }
#h2 { font-size: 12.5pt; font-weight: 600; }
#muted { color: %(muted)s; }
#faint { color: %(faint)s; font-size: 9pt; }
#card, #detail, #selbar { background: %(panel)s; border: 1px solid %(border)s; border-radius: 12px; }
#selbar { border-radius: 0; border-width: 1px 0 0 0; }
#bigNumber { font-size: 20pt; font-weight: 700; }
QPushButton { background: %(panel)s; border: 1px solid %(border)s; border-radius: 8px; padding: 7px 14px; }
QPushButton:hover { background: %(hover)s; }
QPushButton:disabled { color: %(faint)s; }
QPushButton#primary { background: %(accent)s; color: %(accent_text)s; border: none; font-weight: 600; }
QPushButton#primary:hover { background: %(accent_hover)s; }
QPushButton#primary:disabled { background: %(border)s; color: %(faint)s; }
QPushButton#danger { background: %(danger)s; color: #ffffff; border: none; font-weight: 600; }
QPushButton#danger:hover { background: %(danger_hover)s; }
QPushButton#link { background: transparent; border: none; color: %(accent)s; padding: 2px 4px; text-align: left; }
QPushButton#link:hover { text-decoration: underline; }
QTreeWidget, QListWidget, QTextEdit, QPlainTextEdit { background: %(panel)s; border: 1px solid %(border)s;
    border-radius: 10px; outline: none; }
QTreeWidget::item { padding: 5px 2px; border: none; }
QTreeWidget::item:hover { background: %(hover)s; }
QTreeWidget::item:selected { background: %(select)s; color: %(text)s; }
QHeaderView::section { background: %(panel)s; color: %(muted)s; border: none; border-bottom: 1px solid %(border)s;
    padding: 6px 6px; font-weight: 600; font-size: 9pt; }
QComboBox, QSpinBox, QLineEdit { background: %(panel)s; border: 1px solid %(border)s; border-radius: 7px;
    padding: 5px 8px; }
QComboBox QAbstractItemView { background: %(panel)s; border: 1px solid %(border)s; selection-background-color: %(select)s; }
QProgressBar { background: %(bar_bg)s; border: none; border-radius: 4px; height: 8px; text-align: center;
    color: transparent; }
QProgressBar::chunk { background: %(accent)s; border-radius: 4px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: %(border)s; border-radius: 4px; min-height: 30px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: %(border)s; border-radius: 4px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollArea { border: none; background: transparent; }
QRadioButton, QCheckBox { spacing: 8px; }
"""


def size_text(n):
    n = float(n or 0)
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            if unit == "bytes":
                return "%d bytes" % n
            return ("%.1f %s" if n < 100 else "%.0f %s") % (n, unit)
        n /= 1024.0
    return ""


def age_text(ts):
    import time
    if not ts:
        return ""
    days = (time.time() - ts) / 86400
    if days < 1:
        return "today"
    if days < 2:
        return "yesterday"
    if days < 31:
        return "%d days ago" % days
    if days < 365:
        return "%d months ago" % (days // 30)
    years = days / 365
    return "%d year%s ago" % (years, "" if years < 2 else "s")

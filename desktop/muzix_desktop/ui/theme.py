"""Muzix's look in Qt (DESIGN.md in the repository): midnight navy panels, bone text, a marigold
accent, Saira for words and JetBrains Mono for codes and labels (bundled under fonts/, OFL)."""

import os

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QImage, QPainter, QPalette, QPixmap

HERE = os.path.dirname(os.path.dirname(__file__))
ASSETS = os.path.join(HERE, "assets")

NAVY, DEEP, PANEL, RAISED, HIGH = "#0a1020", "#060a15", "#121b2e", "#1f2738", "#2d3341"
BONE, DIM, FAINT = "#f1e7d0", "#aca79b", "#87847f"
ACCENT, ON_ACCENT, OK, BAD = "#f2a93b", "#0b0b0f", "#4fb286", "#ef5350"
LINE, LINE_STRONG = "#1c263b", "#29344d"

UI, MONO = "Saira", "JetBrains Mono"


def load_fonts():
    folder = os.path.join(ASSETS, "fonts")
    if os.path.isdir(folder):
        for n in sorted(os.listdir(folder)):
            if n.endswith((".ttf", ".otf")):
                QFontDatabase.addApplicationFont(os.path.join(folder, n))


def icon() -> QIcon:
    """Muzix's own icon (frontend/public): drawn for each size, so the small ones in the tray and the
    title bar are sharp (16 and 20 px are Muzix's simpler drawing for those sizes: scripts/icons.py), and the
    big one beside them."""
    i = QIcon()
    folder = os.path.join(ASSETS, "icons")
    for n in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        i.addFile(os.path.join(folder, n))
    i.addFile(os.path.join(ASSETS, "icon.png"))
    return i


def _greyed(pm: QPixmap) -> QPixmap:
    """The icon without its colours, as dark as it is (Qt's own greying lightens it into a pale
    square, brighter on a dark panel than the coloured one)."""
    img = pm.toImage()
    grey = img.convertToFormat(QImage.Format.Format_Grayscale8).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(grey)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)     # its own outline
    p.drawImage(0, 0, img)
    p.end()
    out = QPixmap.fromImage(grey)
    out.setDevicePixelRatio(pm.devicePixelRatio())
    return out


def tray_icon(progress: float | None = None, active: bool = True) -> QIcon:
    """The tray's icon: in colour while someone listens to the music shared from here (`active`),
    grey while nobody does; with `progress` (0 to 1) a bar across its foot shows how far a read of
    the folders is."""
    base = icon()
    if not active:
        grey = QIcon()
        for size in (16, 20, 24, 32, 48, 64, 128, 256):
            grey.addPixmap(_greyed(base.pixmap(size, size)))
        base = grey
    if progress is None:
        return base
    pm = base.pixmap(64, 64)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(DEEP))
    p.drawRoundedRect(QRectF(2, 48, 60, 14), 5, 5)
    p.setBrush(QColor(ACCENT))
    p.drawRoundedRect(QRectF(4, 50, max(6.0, 56 * min(1.0, progress)), 10), 4, 4)
    p.end()
    return QIcon(pm)


def palette() -> QPalette:
    """The same colours for what the style sheet doesn't reach: Qt's own folder dialog where the
    desktop has none, and anything else drawn from the palette (white lists with bone text before)."""
    p = QPalette()
    for role, colour in ((QPalette.Window, NAVY), (QPalette.WindowText, BONE), (QPalette.Base, DEEP),
                         (QPalette.AlternateBase, PANEL), (QPalette.Text, BONE), (QPalette.Button, RAISED),
                         (QPalette.ButtonText, BONE), (QPalette.ToolTipBase, RAISED), (QPalette.ToolTipText, BONE),
                         (QPalette.PlaceholderText, FAINT), (QPalette.Highlight, ACCENT),
                         (QPalette.HighlightedText, ON_ACCENT), (QPalette.Link, ACCENT), (QPalette.Light, HIGH),
                         (QPalette.Midlight, RAISED), (QPalette.Mid, LINE_STRONG), (QPalette.Dark, DEEP),
                         (QPalette.Shadow, "#000000")):
        p.setColor(role, QColor(colour))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor(FAINT))
    return p


def ui_font(size: float = 10) -> QFont:
    f = QFont(UI)
    f.setPointSizeF(size)
    return f


STYLE = f"""
* {{ font-family: "{UI}"; color: {BONE}; }}
QWidget#root, QDialog {{ background: {NAVY}; }}
QToolTip {{ background: {RAISED}; color: {BONE}; border: 1px solid {LINE_STRONG}; padding: 4px 6px; }}

QLabel[role="kicker"] {{ font-family: "{MONO}"; font-size: 8pt; letter-spacing: 3px; color: {DIM}; }}
QLabel[role="title"] {{ font-size: 19pt; font-weight: 900; }}
QLabel[role="h3"] {{ font-size: 11pt; font-weight: 800; }}
QLabel[role="dim"] {{ color: {DIM}; }}
QLabel[role="faint"] {{ color: {FAINT}; font-size: 9pt; }}
QLabel[role="error"] {{ color: {BAD}; }}
QLabel[role="ok"] {{ color: {OK}; }}
QLabel[role="code"] {{ font-family: "{MONO}"; font-size: 12pt; font-weight: 700; color: {ACCENT};
                      background: {DEEP}; border: 1px solid {LINE_STRONG}; border-radius: 6px; padding: 6px 10px; }}

QFrame[role="panel"] {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 10px; }}
QFrame[role="hint"] {{ background: {PANEL}; border: 1px solid {LINE}; border-left: 3px solid {ACCENT}; border-radius: 6px; }}
QFrame[role="drop"] {{ border: 2px dashed {LINE_STRONG}; border-radius: 12px; background: {DEEP}; }}
QFrame[role="drop"][hover="true"] {{ border-color: {ACCENT}; }}
QFrame[role="row"] {{ background: transparent; border-radius: 6px; }}
QFrame[role="row"]:hover {{ background: {RAISED}; }}

QPushButton {{ background: {RAISED}; border: 1px solid {LINE_STRONG}; border-radius: 15px; padding: 6px 14px;
              font-weight: 700; }}
QPushButton:hover {{ background: {HIGH}; }}
QPushButton:disabled {{ color: {FAINT}; background: {PANEL}; }}
QPushButton[role="accent"] {{ background: {ACCENT}; color: {ON_ACCENT}; border-color: {ACCENT}; }}
QPushButton[role="accent"]:hover {{ background: #f5bb62; }}
QPushButton[role="ghost"] {{ background: transparent; border-color: transparent; color: {DIM}; }}
QPushButton[role="ghost"]:hover {{ color: {BONE}; background: {RAISED}; }}
QPushButton[role="mini"] {{ background: transparent; border: none; padding: 2px 6px; color: {DIM}; border-radius: 4px; }}
QPushButton[role="mini"]:hover {{ color: {BONE}; background: {RAISED}; }}

QLineEdit, QComboBox {{ background: {DEEP}; border: 1px solid {LINE_STRONG}; border-radius: 6px; padding: 5px 8px;
                       selection-background-color: {ACCENT}; selection-color: {ON_ACCENT}; }}
QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QLineEdit[mono="true"] {{ font-family: "{MONO}"; }}
QComboBox QAbstractItemView {{ background: {PANEL}; border: 1px solid {LINE_STRONG}; selection-background-color: {RAISED}; }}

QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; border: 1px solid {LINE_STRONG};
                                                background: {DEEP}; }}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QTabWidget::pane {{ border: none; border-top: 1px solid {LINE}; top: -1px; }}
QTabBar::tab {{ background: transparent; color: {DIM}; padding: 8px 14px; margin-right: 4px; font-weight: 700;
               border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {BONE}; border-bottom-color: {ACCENT}; }}
QTabBar::tab:hover {{ color: {BONE}; }}

QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {LINE_STRONG}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}

QTableWidget, QListWidget {{ background: {DEEP}; border: 1px solid {LINE}; border-radius: 6px; gridline-color: {LINE};
                             alternate-background-color: {PANEL}; }}
QHeaderView::section {{ background: {PANEL}; color: {DIM}; border: none; border-bottom: 1px solid {LINE};
                        padding: 4px 6px; font-family: "{MONO}"; font-size: 8pt; }}
QTableWidget::item:selected, QListWidget::item:selected {{ background: {RAISED}; color: {BONE}; }}

QFileDialog QTreeView, QFileDialog QListView {{ background: {DEEP}; border: 1px solid {LINE}; border-radius: 6px;
                                              selection-background-color: {RAISED}; selection-color: {BONE}; }}
QFileDialog QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 3px; }}
QFileDialog QToolButton:hover, QFileDialog QToolButton:checked {{ background: {RAISED}; border-color: {LINE_STRONG}; }}

QProgressBar {{ background: {DEEP}; border: 1px solid {LINE_STRONG}; border-radius: 5px; max-height: 10px;
                text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QMenu {{ background: {PANEL}; border: 1px solid {LINE_STRONG}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 14px; border-radius: 4px; }}
QMenu::item:selected {{ background: {RAISED}; }}
QMenu::item:disabled {{ color: {FAINT}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 8px; }}
"""

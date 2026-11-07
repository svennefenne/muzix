"""Muzix's look in Qt (DESIGN.md in the repository): midnight navy panels, bone text, a marigold
accent, Saira for words and JetBrains Mono for codes and labels (bundled under fonts/, OFL)."""

import os

from PySide6.QtGui import QFont, QFontDatabase, QIcon

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
    return QIcon(os.path.join(ASSETS, "icon.png"))


def tray_icon() -> QIcon:
    path = os.path.join(ASSETS, "tray.png")
    return QIcon(path) if os.path.exists(path) else icon()


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

QMenu {{ background: {PANEL}; border: 1px solid {LINE_STRONG}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 14px; border-radius: 4px; }}
QMenu::item:selected {{ background: {RAISED}; }}
QMenu::item:disabled {{ color: {FAINT}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 8px; }}
"""

"""Small pieces the windows share: labels in Muzix's styles, and work done off the window's thread."""

import threading

import httpx
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from .. import sharing


def label(text: str = "", role: str = "", wrap: bool = False, selectable: bool = False) -> QLabel:
    lb = QLabel(text)
    if role:
        lb.setProperty("role", role)
    lb.setWordWrap(wrap)
    if selectable:
        lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lb


class Elided(QLabel):
    """A path or name on one line, shortened in the middle to fit (the whole of it as the tooltip)."""

    def __init__(self, text: str = "", role: str = ""):
        super().__init__()
        if role:
            self.setProperty("role", role)
        self.setMinimumWidth(40)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.full = ""
        self.set(text)

    def set(self, text: str):
        self.full = text
        self.setToolTip(text)
        self._fit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def _fit(self):
        self.setText(self.fontMetrics().elidedText(self.full, Qt.ElideMiddle, max(40, self.width())))


def clear(layout):
    """Everything out of a layout (hidden at once, deleted when the window gets to it)."""
    while layout.count():
        item = layout.takeAt(0)
        if w := item.widget():
            w.hide()
            w.deleteLater()
        elif item.layout():
            clear(item.layout())


def heading(kicker: str, title: str) -> QWidget:
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(2)
    v.addWidget(label(kicker.upper(), "kicker"))
    v.addWidget(label(title, "title"))
    return w


def frame(role: str, layout="v", margins=(14, 12, 14, 12), spacing=8) -> tuple[QFrame, QVBoxLayout | QHBoxLayout]:
    f = QFrame()
    f.setProperty("role", role)
    lay = QVBoxLayout(f) if layout == "v" else QHBoxLayout(f)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return f, lay


def restyle(w: QWidget):
    """After a property the style depends on has changed."""
    w.style().unpolish(w)
    w.style().polish(w)


class _Call(QObject):
    done = Signal(object)
    failed = Signal(str)


_running: set[_Call] = set()


def in_background(fn, on_done=None, on_fail=None):
    """fn() in a thread; on_done(result) or on_fail(message) back on the window's thread."""
    call = _Call()
    _running.add(call)
    if on_done:
        call.done.connect(on_done)
    if on_fail:
        call.failed.connect(on_fail)
    call.done.connect(lambda _: _running.discard(call))
    call.failed.connect(lambda _: _running.discard(call))

    def run():
        try:
            result = fn()
        except Exception as e:      # shown to the user as it is
            call.failed.emit(str(e) or e.__class__.__name__)
        else:
            call.done.emit(result)

    threading.Thread(target=run, daemon=True).start()


_pictures: dict[str, bytes] = {}


def picture(url: str, size: int, on_done):
    """A picture from the web, scaled to `size`, given to on_done(QPixmap)."""
    def fetch():
        if url not in _pictures:
            with httpx.Client(headers={"User-Agent": sharing.UA}, timeout=20, follow_redirects=True) as c:
                r = c.get(url)
                r.raise_for_status()
                _pictures[url] = r.content
        return _pictures[url]

    def show(data):
        pm = QPixmap()
        if pm.loadFromData(data):
            on_done(pm.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))

    in_background(fetch, show, lambda _: None)


def cover_label(size: int) -> QLabel:
    lb = QLabel()
    lb.setFixedSize(size, size)
    lb.setAlignment(Qt.AlignCenter)
    lb.setStyleSheet(f"background: #060a15; border: 1px solid #29344d; border-radius: 6px; color: #87847f;")
    lb.setText("♪")
    return lb


def set_cover(lb: QLabel, pm: QPixmap):
    s = lb.width()
    lb.setPixmap(pm.scaled(s, s, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation).copy(0, 0, s, s))

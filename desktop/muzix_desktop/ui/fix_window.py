"""Fix Metadata & Artwork: a small window on top of the others. Albums dropped on it each get a
card: the sources' suggestions (fixer.search), the one picked with its songs paired to the files
and a cover to choose, then Apply, and Undo after."""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLineEdit, QPushButton, QScrollArea, QSizePolicy,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QAbstractItemView, QHeaderView)

from .. import config, fixer
from . import theme
from .widgets import Elided, alive, clear, cover_label, frame, heading, in_background, label, picture, restyle, set_cover

THUMB = 46


def _fmt_len(seconds: float) -> str:
    seconds = int(round(seconds or 0))
    return f"{seconds // 60}:{seconds % 60:02d}" if seconds else ""


def _button(text: str, role: str = "", tip: str = "") -> QPushButton:
    b = QPushButton(text)
    if role:
        b.setProperty("role", role)
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


class Suggestion(QFrame):
    """One source's album, to pick."""
    picked = Signal(dict)

    def __init__(self, r: dict):
        super().__init__()
        self.r = r
        self.setProperty("role", "row")
        self.setCursor(Qt.PointingHandCursor)
        h = QHBoxLayout(self)
        h.setContentsMargins(6, 5, 6, 5)
        h.setSpacing(10)
        self.cover = cover_label(THUMB)
        h.addWidget(self.cover)
        v = QVBoxLayout()
        v.setSpacing(0)
        title = label(r.get("title") or "?")
        title.setStyleSheet("font-weight: 700;")
        v.addWidget(title)
        bits = [r.get("artist"), str(r["year"]) if r.get("year") else "",
                f"{r['tracks']} songs" if r.get("tracks") else "", r.get("format") or "", r.get("country") or ""]
        v.addWidget(label(" · ".join(b for b in bits if b), "dim"))
        h.addLayout(v, 1)
        src = label(r["source"].upper(), "kicker")
        h.addWidget(src, 0, Qt.AlignTop)
        if r.get("cover"):
            picture(r["cover"], THUMB * 2, lambda pm: set_cover(self.cover, pm))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.picked.emit(self.r)


class AlbumCard(QFrame):
    """One dropped album, from searching to fixed."""
    removed = Signal(object)
    fixed = Signal(object)          # fixer.Done: the app reads the shared folders again
    open_settings = Signal()

    def __init__(self, album: fixer.Album):
        super().__init__()
        self.album = album
        self.setProperty("role", "panel")
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(12, 12, 12, 12)
        self.v.setSpacing(10)
        self.done: fixer.Done | None = None
        self.chosen: dict | None = None
        self.cover_bytes: bytes | None = None
        self.cover_url: str | None = None

        head = QHBoxLayout()
        head.setSpacing(10)
        self.thumb = cover_label(54)
        self._own_cover()
        head.addWidget(self.thumb)
        t = QVBoxLayout()
        t.setSpacing(0)
        self.title = label("", "h3", wrap=True)
        t.addWidget(self.title)
        self.sub = label("", "faint")
        t.addWidget(self.sub)
        self.where = Elided("", "faint")
        t.addWidget(self.where)
        head.addLayout(t, 1)
        x = _button("✕", "mini", "Remove from the list (nothing is changed)")
        x.clicked.connect(lambda: self.removed.emit(self))
        head.addWidget(x, 0, Qt.AlignTop)
        self.v.addLayout(head)
        self._describe()

        self.body = QWidget()
        self.body_l = QVBoxLayout(self.body)
        self.body_l.setContentsMargins(0, 0, 0, 0)
        self.body_l.setSpacing(6)
        self.v.addWidget(self.body)
        self.search(self.album.artist, self.album.title)

    # ------------------------------------------------------------ what it shows

    def _describe(self):
        a = self.album
        self.title.setText(f"{a.title} — {a.artist or 'unknown artist'}")
        n = len(a.songs)
        self.sub.setText(f"{n} {'song' if n == 1 else 'songs'}{f' · {a.year}' if a.year else ''}")
        self.where.set(a.folder)

    def _own_cover(self):
        from ..shared import scanner
        path = scanner.find_cover(self.album.folder)
        pm = QPixmap()
        if path and pm.load(path):
            set_cover(self.thumb, pm)

    def _clear(self):
        clear(self.body_l)

    def _query_row(self, artist: str, title: str):
        row = QHBoxLayout()
        a, t = QLineEdit(artist), QLineEdit(title)
        a.setPlaceholderText("Artist")
        t.setPlaceholderText("Album")
        go = _button("Search")
        for w in (a, t):
            w.returnPressed.connect(lambda: self.search(a.text(), t.text()))
        go.clicked.connect(lambda: self.search(a.text(), t.text()))
        row.addWidget(a, 1)
        row.addWidget(t, 1)
        row.addWidget(go)
        self.body_l.addLayout(row)

    def search(self, artist: str, title: str):
        self._clear()
        self._query_row(artist, title)
        wait = label("Searching " + ", ".join(sorted(config.load().enabled_sources() & fixer.ALBUM_SOURCES)) + "…", "dim")
        self.body_l.addWidget(wait)
        in_background(lambda: fixer.search(artist, title), lambda got: self._suggestions(artist, title, got),
                      lambda e: self._error(f"Couldn't search: {e}", lambda: self.search(artist, title)))

    def _suggestions(self, artist: str, title: str, got: dict):
        self._clear()
        self._query_row(artist, title)
        results = got.get("results") or []
        if not results:
            self.body_l.addWidget(label("No suggestions. Try other words, or switch on more sources in Settings.", "dim",
                                        wrap=True))
        for r in results[:12]:
            s = Suggestion(r)
            s.picked.connect(self.pick)
            self.body_l.addWidget(s)
        errors = got.get("errors") or {}
        if errors:
            self.body_l.addWidget(label("Not answering: " + "; ".join(f"{k} {v}" for k, v in errors.items()), "faint",
                                        wrap=True))

    def _error(self, text: str, again=None):
        self._clear()
        self.body_l.addWidget(label(text, "error", wrap=True))
        if again:
            b = _button("Try again")
            b.clicked.connect(again)
            self.body_l.addWidget(b, 0, Qt.AlignLeft)

    # ------------------------------------------------------------ the one picked

    def pick(self, r: dict):
        self._clear()
        self.body_l.addWidget(label(f"Getting the album from {r['source']}…", "dim"))
        in_background(lambda: fixer.details(r["source"], r["id"]), lambda d: self.review(r, d),
                      lambda e: self._error(e, lambda: self.pick(r)))

    def review(self, r: dict, d: dict):
        self.chosen = {**d, "source": r["source"]}
        self.pairs = fixer.pair(self.album.songs, d.get("tracks") or [])
        self.cover_url = d.get("cover") or r.get("cover")
        self.cover_bytes = None
        self._clear()

        top = QHBoxLayout()
        top.setSpacing(12)
        self.new_cover = cover_label(96)
        if self.cover_url:
            picture(self.cover_url, 192, lambda pm: set_cover(self.new_cover, pm))
        else:
            self.new_cover.setText("no cover")
        top.addWidget(self.new_cover)
        info = QVBoxLayout()
        info.setSpacing(2)
        t = label(d.get("title") or "?", "h3", wrap=True)
        info.addWidget(t)
        info.addWidget(label(" · ".join(x for x in (d.get("artist"), str(d["year"]) if d.get("year") else "",
                                                     d.get("genre")) if x), "dim", wrap=True))
        info.addWidget(label(f"from {r['source']}", "faint"))
        covers = _button("Other covers…", "ghost")
        covers.clicked.connect(lambda: self._covers(d))
        info.addWidget(covers, 0, Qt.AlignLeft)
        info.addStretch(1)
        top.addLayout(info, 1)
        self.body_l.addLayout(top)

        table = QTableWidget(len(self.pairs), 2)
        table.setHorizontalHeaderLabels(["NOW", "BECOMES"])
        table.verticalHeader().hide()
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        unmatched = 0
        for i, (song, theirs) in enumerate(self.pairs):
            now = QTableWidgetItem(f"{os.path.basename(song.path)}  {_fmt_len(song.duration)}")
            now.setToolTip(song.path)
            if theirs:
                becomes = QTableWidgetItem(f"{theirs.get('no') or ''}. {theirs.get('title')}  {_fmt_len(theirs.get('length'))}")
            else:
                unmatched += 1
                becomes = QTableWidgetItem("— keeps its title (no song like it)")
                becomes.setForeground(Qt.gray)
            table.setItem(i, 0, now)
            table.setItem(i, 1, becomes)
        table.setFixedHeight(min(30 + 26 * len(self.pairs), 260))
        self.body_l.addWidget(table)
        if unmatched:
            self.body_l.addWidget(label(f"{unmatched} of the songs aren't on this release; they get the album's "
                                        "name, artist and year only.", "faint", wrap=True))

        self.body_l.addWidget(label(self._what_happens(), "faint", wrap=True))
        row = QHBoxLayout()
        apply = _button("Apply", "accent")
        apply.clicked.connect(self.apply)
        back = _button("Back to suggestions", "ghost")
        back.clicked.connect(lambda: self.search(self.album.artist, self.album.title))
        row.addWidget(apply)
        row.addWidget(back)
        row.addStretch(1)
        self.body_l.addLayout(row)

    def _what_happens(self) -> str:
        cfg = config.load()
        cover = " The cover is saved as cover.jpg" + (" and put into each song." if cfg.embed_cover else ".")
        if cfg.organize == "rename":
            where = "The songs and the album folder are then renamed where they are." if self.album.whole_folder \
                else "The songs are then renamed (the folder has other music too, so it keeps its name)."
        elif cfg.organize == "library" and cfg.library and self.album.whole_folder:
            where = f"The album is then filed into {cfg.library} (Genre / Artist / Artist - Year - Album)."
        elif cfg.organize == "library":
            where = "The songs are then renamed where they are (" + \
                    ("set the library folder in Settings to file albums there)." if not cfg.library else
                     "the folder has other music too, so it stays where it is).")
        else:
            where = "No file or folder is renamed."
        return "Apply writes these tags into the songs." + (cover if self.cover_url else "") + " " + where

    def _covers(self, d: dict):
        grid_box, grid_l = frame("panel", margins=(8, 8, 8, 8))
        grid_box.setObjectName("covers")
        old = self.findChild(QFrame, "covers")
        if old:
            old.deleteLater()
        grid_l.addWidget(label("Looking for covers…", "dim"))
        self.body_l.insertWidget(1, grid_box)

        def show(got):
            clear(grid_l)
            found = got.get("results") or []
            if not found:
                grid_l.addWidget(label("No other covers found.", "dim"))
                return
            grid = QGridLayout()
            grid.setSpacing(6)
            for i, c in enumerate(found[:16]):
                b = QPushButton()
                b.setFixedSize(72, 72)
                b.setToolTip(f"{c.get('source')}: {c.get('title') or ''}")
                b.setCursor(Qt.PointingHandCursor)
                b.setStyleSheet("padding: 0; border-radius: 4px;")
                picture(c["thumb"], 72, lambda pm, b=b: alive(b) and (b.setIcon(QIcon(pm)), b.setIconSize(b.size())))
                b.clicked.connect(lambda _=False, url=c["url"]: self._use_cover(url, grid_box))
                grid.addWidget(b, i // 5, i % 5)
            holder = QWidget()
            holder.setLayout(grid)
            grid_l.addWidget(holder)

        in_background(lambda: fixer.other_covers(d.get("artist") or self.album.artist, d.get("title") or self.album.title),
                      show, lambda e: grid_l.addWidget(label(f"Couldn't look: {e}", "error")))

    def _use_cover(self, url: str, box: QFrame):
        self.cover_url = url
        picture(url, 192, lambda pm: set_cover(self.new_cover, pm))
        box.deleteLater()

    # ------------------------------------------------------------ fixing and undoing

    def apply(self):
        self._clear()
        self.body_l.addWidget(label("Writing tags…", "dim"))
        url, chosen, pairs = self.cover_url, self.chosen, self.pairs

        def work():
            cover = fixer.fetch_cover(url) if url else None
            return fixer.apply(self.album, chosen, pairs, cover)

        in_background(work, self._fixed, lambda e: self._error(e, lambda: self.review({"source": chosen["source"],
                                                                                        "cover": url}, chosen)))

    def _fixed(self, done: fixer.Done):
        self.done = done
        self.fixed.emit(done)
        self._describe()
        self._own_cover()
        self._clear()
        msg = label("Fixed." + (f" Now in {done.target}" if done.target != done.folder else ""), "ok", wrap=True)
        self.body_l.addWidget(msg)
        if done.skipped:
            self.body_l.addWidget(label("These songs' tags can't be written: " + ", ".join(done.skipped), "faint",
                                        wrap=True))
        row = QHBoxLayout()
        undo = _button("Undo")
        undo.clicked.connect(self.undo)
        row.addWidget(undo)
        row.addStretch(1)
        self.body_l.addLayout(row)

    def undo(self):
        done = self.done
        self._clear()
        self.body_l.addWidget(label("Putting it back…", "dim"))

        def work():
            fixer.undo(done)
            return fixer.albums_from([done.folder])

        def back(albums):
            self.done = None
            self.fixed.emit(done)
            if albums:
                self.album = albums[0]
            self._describe()
            self._own_cover()
            self._clear()
            self.body_l.addWidget(label("Put back as it was.", "dim"))
            again = _button("Fix again")
            again.clicked.connect(lambda: self.search(self.album.artist, self.album.title))
            self.body_l.addWidget(again, 0, Qt.AlignLeft)

        in_background(work, back, lambda e: self._error(f"Couldn't put it all back: {e}"))


class DropZone(QFrame):
    dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setProperty("role", "drop")
        self.setAcceptDrops(True)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 26, 20, 26)
        v.setSpacing(4)
        big = label("Drop albums here", "h3")
        big.setAlignment(Qt.AlignCenter)
        v.addWidget(big)
        small = label("Album folders, or the songs of an album", "faint")
        small.setAlignment(Qt.AlignCenter)
        v.addWidget(small)

    def _hover(self, on: bool):
        self.setProperty("hover", "true" if on else "false")
        restyle(self)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._hover(True)

    def dragLeaveEvent(self, e):
        self._hover(False)

    def dropEvent(self, e):
        self._hover(False)
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.dropped.emit(paths)


class FixWindow(QWidget):
    open_settings = Signal()
    fixed = Signal(object)

    def __init__(self):
        super().__init__(None, Qt.Window | Qt.WindowStaysOnTopHint)
        self.setObjectName("root")
        self.setWindowTitle("Fix Metadata & Artwork")
        self.setWindowIcon(theme.icon())
        self.resize(500, 640)
        self.setAcceptDrops(True)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(12)
        v.addWidget(heading("Muzix · Fix metadata & artwork", "Fix your albums"))

        hint, hl = frame("hint", "h", margins=(12, 10, 12, 10))
        self.hint_text = label("", wrap=True)
        hl.addWidget(self.hint_text, 1)
        settings = _button("Settings")
        settings.clicked.connect(self.open_settings.emit)
        hl.addWidget(settings, 0, Qt.AlignVCenter)
        v.addWidget(hint)
        self.refresh_hint()

        self.zone = DropZone()
        self.zone.dropped.connect(self.add)
        v.addWidget(self.zone)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        self.cards = QVBoxLayout(inner)
        self.cards.setContentsMargins(0, 0, 4, 0)
        self.cards.setSpacing(10)
        self.cards.addStretch(1)
        self.scroll.setWidget(inner)
        self.scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        v.addWidget(self.scroll, 1)

    def refresh_hint(self):
        cfg = config.load()
        sources = sorted(cfg.enabled_sources() & fixer.ALBUM_SOURCES)
        mode = {"tags": "only tags and artwork are changed",
                "rename": "songs and album folders are renamed where they are",
                "library": f"albums are filed into {cfg.library or 'your library folder (not set yet)'}"}[cfg.organize]
        self.hint_text.setText(f"<b>Check Settings before you drop albums here.</b> Right now {mode}, and the "
                               f"suggestions come from {', '.join(sources) if sources else 'no source at all'}.")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.zone.dropEvent(e)

    def add(self, paths: list[str]):
        def show(albums):
            if not albums:
                return
            for a in albums:
                card = AlbumCard(a)
                card.removed.connect(self._remove)
                card.fixed.connect(self.fixed.emit)
                self.cards.insertWidget(self.cards.count() - 1, card)
            self.scroll.ensureWidgetVisible(card)

        in_background(lambda: fixer.albums_from(paths), show)

    def _remove(self, card: AlbumCard):
        card.setParent(None)
        card.deleteLater()

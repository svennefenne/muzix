"""Settings: the folders shared, the servers shared with (and this computer's code for their
admins), the sources Fix Metadata & Artwork looks in, and what it may do with the files. Every
change is saved as it's made."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLineEdit,
                               QProgressBar, QPushButton, QRadioButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget)

from .. import __version__, autostart, config, sharing
from ..shared import use_keys
from . import theme
from .widgets import Elided, clear, frame, heading, in_background, label

STATUS = {
    "connecting": ("Connecting…", "dim"),
    "waiting": ("Waiting for its admin to accept this computer", "dim"),
    "linked": ("Sharing", "ok"),
    "offline": ("Can't be reached right now", "error"),
    "refused": ("Doesn't accept this computer (any more): remove it, or ask its admin", "error"),
    "removed": ("Its admin removed this computer", "error"),
    "stopped": ("Sharing is stopped", "dim"),
}


def _button(text: str, role: str = "") -> QPushButton:
    b = QPushButton(text)
    if role:
        b.setProperty("role", role)
    b.setCursor(Qt.PointingHandCursor)
    return b


def _page(*widgets) -> QScrollArea:
    inner = QWidget()
    v = QVBoxLayout(inner)
    v.setContentsMargins(2, 14, 8, 8)
    v.setSpacing(12)
    for w in widgets:
        v.addWidget(w)
    v.addStretch(1)
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.setWidget(inner)
    return area


class SettingsDialog(QDialog):
    folders_changed = Signal()
    sharing_toggled = Signal(bool)
    server_added = Signal(str)
    server_removed = Signal(str)
    rescan = Signal()
    fix_settings_changed = Signal()

    def __init__(self, app):
        super().__init__(None)
        self.app = app
        self.cfg = config.load()
        self.setWindowTitle("Muzix Desktop · Settings")
        self.setWindowIcon(theme.icon())
        self.resize(640, 640)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 18, 22, 16)
        v.setSpacing(10)
        v.addWidget(heading("Muzix Desktop · Settings", "Settings"))
        self.tabs = QTabWidget()
        self.tabs.addTab(self._sharing_tab(), "Sharing")
        self.tabs.addTab(self._servers_tab(), "Servers")
        self.tabs.addTab(self._sources_tab(), "Metadata && artwork")
        self.tabs.addTab(self._files_tab(), "Files")
        v.addWidget(self.tabs, 1)
        foot = QHBoxLayout()
        foot.addWidget(label(f"Muzix Desktop {__version__}", "faint"))
        foot.addStretch(1)
        close = _button("Close")
        close.clicked.connect(self.close)
        foot.addWidget(close)
        v.addLayout(foot)

    # ------------------------------------------------------------ sharing

    def _sharing_tab(self) -> QWidget:
        on, onl = frame("panel")
        self.share_box = QCheckBox("Share my folders with my servers while Muzix Desktop runs")
        self.share_box.setChecked(self.cfg.sharing)
        self.share_box.toggled.connect(self.sharing_toggled.emit)
        onl.addWidget(self.share_box)
        onl.addWidget(label("Your music is listed on the servers under Servers while this computer is on, and hidden "
                            "while it's off. Nothing on this computer is changed by sharing.", "dim", wrap=True))
        start = QCheckBox("Start Muzix Desktop minimized when I log in")
        try:
            start.setChecked(autostart.enabled())
        except OSError:
            start.setEnabled(False)
        start.toggled.connect(self._autostart)
        onl.addWidget(start)

        box, bl = frame("panel")
        bl.addWidget(label("Your music folders", "h3"))
        bl.addWidget(label("This computer's library in the Muzix window (Muzix library… → This computer). Those "
                           "marked Share are also shared with your servers: everything playable in them and their "
                           "subfolders. Mark folders of game music and tracker modules as VGM (they're for sharing: "
                           "game music needs a server to play).", "dim", wrap=True))
        self.folder_rows = QVBoxLayout()
        self.folder_rows.setSpacing(6)
        bl.addLayout(self.folder_rows)
        self._fill_folders()
        row = QHBoxLayout()
        add = _button("+ Add folder")
        add.clicked.connect(self._add_folder)
        row.addWidget(add)
        row.addStretch(1)
        self.catalog_text = label("", "faint")
        row.addWidget(self.catalog_text)
        self.reading_bar = QProgressBar()
        self.reading_bar.hide()
        again = _button("Read again", "ghost")
        again.setToolTip("Read the shared folders again now (it's done every few minutes too)")
        again.clicked.connect(self.rescan.emit)
        row.addWidget(again)
        bl.addLayout(row)
        bl.addWidget(self.reading_bar)
        self.show_catalog(self.app.reading if self.app.scanning else None)

        name, nl = frame("panel")
        nl.addWidget(label("This computer's name", "h3"))
        nl.addWidget(label("What the servers call it: their admins see it when you ask to share, and on the "
                           "Library Network page. Takes effect for servers added from now on.", "dim", wrap=True))
        edit = QLineEdit(self.cfg.name)
        edit.editingFinished.connect(lambda: self._set("name", edit.text().strip() or self.cfg.name))
        nl.addWidget(edit)
        return _page(on, box, name)

    def show_catalog(self, reading: tuple[int, int] | None = None):
        c = self.app.catalog.counts()
        n = lambda k, one, many: f"{c[k]:,} {one if c[k] == 1 else many}".replace(",", " ")
        text = f"{n('tracks', 'song', 'songs')} in {n('albums', 'album', 'albums')}"
        if reading and reading[1]:
            text += f" · reading {reading[0]:,} of {reading[1]:,} new".replace(",", " ")
        elif reading:
            text += " · looking through the folders…"
        self.catalog_text.setText(text)
        # a bar while the folders are read: moving to and fro until it knows how many songs are new
        self.reading_bar.setVisible(reading is not None)
        if reading:
            self.reading_bar.setRange(0, reading[1])
            self.reading_bar.setValue(reading[0])

    def _fill_folders(self):
        clear(self.folder_rows)
        if not self.cfg.folders:
            empty = QHBoxLayout()
            empty.addWidget(label("No folders yet.", "faint"))
            self.folder_rows.addLayout(empty)
        for f in self.cfg.folders:
            row = QHBoxLayout()
            row.addWidget(Elided(f.path), 1)
            kind = QComboBox()
            kind.addItems(["Music", "VGM"])
            kind.setCurrentIndex(1 if f.kind == "vgm" else 0)
            kind.currentIndexChanged.connect(lambda i, f=f: self._set_kind(f, "vgm" if i else "music"))
            row.addWidget(kind)
            share = QCheckBox("Share")
            share.setToolTip("Shared with your servers too")
            share.setChecked(f.share)
            share.toggled.connect(lambda on, f=f: self._set_share(f, on))
            row.addWidget(share)
            rm = _button("Remove", "ghost")
            rm.clicked.connect(lambda _=False, f=f: self._remove_folder(f))
            row.addWidget(rm)
            self.folder_rows.addLayout(row)

    def _add_folder(self):
        path = QFileDialog.getExistingDirectory(self, "A music folder")
        if not path or any(f.path == path for f in self.cfg.folders):
            return
        with config._lock:
            self.cfg.folders.append(config.Folder(path=path))
            config.save()
        self._fill_folders()
        self.folders_changed.emit()

    def _remove_folder(self, f: config.Folder):
        with config._lock:
            self.cfg.folders = [x for x in self.cfg.folders if x.path != f.path]
            config.save()
        self._fill_folders()
        self.folders_changed.emit()

    def _set_share(self, f: config.Folder, on: bool):
        with config._lock:
            f.share = on
            config.save()
        self.folders_changed.emit()

    def _set_kind(self, f: config.Folder, kind: str):
        with config._lock:
            f.kind = kind
            config.save()
        self.folders_changed.emit()

    def _autostart(self, on: bool):
        try:
            autostart.set_enabled(on)
        except OSError as e:
            self.app.notify("Couldn't change it", str(e))

    # ------------------------------------------------------------ servers

    def _servers_tab(self) -> QWidget:
        code, cl = frame("panel")
        cl.addWidget(label("This computer's sharing code", "h3"))
        cl.addWidget(label("When you add a server, give this code to its admin. They enter it on the server under "
                           "Admin → Library Network to accept this computer; then your music is shared there.",
                           "dim", wrap=True))
        row = QHBoxLayout()
        row.addWidget(label(self.cfg.code, "code", selectable=True))
        copy = _button("Copy")
        copy.clicked.connect(lambda: (QGuiApplication.clipboard().setText(self.cfg.code), copy.setText("Copied")))
        row.addWidget(copy)
        row.addStretch(1)
        cl.addLayout(row)

        box, bl = frame("panel")
        head = QHBoxLayout()
        head.addWidget(label("Servers", "h3"))
        head.addStretch(1)
        self.add_button = _button("+ Add", "accent")
        self.add_button.clicked.connect(self._show_add)
        head.addWidget(self.add_button)
        bl.addLayout(head)

        self.add_form, al = frame("hint")
        al.addWidget(label("The server's address and its sharing code: its admin finds the code under "
                           "Admin → Library Network.", "dim", wrap=True))
        self.address = QLineEdit()
        self.address.setPlaceholderText("https://muzix.example.com")
        self.server_code = QLineEdit()
        self.server_code.setPlaceholderText("XXXXX-XXXXX-XXXXX-XXXXX")
        self.server_code.setProperty("mono", "true")
        al.addWidget(self.address)
        al.addWidget(self.server_code)
        arow = QHBoxLayout()
        self.link_button = _button("Add server", "accent")
        self.link_button.clicked.connect(self._link)
        cancel = _button("Cancel", "ghost")
        cancel.clicked.connect(lambda: self.add_form.hide())
        arow.addWidget(self.link_button)
        arow.addWidget(cancel)
        arow.addStretch(1)
        al.addLayout(arow)
        self.link_error = label("", "error", wrap=True)
        al.addWidget(self.link_error)
        self.add_form.hide()
        bl.addWidget(self.add_form)

        self.server_rows = QVBoxLayout()
        self.server_rows.setSpacing(10)
        bl.addLayout(self.server_rows)
        self.show_servers()
        return _page(code, box)

    def _show_add(self):
        self.link_error.setText("")
        self.add_form.show()
        self.address.setFocus()

    def _link(self):
        address, code = self.address.text(), self.server_code.text()
        self.link_button.setEnabled(False)
        self.link_error.setText("")

        def ok(server: config.Server):
            self.link_button.setEnabled(True)
            self.address.clear()
            self.server_code.clear()
            self.add_form.hide()
            self.server_added.emit(server.server_id)
            self.show_servers()

        def failed(why: str):
            self.link_button.setEnabled(True)
            self.link_error.setText(why)

        in_background(lambda: sharing.link(address, code), ok, failed)

    def show_servers(self):
        clear(self.server_rows)
        if not self.cfg.servers:
            self.server_rows.addWidget(label("No servers yet. Add the server you listen on with + Add.", "faint",
                                             wrap=True))
        for s in self.cfg.servers:
            row, rl = frame("row", "h", margins=(4, 4, 4, 4))
            info = QVBoxLayout()
            info.setSpacing(0)
            name = label(s.name, "h3")
            info.addWidget(name)
            info.addWidget(Elided(s.address, "faint"))
            live = self.app.sharing.status.get(s.server_id)
            status = "removed" if s.state == "removed" else "stopped" if not self.cfg.sharing \
                else live if live in ("offline", "refused", "connecting") else s.state
            text, role = STATUS.get(status, (status, "dim"))
            info.addWidget(label(text, role, wrap=True))
            # its admin's watch folder on this computer (sharing.py): albums put there go into its library
            watch = QCheckBox("May pick a folder here to watch for new music")
            watch.setToolTip("Its admin sees this computer's folder names to pick one, and then reads and moves files "
                             "only in that folder: albums put there are filed into the server's library, and the files "
                             "here go to its _Done folder. While Muzix Desktop runs and shares.")
            watch.setChecked(s.watch)
            watch.toggled.connect(lambda on, sid=s.server_id: self._set_watch(sid, on))
            info.addSpacing(4)
            info.addWidget(watch)
            if s.watch and s.watch_folder:
                info.addWidget(Elided(f"Watches {s.watch_folder}", "faint"))
            rl.addLayout(info, 1)
            rm = _button("Remove", "ghost")
            rm.clicked.connect(lambda _=False, s=s: self._unlink(s))
            rl.addWidget(rm, 0, Qt.AlignTop)
            self.server_rows.addWidget(row)

    def _set_watch(self, sid: str, on: bool):
        """Whether the server's admin may pick a watch folder here; taking it back forgets the folder."""
        with config._lock:
            server = self.cfg.server(sid)
            if server is None:
                return
            server.watch = on
            if not on:
                server.watch_folder = ""
            config.save()
        self.show_servers()

    def _unlink(self, s: config.Server):
        def done(_):
            self.server_removed.emit(s.server_id)
            self.show_servers()
        in_background(lambda: sharing.unlink(s), done, lambda why: self.app.notify("Couldn't remove it", why))

    # ------------------------------------------------------------ sources

    def _sources_tab(self) -> QWidget:
        box, bl = frame("panel")
        bl.addWidget(label("Where Fix Metadata & Artwork looks", "h3"))
        bl.addWidget(label("The same sources as Edit metadata on a Muzix server. Each album shows what they suggest, "
                           "and you pick.", "dim", wrap=True))
        for key, name, about in config.SOURCES:
            check = QCheckBox(name)
            check.setChecked(self.cfg.sources.get(key, False))
            check.toggled.connect(lambda on, key=key: self._set_source(key, on))
            bl.addSpacing(4)
            bl.addWidget(check)
            under = QVBoxLayout()
            under.setContentsMargins(26, 0, 0, 0)
            under.setSpacing(4)
            under.addWidget(label(about, "faint", wrap=True))
            if key in config.KEYS:
                setting, what = config.KEYS[key]
                edit = QLineEdit(self.cfg.keys.get(setting, ""))
                edit.setPlaceholderText(what)
                edit.setEchoMode(QLineEdit.Password)
                edit.setProperty("mono", "true")
                edit.editingFinished.connect(lambda edit=edit, setting=setting: self._set_key(setting, edit.text()))
                under.addWidget(edit)
            bl.addLayout(under)
        return _page(box)

    def _set_source(self, key: str, on: bool):
        with config._lock:
            self.cfg.sources[key] = on
            config.save()
        self.fix_settings_changed.emit()

    def _set_key(self, setting: str, value: str):
        with config._lock:
            self.cfg.keys[setting] = value.strip()
            config.save()
        use_keys(self.cfg.keys)
        self.fix_settings_changed.emit()

    # ------------------------------------------------------------ files

    def _files_tab(self) -> QWidget:
        box, bl = frame("panel")
        bl.addWidget(label("What Fix Metadata & Artwork may do with the files", "h3"))
        group = QButtonGroup(self)
        for key, text in config.ORGANIZE.items():
            r = QRadioButton(text)
            r.setChecked(self.cfg.organize == key)
            r.toggled.connect(lambda on, key=key: on and self._set_organize(key))
            group.addButton(r)
            bl.addWidget(r)
        lib = QHBoxLayout()
        lib.setContentsMargins(26, 0, 0, 0)
        self.library = label(self.cfg.library or "No library folder chosen", "dim" if self.cfg.library else "faint")
        lib.addWidget(self.library, 1)
        choose = _button("Choose…")
        choose.clicked.connect(self._choose_library)
        lib.addWidget(choose)
        bl.addLayout(lib)
        bl.addWidget(label("Songs are named “1. Artist - Album - Title (Year)”, as on the server. Whatever is done "
                           "can be undone from the album's card.", "faint", wrap=True))

        cover, cvl = frame("panel")
        cvl.addWidget(label("Covers", "h3"))
        embed = QCheckBox("Also put the cover into each song, not only cover.jpg beside them")
        embed.setChecked(self.cfg.embed_cover)
        embed.toggled.connect(lambda on: self._set("embed_cover", on))
        cvl.addWidget(embed)
        return _page(box, cover)

    def _set_organize(self, key: str):
        self._set("organize", key)
        if key == "library" and not self.cfg.library:
            self._choose_library()

    def _choose_library(self):
        path = QFileDialog.getExistingDirectory(self, "Your library folder")
        if path:
            self._set("library", path)
            self.library.setText(path)
            self.library.setProperty("role", "dim")

    def _set(self, key: str, value):
        with config._lock:
            setattr(self.cfg, key, value)
            config.save()
        self.fix_settings_changed.emit()

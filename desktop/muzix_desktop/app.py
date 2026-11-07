"""The tray app: an icon in the system tray whose menu opens Fix Metadata & Artwork, starts and
stops sharing, opens Settings and quits. The shared folders are read when it starts, when they
change in Settings and every few minutes; the servers fetch the catalog again when it changed."""

import logging
import os
import sys
import traceback

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import config
from .catalog import Catalog
from .sharing import Sharing
from .shared import use_keys
from .ui import theme
from .ui.widgets import in_background

log = logging.getLogger(__name__)

RESCAN_EVERY = 5 * 60 * 1000        # ms
SOCKET = "muzix-desktop-" + (os.environ.get("USER") or os.environ.get("USERNAME") or "user")


class _Bridge(QObject):
    """Status from the sharing thread, to the window's thread."""
    status = Signal(str, str)


class App:
    def __init__(self, qt: QApplication):
        self.qt = qt
        self.cfg = config.load()
        use_keys(self.cfg.keys)
        self.catalog = Catalog(os.path.join(config.DATA_DIR, "index.db"))
        self.bridge = _Bridge()
        self.bridge.status.connect(self._status)
        self.sharing = Sharing(self.catalog, lambda sid, st: self.bridge.status.emit(sid, st))
        self.scanning = False
        self.fix_window = None
        self.settings = None
        self.known_states = {s.server_id: s.state for s in self.cfg.servers}

        self.tray = QSystemTrayIcon(theme.tray_icon())
        self.tray.setToolTip("Muzix Desktop")
        self.menu = QMenu()
        self.fix_action = QAction("Fix Metadata && Artwork…")
        self.fix_action.triggered.connect(self.open_fix)
        self.status_action = QAction("")
        self.status_action.setEnabled(False)
        self.toggle_action = QAction("")
        self.toggle_action.triggered.connect(lambda: self.set_sharing(not self.cfg.sharing))
        self.settings_action = QAction("Settings…")
        self.settings_action.triggered.connect(self.open_settings)
        self.quit_action = QAction("Quit")
        self.quit_action.triggered.connect(self.quit)
        self.menu.addAction(self.fix_action)
        self.menu.addSeparator()
        self.menu.addAction(self.status_action)
        self.menu.addAction(self.toggle_action)
        self.menu.addAction(self.settings_action)
        self.menu.addSeparator()
        self.menu.addAction(self.quit_action)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._clicked)
        self.tray.show()
        self._menu_text()

        self.timer = QTimer()
        self.timer.timeout.connect(self.scan)
        self.timer.start(RESCAN_EVERY)
        self.scan()
        if self.cfg.sharing:
            self.sharing.start()
        if not self.cfg.folders or not self.cfg.servers:
            QTimer.singleShot(400, self.open_settings)      # the first start: what to share, and where

    # ------------------------------------------------------------ the menu

    def _clicked(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger and sys.platform != "darwin":
            self.open_fix()

    def _menu_text(self):
        c = self.catalog.counts()
        linked = sum(1 for s in self.cfg.servers if s.state == "linked")
        if not self.cfg.sharing:
            text = "Sharing is stopped"
        elif not self.cfg.folders:
            text = "No folders to share yet"
        elif not linked:
            text = "No server has accepted this computer yet"
        else:
            text = f"Sharing {c['tracks']:,} songs with {linked} {'server' if linked == 1 else 'servers'}".replace(",", " ")
        if self.scanning:
            text += " · reading folders…"
        self.status_action.setText(text)
        self.toggle_action.setText("Stop sharing" if self.cfg.sharing else "Start sharing")
        self.tray.setToolTip(f"Muzix Desktop\n{text}")

    def notify(self, title: str, text: str):
        self.tray.showMessage(title, text, theme.icon(), 6000)

    # ------------------------------------------------------------ sharing

    def set_sharing(self, on: bool):
        with config._lock:
            self.cfg.sharing = on
            config.save()
        if on:
            self.sharing.start()
        else:
            self.sharing.stop()
        self._menu_text()
        if self.settings:
            self.settings.share_box.blockSignals(True)
            self.settings.share_box.setChecked(on)
            self.settings.share_box.blockSignals(False)
            self.settings.show_servers()

    def _status(self, sid: str, status: str):
        s = self.cfg.server(sid)
        if s is not None:
            before = self.known_states.get(sid)
            if s.state == "linked" and before == "waiting":
                self.notify("Muzix Desktop", f"{s.name} accepted this computer: your music is shared there now.")
            if s.state == "removed" and before != "removed":
                self.notify("Muzix Desktop", f"{s.name} removed this computer from its Library Network.")
            self.known_states[sid] = s.state
        self._menu_text()
        if self.settings:
            self.settings.show_servers()

    def scan(self):
        if self.scanning:
            return
        self.scanning = True
        self._menu_text()
        folders = [(f.path, f.kind) for f in self.cfg.folders]

        def done(changed):
            self.scanning = False
            self._menu_text()
            if self.settings:
                self.settings.show_catalog()
            if changed and self.cfg.sharing:
                self.sharing.changed()

        def failed(why):
            self.scanning = False
            self._menu_text()
            log.warning("reading the folders failed: %s", why)

        in_background(lambda: self.catalog.scan(folders), done, failed)

    # ------------------------------------------------------------ windows

    def open_fix(self):
        if self.fix_window is None:
            from .ui.fix_window import FixWindow
            self.fix_window = FixWindow()
            self.fix_window.open_settings.connect(self.open_settings)
            self.fix_window.fixed.connect(self._fixed)
        self.fix_window.refresh_hint()
        self.fix_window.show()
        self.fix_window.raise_()
        self.fix_window.activateWindow()

    def _fixed(self, done):
        if done.moves:
            self.catalog.moved(done.moves)
        self.scan()

    def open_settings(self):
        if self.settings is None:
            from .ui.settings_dialog import SettingsDialog
            self.settings = SettingsDialog(self)
            self.settings.folders_changed.connect(self.scan)
            self.settings.rescan.connect(self.scan)
            self.settings.sharing_toggled.connect(self.set_sharing)
            self.settings.server_added.connect(self._server_added)
            self.settings.server_removed.connect(self._server_removed)
            self.settings.fix_settings_changed.connect(
                lambda: self.fix_window and self.fix_window.refresh_hint())
            self.settings.finished.connect(lambda _: self._settings_closed())
        self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()

    def _settings_closed(self):
        self.settings.deleteLater()
        self.settings = None

    def _server_added(self, sid: str):
        self.known_states[sid] = (self.cfg.server(sid) or config.Server("", sid, "", "")).state
        if self.cfg.sharing:
            self.sharing.follow(sid)
        self._menu_text()

    def _server_removed(self, sid: str):
        self.sharing.forget(sid)
        self.known_states.pop(sid, None)
        self._menu_text()

    def quit(self):
        self.timer.stop()
        self.sharing.stop()
        self.tray.hide()
        self.qt.quit()


def _already_running() -> bool:
    """Another Muzix Desktop of this user is running: it's asked to show Settings instead."""
    s = QLocalSocket()
    s.connectToServer(SOCKET)
    if s.waitForConnected(300):
        s.write(b"show")
        s.waitForBytesWritten(300)
        s.disconnectFromServer()
        return True
    return False


def check() -> int:
    """`--check [--report FILE]`: whether everything the app needs is there (the builds run it
    before they ship). What it found goes to FILE too: a windowed app has no console to print to."""
    report = sys.argv[sys.argv.index("--report") + 1] if "--report" in sys.argv[:-1] else None
    try:
        from . import fixer, sharing  # noqa: F401
        from .shared import formats, manage, tags, tagwrite  # noqa: F401
        assert manage.broad_genre("Doom Metal") == "Metal", "the genre rules aren't there"
        assert formats.is_audio("song.flac") and not formats.is_audio("notes.txt")
        qt = QApplication(sys.argv[:1])
        theme.load_fonts()
        from PySide6.QtGui import QFontDatabase
        assert "Saira" in QFontDatabase.families(), "the fonts aren't there"
        assert not theme.icon().isNull(), "the icon isn't there"
        qt.quit()
        text, code = "Muzix Desktop: OK", 0
    except BaseException:
        text, code = traceback.format_exc(), 1
    if sys.stdout:
        print(text)
    if report:
        with open(report, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    return code


def _logging():
    """To a file in the data folder (a windowed app has no console), and to the console when there is one."""
    os.makedirs(config.DATA_DIR, exist_ok=True)
    handlers = [logging.FileHandler(os.path.join(config.DATA_DIR, "muzix-desktop.log"), encoding="utf-8")]
    if sys.stderr:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", handlers=handlers)
    sys.excepthook = lambda *exc: logging.getLogger("muzix_desktop").error("crashed", exc_info=exc)


def main():
    if "--check" in sys.argv:
        return check()
    _logging()
    QApplication.setApplicationName("Muzix Desktop")
    QApplication.setOrganizationName("Muzix")
    qt = QApplication(sys.argv)
    qt.setQuitOnLastWindowClosed(False)
    if _already_running():
        return 0
    theme.load_fonts()
    qt.setStyleSheet(theme.STYLE)
    qt.setWindowIcon(theme.icon())
    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.warning("No system tray here: Settings stays open instead")
    app = App(qt)
    server = QLocalServer()
    QLocalServer.removeServer(SOCKET)
    server.listen(SOCKET)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), app.open_settings()))
    if not QSystemTrayIcon.isSystemTrayAvailable():
        app.open_settings()
    return qt.exec()

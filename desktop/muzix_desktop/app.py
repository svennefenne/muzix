"""The tray app: an icon in the system tray whose menu opens Fix Metadata & Artwork, starts and
stops sharing, opens Settings and quits. The shared folders are read when it starts, when they
change in Settings and every few minutes; the servers fetch the catalog again when it changed.

The icon is grey while nobody listens to the music shared from here, and in colour while someone
does (a server says so when one of its listeners plays a song from here); hovering over it says
what plays where and how much has been sent today. Started at login (--minimized) it opens no
window, and waits for the tray if the desktop isn't ready yet."""

import json
import logging
import os
import sys
import time
import traceback
from datetime import date

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import __version__, autostart, config
from .catalog import Catalog
from .sharing import Sharing
from .shared import use_keys
from .ui import theme
from .ui.widgets import in_background
from .updater import Updater, resumed

log = logging.getLogger(__name__)

RESCAN_EVERY = 5 * 60 * 1000        # ms
TICK = 3000                         # ms between looks at what plays and what's been sent
PLAYS_FOR_UNKNOWN = 5 * 60          # seconds a song of unknown length counts as playing
SOCKET = "muzix-desktop-" + (os.environ.get("USER") or os.environ.get("USERNAME") or "user")


class _Bridge(QObject):
    """Status from the sharing thread, a song played on a server, and how far a read of the folders
    is, to the window's thread."""
    status = Signal(str, str)
    progress = Signal(int, int)
    playing = Signal(str, int)


def fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


class Usage:
    """The bytes sent to the servers today (kept over a restart in usage.json)."""

    def __init__(self):
        self.path = os.path.join(config.DATA_DIR, "usage.json")
        try:
            with open(self.path, encoding="utf-8") as f:
                saved = json.load(f)
        except (OSError, ValueError):
            saved = {}
        self.day, self.sent = saved.get("day", ""), int(saved.get("sent") or 0)
        self.saved_at = self.sent

    def add(self, n: int):
        today = date.today().isoformat()
        if self.day != today:
            self.day, self.sent, self.saved_at = today, 0, -1
        self.sent += n
        if self.sent - self.saved_at >= 1024 ** 2 or self.saved_at < 0:
            self.save()

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"day": self.day, "sent": self.sent}, f)
            self.saved_at = self.sent
        except OSError:
            pass


class App:
    def __init__(self, qt: QApplication, minimized: bool = False):
        self.qt = qt
        self.cfg = config.load()
        use_keys(self.cfg.keys)
        self.catalog = Catalog(os.path.join(config.DATA_DIR, "index.db"))
        self.bridge = _Bridge()
        self.bridge.status.connect(self._status)
        self.bridge.progress.connect(self._progress)
        self.reading: tuple[int, int] | None = None     # (songs read, of) while the folders are read
        self.bridge.playing.connect(self._played)
        self.sharing = Sharing(self.catalog, lambda sid, st: self.bridge.status.emit(sid, st),
                               lambda sid, track: self.bridge.playing.emit(sid, track))
        self.plays: dict[tuple[str, int], float] = {}     # (server, song) → until when it counts as playing
        self.usage = Usage()
        self.counted = 0                # of sharing.sent, what's in usage already
        self.active = False
        self.scanning = False
        self.fix_window = None
        self.settings = None
        self.known_states = {s.server_id: s.state for s in self.cfg.servers}

        from .window import Window
        # after an update's restart: the page it was on and what played (updater.py)
        self.window = Window(self.cfg, resumed())
        self.window.folder_added.connect(self._folder_added)
        if not minimized:
            self.window.bring()

        self.tray = QSystemTrayIcon(theme.tray_icon(active=False))
        self.tray.setToolTip("Muzix Desktop")
        self.menu = QMenu()
        self.open_action = QAction("Open Muzix")
        self.open_action.triggered.connect(self.window.bring)
        self.server_action = QAction("Muzix library…")
        self.server_action.triggered.connect(lambda: (self.window.ask(), self.window.bring()))
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
        self.playing_action = QAction("")
        self.playing_action.setEnabled(False)
        self.playing_action.setVisible(False)
        self.menu.addAction(self.open_action)
        self.menu.addAction(self.fix_action)
        self.menu.addSeparator()
        self.menu.addAction(self.playing_action)
        self.menu.addAction(self.status_action)
        self.menu.addAction(self.toggle_action)
        self.menu.addAction(self.settings_action)
        self.menu.addAction(self.server_action)
        self.menu.addSeparator()
        self.menu.addAction(self.quit_action)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._clicked)
        self.tray.show()
        self._menu_text()
        if minimized and not QSystemTrayIcon.isSystemTrayAvailable():
            self._wait_for_tray()       # at login the desktop's tray may come a little after this app

        self.timer = QTimer()
        self.timer.timeout.connect(self.scan)
        self.timer.start(RESCAN_EVERY)
        self.ticker = QTimer()
        self.ticker.timeout.connect(self._tick)
        self.ticker.start(TICK)
        self.scan()
        if self.cfg.sharing:
            self.sharing.start()
        # Update in the account menu: the new version downloaded in the background, put in and started (updater.py)
        self.updater = Updater(lambda: self.window.isVisible() and not self.window.isMinimized(), self.window.handover,
                               self.quit, self.window.notify)
        self.window.updater = self.updater
        try:
            if autostart.enabled():
                autostart.set_enabled(True)     # the login entry kept up to date (--minimized, where the app is)
        except OSError:
            pass

    def _wait_for_tray(self, tries: int = 60):
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.hide()
            self.tray.show()
        elif tries:
            QTimer.singleShot(2000, lambda: self._wait_for_tray(tries - 1))

    # ------------------------------------------------------------ what plays, and what's sent

    def _played(self, sid: str, track: int):
        """A server says one of its listeners plays a song from here: it counts as playing for its length."""
        song = self.catalog.song(track)
        seconds = song[2] if song and song[2] else PLAYS_FOR_UNKNOWN
        self.plays[(sid, track)] = time.monotonic() + seconds + 20
        self._tick()

    def _tick(self):
        now = time.monotonic()
        self.plays = {k: until for k, until in self.plays.items() if until > now}
        sent = self.sharing.sent
        if sent > self.counted:
            self.usage.add(sent - self.counted)
            self.counted = sent
        active = bool(self.plays) or self.sharing.sending > 0
        if active != self.active:
            self.active = active
            self._icon()
        self._menu_text()

    def _now_playing(self) -> list[str]:
        """What plays on the servers now, the latest first: "Artist – Title on Server"."""
        out = []
        for (sid, track), _ in sorted(self.plays.items(), key=lambda kv: -kv[1]):
            song = self.catalog.song(track)
            server = self.cfg.server(sid)
            name = f"{song[0]} – {song[1]}" if song else "a song from here"
            out.append(f"{name} on {server.name if server else 'a server'}")
        return out

    def _icon(self):
        progress = None
        if self.scanning:
            done, of = self.reading or (0, 0)
            progress = done / of if of else 0
        self.tray.setIcon(theme.tray_icon(progress, active=self.active))

    # ------------------------------------------------------------ the menu

    def _clicked(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger and sys.platform != "darwin":
            self.window.bring()

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
            done, of = self.reading or (0, 0)
            text += f" · reading folders: {done:,} of {of:,} new songs ({done * 100 // of} %)".replace(",", " ") if of \
                else " · looking through the folders…"
        self.status_action.setText(text)
        self.toggle_action.setText("Stop sharing" if self.cfg.sharing else "Start sharing")
        playing = self._now_playing()
        self.playing_action.setVisible(bool(playing))
        if playing:
            self.playing_action.setText(f"Playing: {playing[0]}" + (f" (and {len(playing) - 1} more)" if len(playing) > 1 else ""))
        lines = ["Muzix Desktop"]
        lines += [f"♪ {p}" for p in playing[:4]] + ([f"and {len(playing) - 4} more"] if len(playing) > 4 else [])
        if not playing:
            lines.append("Nobody is listening to your music right now")
        lines.append(text)
        lines.append(f"Sent today: {fmt_bytes(self.usage.sent if self.usage.day == date.today().isoformat() else 0)}")
        self.tray.setToolTip("\n".join(lines))

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

    def _progress(self, done: int, of: int):
        self.reading = (done, of)
        self._menu_text()
        self._icon()
        if self.settings:
            self.settings.show_catalog(self.reading)

    def scan(self):
        if self.scanning:
            return
        self.scanning = True
        self._progress(0, 0)            # looking through the folders, before it knows how many are new
        folders = [(f.path, f.kind) for f in self.cfg.folders if f.share]

        def done(changed):
            self.scanning = False
            self.reading = None
            self._menu_text()
            self._icon()
            if self.settings:
                self.settings.show_catalog()
            if changed and self.cfg.sharing:
                self.sharing.changed()

        def failed(why):
            self.scanning = False
            self.reading = None
            self._menu_text()
            self._icon()
            if self.settings:
                self.settings.show_catalog()
            log.warning("reading the folders failed: %s", why)

        in_background(lambda: self.catalog.scan(folders, lambda d, n: self.bridge.progress.emit(d, n)), done, failed)

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

    def _folder_added(self):
        """A music folder added from the window: shared too (while sharing is on), and in Settings if it's open."""
        self.scan()
        if self.settings is not None:
            self.settings._fill_folders()

    def open_settings(self):
        if self.settings is None:
            from .ui.settings_dialog import SettingsDialog
            self.settings = SettingsDialog(self)
            self.settings.folders_changed.connect(self.scan)
            self.settings.folders_changed.connect(self.window.folders_changed)
            # Read again: this computer's library too (it reads its folders by itself every few hours)
            self.settings.rescan.connect(lambda: self.cfg.library == "local" and self.window.library.rescan())
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
        self.ticker.stop()
        self._tick()
        self.usage.save()
        self.sharing.stop()
        self.window.shutdown()
        self.tray.hide()
        self.qt.quit()


def _version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split(".") if x.isdigit())


def _already_running() -> bool:
    """Another Muzix Desktop of this user is running. An older one (an update was just started) makes way
    for this one; the same version, or a newer one, shows its window instead."""
    s = QLocalSocket()
    s.connectToServer(SOCKET)
    if not s.waitForConnected(300):
        return False
    s.write(f"hello {__version__}\n".encode())
    s.waitForBytesWritten(300)
    answer = bytes(s.readAll().data()) if s.waitForReadyRead(1500) else b""
    if answer.startswith(b"quit"):
        log.info("An older Muzix Desktop makes way for %s", __version__)
        s.waitForDisconnected(8000)
        time.sleep(0.5)         # its window's own server lets go of its port too
        return False
    if answer.startswith(b"show"):
        s.disconnectFromServer()
        return True
    # one from before 0.4.5 says nothing (and shows its window): it's older, so it's ended instead
    return not _end_older(s.fullServerName())


def _end_older(path: str) -> bool:
    """An older Muzix Desktop, which can't be asked to go, ended (on Linux: the program at the other end of
    its socket, if it's Muzix Desktop). Whether it went."""
    if not sys.platform.startswith("linux"):
        return False
    import signal
    import socket
    import struct
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(path)
            pid = struct.unpack("3i", s.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))[0]
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            if b"muzix" not in f.read().lower():
                return False
        log.info("Ending the older Muzix Desktop (pid %s) for %s", pid, __version__)
        os.kill(pid, signal.SIGTERM)
        for _ in range(80):
            if not os.path.exists(f"/proc/{pid}"):
                return True
            time.sleep(0.1)
    except OSError:
        pass
    return False


def _knocked(conn: QLocalSocket, app: "App"):
    """Muzix Desktop started again: a newer version takes over (this one goes), the same or an older one
    shows this window."""
    def read():
        said = bytes(conn.readAll().data()).decode(errors="ignore").strip()
        if said.startswith("hello ") and _version(said[6:]) > _version(__version__):
            log.info("Muzix Desktop %s is starting: %s makes way", said[6:], __version__)
            conn.write(b"quit\n")
            conn.waitForBytesWritten(300)
            app.quit()
            return
        conn.write(b"show\n")
        conn.flush()
        app.window.bring()
    conn.readyRead.connect(read)


def check() -> int:
    """`--check [--report FILE]`: whether everything the app needs is there (the builds run it
    before they ship). What it found goes to FILE too: a windowed app has no console to print to."""
    report = sys.argv[sys.argv.index("--report") + 1] if "--report" in sys.argv[:-1] else None
    try:
        from . import fixer, sharing  # noqa: F401
        from .shared import formats, manage, tags, tagwrite  # noqa: F401
        assert manage.broad_genre("Doom Metal") == "Metal", "the genre rules aren't there"
        assert formats.is_audio("song.flac") and not formats.is_audio("notes.txt")
        # the Muzix window: its web interface, its browser, its own server, its player and its speakers
        from PySide6 import QtWebChannel, QtWebEngineWidgets  # noqa: F401
        import pychromecast  # noqa: F401
        import uvicorn  # noqa: F401
        from . import player, relay
        assert relay.web_dir(), "the web interface isn't there"
        assert player.available(), "GStreamer's player (playbin3) isn't there"
        need = [("flacdec",), ("opusdec",), ("vorbisdec",), ("mpg123audiodec", "avdec_mp3"), ("avdec_aac", "faad", "fdkaacdec"),
                ("wavpackdec", "avdec_wavpack"), ("spectrum",), ("souphttpsrc", "curlhttpsrc")]
        missing = [n[0] for n in need if not any(player.Gst.ElementFactory.find(x) for x in n)]
        assert not missing, (f"GStreamer lacks {', '.join(missing)} (its packages: {player.gst_packages()}, plugins from "
                             f"{os.environ.get('GST_PLUGIN_SYSTEM_PATH_1_0') or os.environ.get('GST_PLUGIN_PATH')})")
        # Linux: streams through souphttpsrc, with the libsoup that comes along (muzix-desktop.spec), made here as
        # it loads libsoup only then: curlhttpsrc can't seek in a podcast and stops in long streams. (Windows'
        # GStreamer packages have no souphttpsrc that starts: curlhttpsrc there, for now)
        if sys.platform == "linux":
            try:
                made = player.Gst.ElementFactory.make("souphttpsrc")
            except Exception:       # newer PyGObject raises for an element that's missing
                made = None
            assert made is not None, "souphttpsrc doesn't start (its libsoup)"
        if sys.platform == "win32":
            from . import smtc
            assert smtc.MediaPlayer is not None, "Windows' media controls (pywinrt) aren't there"
        if sys.platform == "darwin":
            from . import nowplaying
            assert nowplaying.MP is not None, "macOS' Now Playing (pyobjc) isn't there"
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
    log.info("Muzix Desktop %s", __version__)
    if sys.platform.startswith("linux") and os.environ.get("QT_QPA_PLATFORMTHEME") not in ("gtk3", "xdgdesktopportal"):
        # the desktop's own folder picker through its portal (KDE's, GNOME's...): the desktop's Qt
        # plugins don't fit the Qt bundled here, so Qt would draw its own, and on systems without
        # the portal it still does
        os.environ["QT_QPA_PLATFORMTHEME"] = "xdgdesktopportal"
    from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401  (QtWebEngine wants to be there before the QApplication)
    QApplication.setApplicationName("Muzix Desktop")
    QApplication.setOrganizationName("Muzix")
    qt = QApplication(sys.argv)
    qt.setQuitOnLastWindowClosed(False)
    minimized = "--minimized" in sys.argv          # started at login: no window, only the tray
    if _already_running():
        return 0
    theme.load_fonts()
    qt.setPalette(theme.palette())
    qt.setStyleSheet(theme.STYLE)
    qt.setWindowIcon(theme.icon())
    app = App(qt, minimized=minimized)
    server = QLocalServer()
    QLocalServer.removeServer(SOCKET)
    server.listen(SOCKET)
    server.newConnection.connect(lambda: _knocked(server.nextPendingConnection(), app))
    if not minimized and not QSystemTrayIcon.isSystemTrayAvailable():
        log.warning("No system tray here: closing the window quits")
    return qt.exec()

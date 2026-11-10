"""The Muzix window: the web interface that comes with the app (relay.py serves it, and passes what's for
the server on), shown by QtWebEngine, as it looks in a browser, with the app's player behind it
(player.py): the page hands it the queue through `window.MuzixApp`, as in the Android app. The first
time, and from the tray's menu, it asks for the server's address. Closing it leaves Muzix in the tray,
playing on."""

import asyncio
import logging
import re
import sys
import threading

import httpx
from PySide6.QtCore import QFile, QObject, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QCursor, QDesktopServices
from PySide6.QtNetwork import QNetworkCookie, QNetworkInformation
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLineEdit, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget)

from . import config, player
from .library import Library
from .relay import SECRET_COOKIE, Relay, health, local, normalize
from .ui import theme
from .ui.widgets import in_background, label

log = logging.getLogger(__name__)


class _Page(QWebEnginePage):
    """Muzix's own pages stay in the window; links elsewhere open in the browser."""

    def __init__(self, profile, parent, origin: str):
        super().__init__(profile, parent)
        self.origin = origin

    def acceptNavigationRequest(self, url: QUrl, kind, main_frame: bool) -> bool:
        if url.scheme() in ("http", "https") and not url.toString().startswith(self.origin):
            QDesktopServices.openUrl(url)
            return False
        return True

    def createWindow(self, kind):
        # a link to a new tab or window: the browser
        page = QWebEnginePage(self.profile(), self)
        page.urlChanged.connect(lambda u: (QDesktopServices.openUrl(u), page.deleteLater()))
        return page


# `window.MuzixApp` as the Android app's web view has it (frontend/src/player/app.ts), over Qt's web channel;
# what's posted before the channel is up waits for it
BRIDGE = """
(() => {
  const listeners = [], waiting = [];
  let app = null;
  window.MuzixApp = {
    postMessage(s) { app ? app.postMessage(s) : waiting.push(s); },
    addEventListener(type, fn) { if (type === "message") listeners.push(fn); },
  };
  const start = () => {
    if (!(window.qt && qt.webChannelTransport)) return setTimeout(start, 20);
    new QWebChannel(qt.webChannelTransport, (ch) => {
      app = ch.objects.muzix;
      app.message.connect((s) => listeners.forEach((fn) => fn({ data: s })));
      waiting.splice(0).forEach((s) => app.postMessage(s));
    });
  };
  start();
})();
"""


class _Bridge(QObject):
    """The page's end of the player: messages both ways."""
    message = Signal(str)

    def __init__(self, handle):
        super().__init__()
        self.handle = handle

    @Slot(str)
    def postMessage(self, text: str):
        self.handle(text)


class Window(QMainWindow):
    library_up = Signal(bool)       # this computer's library answers (or didn't start)
    folder_added = Signal()         # a music folder added here, not in Settings (the page's "Add a music folder")

    def __init__(self, cfg: config.Config):
        super().__init__()
        self.cfg = cfg
        self.library = Library(cfg)
        self.library_up.connect(self._library_up)
        self.setWindowTitle("Muzix")
        self.resize(1280, 820)
        self.relay = Relay(cfg.listen_home, cfg.listen_away, cfg.window_port)
        # signed in to a server: what this computer kept with no server moves into the account (step 6)
        self.relay.signed_in = lambda session: threading.Thread(
            target=lambda: self.relay.address and self.library.move_to_account(self.relay.address, session), daemon=True).start()
        if cfg.window_port != self.relay.port:
            cfg.window_port = self.relay.port
            config.save()

        # the window's browser: its own cookies and storage, kept between runs
        self.profile = QWebEngineProfile("muzix", self)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        secret = QNetworkCookie(SECRET_COOKIE.encode(), self.relay.secret.encode())
        secret.setHttpOnly(True)
        secret.setPath("/")
        self.profile.cookieStore().setCookie(secret, QUrl(self.relay.origin))
        self.web = QWebEngineView()
        self.web.setPage(_Page(self.profile, self.web, self.relay.origin))
        self.web.page().setBackgroundColor(Qt.GlobalColor.black)

        # the player, and the page's way to it
        self.player = None
        if player.available():
            self.player = player.Player(self.relay.headers, lambda: self.isVisible() and not self.isMinimized(), self._for_speaker,
                                        library=lambda: self.cfg.library)
            self.bridge = _Bridge(self.player.handle)
            self.player.sent.connect(self.bridge.message)
            self.player.command.connect(self._command)
            self.channel = QWebChannel(self)
            self.channel.registerObject("muzix", self.bridge)
            self.web.page().setWebChannel(self.channel)
            js = QFile(":/qtwebchannel/qwebchannel.js")
            js.open(QFile.OpenModeFlag.ReadOnly)
            script = QWebEngineScript()
            script.setName("muzix-bridge")
            script.setSourceCode(bytes(js.readAll()).decode() + BRIDGE)
            script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
            script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            self.web.page().scripts().insert(script)
            # the system's own player: its media keys, and what plays shown there
            try:
                if sys.platform.startswith("linux"):
                    from .mpris import Mpris
                    self.system = Mpris(self.player, self.bring, self.relay.headers)
                elif sys.platform == "win32":
                    from .smtc import Smtc
                    self.system = Smtc(self.player, self.bring, self.relay.headers, self._for_speaker)
                elif sys.platform == "darwin":
                    from .nowplaying import NowPlaying
                    self.system = NowPlaying(self.player, self.bring, self.relay.headers, self._for_speaker)
            except Exception:       # no media keys, but the window plays on
                log.exception("The system's media controls didn't start")

        self.stack = QStackedWidget()
        self.address_page = self._address_page()
        self.stack.addWidget(self.address_page)
        self.stack.addWidget(self.web)
        self.setCentralWidget(self.stack)
        # no server yet, or this computer's library chosen: this computer's music (a folder for it asked for first)
        if cfg.library == "local" or not self.relay.address:
            self._choose_local()
        else:
            self._show_web()

        # the network changed (another wifi, a cable, none): the address that answers
        self._repick = QTimer(self, singleShot=True, interval=1500, timeout=self.relay.pick)
        if QNetworkInformation.loadDefaultBackend() and QNetworkInformation.instance():
            QNetworkInformation.instance().reachabilityChanged.connect(lambda _: self._repick.start())
        self._home = QTimer(self, interval=5 * 60 * 1000, timeout=self.relay.pick)   # and back home now and then
        self._home.start()

    # ------------------------------------------------------------ the server's address

    def _address_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("root")
        outer = QVBoxLayout(page)
        outer.addStretch(1)
        box = QVBoxLayout()
        box.setSpacing(12)
        box.addWidget(label("MUZIX", "kicker"), alignment=Qt.AlignmentFlag.AlignHCenter)
        box.addWidget(label("Your Muzix server's address", "title"), alignment=Qt.AlignmentFlag.AlignHCenter)
        self.field = QLineEdit()
        self.field.setPlaceholderText("muzix.example.com")
        self.field.setMinimumWidth(360)
        self.field.returnPressed.connect(self._connect)
        self.note = label("", "dim", wrap=True)
        self.go = QPushButton("Connect")
        self.go.setProperty("role", "accent")
        self.go.clicked.connect(self._connect)
        # or no server: the music in this computer's folders (Settings → Sharing)
        self.here = QPushButton("Play this computer's music instead")
        self.here.setProperty("role", "ghost")
        self.here.clicked.connect(self._choose_local)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.field)
        row.addWidget(self.go)
        row.addStretch(1)
        box.addLayout(row)
        box.addWidget(self.note, alignment=Qt.AlignmentFlag.AlignHCenter)
        box.addWidget(self.here, alignment=Qt.AlignmentFlag.AlignHCenter)
        outer.addLayout(box)
        outer.addStretch(2)
        return page

    def ask(self):
        """The address screen (the first time, and "Muzix library…" in the tray's menu)."""
        self.field.setText(self.relay.home or self.relay.away)
        self.note.setText("Now: this computer's music" if self.cfg.library == "local" else "")
        self.here.setEnabled(True)
        self.stack.setCurrentWidget(self.address_page)
        self.field.setFocus()

    def _connect(self):
        address = normalize(self.field.text())
        if not address:
            self.note.setText("That isn't a web address")
            return
        self.note.setText("Connecting…")
        self.go.setEnabled(False)

        def look():
            async def run():
                async with httpx.AsyncClient() as c:
                    return await health(c, address, 8)
            return asyncio.run(run())

        def done(answer):
            self.go.setEnabled(True)
            if not answer:
                self.note.setText(f"{address} doesn't answer as a Muzix server")
                return
            outside = normalize(answer.get("address") or "")
            home = address if local(address) else ""
            away = outside if outside and outside != address else ("" if home else address)
            self.cfg.listen_home, self.cfg.listen_away = home, away
            self.cfg.library = "server"
            config.save()
            self.relay.use(home, away)
            self.relay.use_local("", "")
            self.library.stop()
            self._show_web()

        in_background(look, done, lambda why: (self.go.setEnabled(True), self.note.setText(why)))

    # ------------------------------------------------------------ this computer's library

    def _choose_local(self):
        self.cfg.library = "local"
        config.save()
        self._open_local()
        if not any(f.kind == "music" for f in self.cfg.folders):
            QTimer.singleShot(300, self._ask_folder)        # once the window shows

    def _ask_folder(self):
        """No music folder yet: picked first thing. Without one, podcasts and radio play (and the user menu's
        "Add a music folder" asks again). Not over a window that isn't open (started in the tray)."""
        if not self.isVisible() or any(f.kind == "music" for f in self.cfg.folders):
            return
        box = QMessageBox(self)
        box.setWindowTitle("Muzix")
        box.setText("Where's your music?")
        box.setInformativeText("Pick the folder on this computer that has your music. Muzix only reads it.\n\n"
                               "Without one, podcasts and radio still play.")
        choose = box.addButton("Choose a folder", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
        server = box.addButton("Use a Muzix server", QMessageBox.ButtonRole.ActionRole)
        box.exec()
        if box.clickedButton() is choose:
            self.add_folder()
        elif box.clickedButton() is server:
            self.ask()

    def add_folder(self):
        """Another music folder, as Settings adds one (shared too while sharing is on)."""
        path = QFileDialog.getExistingDirectory(self, "A music folder")
        if not path or any(f.path == path for f in self.cfg.folders):
            return
        with config._lock:
            self.cfg.folders.append(config.Folder(path=path))
            config.save()
        self.folders_changed()
        self.folder_added.emit()

    def _open_local(self):
        """This computer's library: its server started (library.py), then the window on it."""
        self.stack.setCurrentWidget(self.address_page)
        self.note.setText("Opening this computer's music…")
        self.here.setEnabled(False)
        self.library.start(lambda: self.library_up.emit(self.library.ready.is_set()))

    def _library_up(self, ok: bool):
        self.here.setEnabled(True)
        if not ok:
            self.note.setText("This computer's library didn't start: see library/server.log in Muzix Desktop's data folder")
            return
        self.relay.use_local(self.library.address, self.library.token)
        self._show_web()

    def _use_library(self, which):
        """The user menu's switch: this computer's music, or the server's again (its address screen, if
        there's none yet)."""
        if which == "local":
            if self.cfg.library != "local":
                self._choose_local()
            return
        if self.cfg.library != "local":
            return
        if not self.relay.address:
            self.ask()
            return
        self.cfg.library = "server"
        config.save()
        self.relay.use_local("", "")
        self.library.stop()
        self._show_web()

    def folders_changed(self):
        """Settings changed the folders: the library follows."""
        if self.cfg.library == "local" and self.library.ready.is_set():
            threading.Thread(target=self.library.sync, daemon=True).start()

    def _show_web(self):
        self.stack.setCurrentWidget(self.web)
        self.web.load(QUrl(self.relay.origin + "/"))

    # ------------------------------------------------------------ the player's side

    def _for_speaker(self, url: str) -> str:
        """A link for a speaker, not this window's 127.0.0.1: the server's own address (the https one if it
        has it: a Cast speaker plays from https), or for this computer's library, its address on the network
        for speakers (relay.py)."""
        if not url.startswith(self.relay.origin):
            return url
        path = url[len(self.relay.origin):]
        base, local = self.relay._target(path.split("?")[0])
        if local:
            base = self.relay.for_speakers() or base
        elif self.relay.away.startswith("https://"):
            base = self.relay.away
        return base + path

    def _speakers(self):
        """The page's Cast button: the speakers on the network, or stopping the one that plays."""
        c = self.player.caster
        if c is None:
            return
        menu = QMenu(self)
        if c.active:
            menu.addAction(f"Stop playing on {c.name}", self.player.stop_casting)
        else:
            for uuid, name in c.list():
                menu.addAction(name, lambda u=uuid: self.player.cast_to(u))
            if not c.list():
                menu.addAction("No speakers on this network yet").setEnabled(False)
        menu.popup(QCursor.pos())

    def _command(self, t: str, m: dict):
        if t == "update":
            # a newer Muzix Desktop: one of its releases on GitHub (the server says which: backend/muzix/api/android.py),
            # downloaded by the browser
            url = m.get("url") or ""
            if re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+/releases/download/desktop-v[\w.-]+/muzix-desktop-[\w.-]+", url):
                QDesktopServices.openUrl(QUrl(url))
        elif t == "cast":
            self._speakers()
        elif t == "server":
            self.ask()
        elif t == "library":
            self._use_library(m.get("which"))
        elif t == "folder":
            self.add_folder()
        elif t == "open":
            url = QUrl(m.get("url") or "")
            if url.scheme() in ("http", "https"):
                # the server's own web version, not the window's: its admin pages
                if url.toString().startswith(self.relay.origin):
                    url = QUrl(self.relay.address + url.toString()[len(self.relay.origin):])
                QDesktopServices.openUrl(url)

    # ------------------------------------------------------------ the window

    def bring(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
        self.raise_()
        self.activateWindow()

    def closeEvent(self, e):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            QApplication.instance().quit()
            return
        # Muzix stays in the tray (the music, later, plays on)
        e.ignore()
        self.hide()

    def shutdown(self):
        if self.player:
            self.player.release()
        self.library.stop()
        self.relay.stop()

"""The Muzix window: the web interface that comes with the app (relay.py serves it, and passes what's for
the server on), shown by QtWebEngine, as it looks in a browser, with the app's player behind it
(player.py): the page hands it the queue through `window.MuzixApp`, as in the Android app. The first
time, and from the tray's menu, it asks for the server's address. Closing it leaves Muzix in the tray,
playing on."""

import asyncio
import logging
import sys

import httpx
from PySide6.QtCore import QFile, QObject, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QCursor, QDesktopServices
from PySide6.QtNetwork import QNetworkCookie, QNetworkInformation
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLineEdit, QMainWindow, QMenu, QPushButton, QStackedWidget,
                               QSystemTrayIcon, QVBoxLayout, QWidget)

from . import config, player
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
    def __init__(self, cfg: config.Config):
        super().__init__()
        self.cfg = cfg
        self.setWindowTitle("Muzix")
        self.resize(1280, 820)
        self.relay = Relay(cfg.listen_home, cfg.listen_away, cfg.window_port)
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
            self.player = player.Player(self._cookies, lambda: self.isVisible() and not self.isMinimized(), self._for_speaker)
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
                    self.system = Mpris(self.player, self.bring, self._cookies)
                elif sys.platform == "win32":
                    from .smtc import Smtc
                    self.system = Smtc(self.player, self.bring, self._cookies, self._for_speaker)
                elif sys.platform == "darwin":
                    from .nowplaying import NowPlaying
                    self.system = NowPlaying(self.player, self.bring, self._cookies, self._for_speaker)
            except Exception:       # no media keys, but the window plays on
                log.exception("The system's media controls didn't start")

        self.stack = QStackedWidget()
        self.address_page = self._address_page()
        self.stack.addWidget(self.address_page)
        self.stack.addWidget(self.web)
        self.setCentralWidget(self.stack)
        if self.relay.address:
            self._show_web()
        else:
            self.ask()

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
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.field)
        row.addWidget(self.go)
        row.addStretch(1)
        box.addLayout(row)
        box.addWidget(self.note, alignment=Qt.AlignmentFlag.AlignHCenter)
        outer.addLayout(box)
        outer.addStretch(2)
        return page

    def ask(self):
        """The address screen (the first time, and "Muzix server…" in the tray's menu)."""
        self.field.setText(self.relay.home or self.relay.away)
        self.note.setText("")
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
            config.save()
            self.relay.use(home, away)
            self._show_web()

        in_background(look, done, lambda why: (self.go.setEnabled(True), self.note.setText(why)))

    def _show_web(self):
        self.stack.setCurrentWidget(self.web)
        self.web.load(QUrl(self.relay.origin + "/"))

    # ------------------------------------------------------------ the player's side

    def _cookies(self) -> list[str]:
        """The player's way in: the window's secret and its login (the relay sees it go by)."""
        s = self.relay.session
        return [f"{SECRET_COOKIE}={self.relay.secret}"] + ([f"muzix_session={s}"] if s else [])

    def _for_speaker(self, url: str) -> str:
        """A link for a speaker: on the server's own address, the https one if it has it (a Cast speaker
        plays from https), not this window's 127.0.0.1."""
        base = self.relay.away if self.relay.away.startswith("https://") else self.relay.address
        return base + url[len(self.relay.origin):] if url.startswith(self.relay.origin) else url

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
        if t == "cast":
            self._speakers()
        elif t == "server":
            self.ask()
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
        self.relay.stop()

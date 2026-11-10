"""The window's own little server (window.py), on 127.0.0.1: it serves the web interface that comes with
the app and passes everything for the Muzix server (`/api/…`, the Connect socket) on to it, at its
address at home while that answers and its outside address otherwise. The login cookie stays with the
window, as in a browser: moving between the addresses changes nothing for the page. Only the window may
use it: it carries a secret cookie, new for each run (window.py sets it).

With this computer's library on (library.py), the library is the local server's, signed in with its
token here; what's the account's stays the server's while there's one: podcasts, radio, the account's
devices and Muzix Connect (docs/app-plan.md).

While neither address answers, what's downloaded answers for the server (downloads.py): the sign-in state,
the downloaded pages' data and their covers."""

import asyncio
import logging
import os
import platform
import re
import secrets
import socket
import sys
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
import uvicorn
import websockets
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from . import __version__

log = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)       # not a line for each of the window's requests

SECRET_COOKIE = "muzix_window"
SECRET_HEADER = "x-muzix-window"        # the same, from the app's player (player.py), which sends no cookies
# what the server sees: its list of devices names the window after the computer (backend/muzix/security.py)
UA = f"MuzixDesktop/{__version__} ({platform.system() or 'Unknown'}; {platform.node() or 'Computer'})"
# not passed on, either way
# the account's, on the server, even while the library is this computer's
ACCOUNT = ("/api/podcasts", "/api/radio", "/api/connect", "/api/me/devices", "/api/auth/logout", "/api/android", "/api/desktop",
           "/api/schemes")
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
       "transfer-encoding", "upgrade", "host", "user-agent", SECRET_HEADER}


# what a speaker may have of this computer's library: audio by its signed links, and covers
SPEAKER = re.compile(r"/api/(stream/\d+|books/\d+/parts/\d+/stream|radio/play|podcasts/episodes/\d+/stream|art/[\w/.-]+)")


def _lan_ip() -> str:
    """This computer's address on the local network (the one its traffic leaves by; nothing is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))
        return s.getsockname()[0]
    except OSError:
        return ""
    finally:
        s.close()


def web_dir() -> str:
    """The web interface that comes with the app: packed beside the code, or the frontend's build in a checkout."""
    here = os.path.dirname(os.path.abspath(__file__))
    base = getattr(sys, "_MEIPASS", None)
    for d in ([os.path.join(base, "muzix_desktop", "web")] if base else []) + [
            os.path.join(here, "web"), os.path.join(here, "..", "..", "frontend", "dist")]:
        if os.path.isfile(os.path.join(d, "index.html")):
            return os.path.abspath(d)
    return ""


def local(address: str) -> bool:
    """An address on the local network: a private IP, or a name that only means something there."""
    import ipaddress
    host = urlsplit(address).hostname or ""
    if "." not in host or host.endswith((".local", ".lan", ".home.arpa")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_link_local or ip.is_loopback


def normalize(text: str) -> str | None:
    """"muzix.example.com" → "https://muzix.example.com"; anything after the address is dropped."""
    text = text.strip().rstrip("/")
    if not text:
        return None
    u = urlsplit(text if "://" in text else "https://" + text)
    if u.scheme not in ("http", "https") or not u.hostname:
        return None
    return f"{u.scheme}://{u.netloc}"


async def health(client: httpx.AsyncClient, address: str, wait: float) -> dict | None:
    """What `address` answers as a Muzix server ({ok, api, address, ...}), or None."""
    try:
        r = await client.get(address + "/api/health", timeout=wait, headers={"User-Agent": UA})
        data = r.json()
        return data if r.status_code == 200 and data.get("ok") else None
    except (httpx.HTTPError, ValueError):
        return None


class Relay:
    def __init__(self, home: str = "", away: str = "", port: int = 0):
        self.secret = secrets.token_urlsafe(24)
        self.home, self.away = home, away
        self.address = home or away             # where the server is now
        self.session = ""                       # the window's login: the player's requests carry it too
        self.signed_in = None                   # (session) → called when the window signs in to the server
        self.local, self.local_token = "", ""   # this computer's library, when it's the window's (library.py)
        self.lan = ""                           # this computer's library for Cast speakers (for_speakers)
        self.offline = False                    # neither address answers: what's downloaded answers instead
        self.on_offline = None                  # (offline) → called when that changes, from the relay's thread
        self.downloads = None                   # downloads.py, for its answers offline
        self._cast = ("", 0)                    # the server's signature for speakers' links, and until when
        self.web = web_dir()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.client: httpx.AsyncClient | None = None
        self._picking: asyncio.Task | None = None
        self.sock = self._bind(port)
        self.port = self.sock.getsockname()[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        app = Starlette(routes=[
            WebSocketRoute("/api/{path:path}", self._socket),
            Route("/api/{path:path}", self._api, methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]),
            Route("/manifest.webmanifest", self._api),
            Route("/{path:path}", self._file),
        ])
        self.server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off", ws="websockets-sansio"))
        threading.Thread(target=self._run, name="relay", daemon=True).start()

    @staticmethod
    def _bind(port: int) -> socket.socket:
        """The same port each run if it's free (the window keeps its login and settings by it), else another."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)     # the last run's port, just let go of
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            s.bind(("127.0.0.1", 0))
        s.listen(64)
        return s

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(30, read=None), follow_redirects=False)
        loop.run_until_complete(self.server.serve(sockets=[self.sock]))

    def stop(self):
        self.server.should_exit = True
        if getattr(self, "_lan_server", None):
            self._lan_server.should_exit = True

    # ------------------------------------------------------------ Cast speakers, for this computer's library

    def for_speakers(self) -> str:
        """Where a Cast speaker on the network gets this computer's library (started the first time): only its
        signed audio links (a speaker's, ?ct=) and covers, nothing else of it."""
        if self.lan or not self.loop:
            return self.lan
        ip = _lan_ip()
        if not ip:
            return ""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind((ip, 0))
        s.listen(16)
        app = Starlette(routes=[Route("/api/{path:path}", self._speaker, methods=["GET", "HEAD"])])
        self._lan_server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
        asyncio.run_coroutine_threadsafe(self._lan_server.serve(sockets=[s]), self.loop)
        self.lan = f"http://{ip}:{s.getsockname()[1]}"
        log.info("Cast speakers get this computer's music from %s", self.lan)
        return self.lan

    async def _speaker(self, request: Request):
        path = request.url.path
        signed = SPEAKER.fullmatch(path) and (request.query_params.get("ct") or path.startswith("/api/art/"))
        if not signed or not self.local:
            return PlainTextResponse("Not for speakers", 403)
        headers = [(k, v) for k, v in request.headers.items() if k in ("range", "accept", "icy-metadata")]
        url = self.local + path + (f"?{request.url.query}" if request.url.query else "")
        r = await self.client.send(self.client.build_request(request.method, url, headers=headers), stream=True)
        resp = StreamingResponse(r.aiter_raw(), status_code=r.status_code, background=BackgroundTask(r.aclose))
        resp.raw_headers = [(k.encode("latin-1"), v.encode("latin-1")) for k, v in r.headers.multi_items()
                            if k.lower() not in HOP and k.lower() != "set-cookie"]
        return resp

    # ------------------------------------------------------------ links for Cast speakers

    def speaker_link(self, url: str) -> str:
        """A link for a speaker, not this window's 127.0.0.1: the server's own address (the https one if it
        has it: a Cast speaker plays from https), or for this computer's library, its address on the network
        for speakers. With this computer's library on, the page's links are signed by it, so the server's
        (the account's episodes and stations) get the server's own signature instead."""
        if not url.startswith(self.origin + "/"):
            return url
        path = url[len(self.origin):]
        base, local = self._target(path.split("?")[0])
        if local:
            return (self.for_speakers() or base) + path
        if self.local and "ct=" in path and (token := self._server_token()):
            u = urlsplit(path)
            query = [(k, token if k == "ct" else v) for k, v in parse_qsl(u.query, keep_blank_values=True)]
            path = urlunsplit(u._replace(query=urlencode(query)))
        if self.away.startswith("https://"):
            base = self.away
        return base + path

    def _server_token(self) -> str:
        """The server's signature for speakers' links (the window's login's), kept while it's good for an hour more."""
        token, until = self._cast
        if until - time.time() > 3600:
            return token

        async def ask():
            r = await self.client.get(self.address + "/api/cast/token", timeout=8,
                                      headers={"cookie": f"muzix_session={self.session}", "user-agent": UA})
            r.raise_for_status()
            return r.json()
        try:
            got = asyncio.run_coroutine_threadsafe(ask(), self.loop).result(10)
            self._cast = (got["token"], int(got["expires"]))
        except Exception as e:
            log.warning("No speaker link from the server: %s", e)
            return ""
        return self._cast[0]

    # ------------------------------------------------------------ the server's address

    def use(self, home: str, away: str):
        """Another server (or its addresses), from the address screen, which has just heard from it."""
        self.home, self.away = home, away
        self.address = home or away
        self._reached(True)

    def use_local(self, address: str, token: str):
        """This computer's library (library.py), or the server's again ("")."""
        self.local, self.local_token = address, token

    def _target(self, path: str) -> tuple[str, bool]:
        """Where a request goes: (address, whether it's this computer's library)."""
        if self.local and not (self.address and path.startswith(ACCOUNT)):
            return self.local, True
        return self.address, False

    def pick(self):
        """Which address answers, from the window's thread (the network changed)."""
        if self.loop:
            asyncio.run_coroutine_threadsafe(self._pick(), self.loop)

    async def _pick(self) -> bool:
        """The address at home if it answers (quickly), else the outside one: whether either did."""
        for a in [x for x in (self.home, self.away) if x]:
            wait = 2.5 if a == self.home and self.away else 8
            if await health(self.client, a, wait):
                if a != self.address:
                    log.info("The server is at %s now", a)
                self.address = a
                self._reached(True)
                return True
        self._reached(not self.address)
        return False

    def _reached(self, yes: bool):
        if self.offline == (not yes):
            return
        self.offline = not yes
        log.info("The server can't be reached: what's downloaded plays" if self.offline else "The server answers again")
        if self.on_offline:
            self.on_offline(self.offline)

    def _offline_answer(self, request: Request):
        """Offline, a GET of the API: what's downloaded has it, or it needs the server."""
        path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        got = self.downloads.answer(path) if self.downloads and request.method == "GET" else None
        if got:
            return Response(got[1], media_type=got[0])
        if request.url.path == "/api/auth/state" or request.method != "GET":
            return JSONResponse({"detail": "The server can't be reached"}, 502)
        return JSONResponse({"detail": "Not downloaded: this needs the server"}, 404)

    async def _repick(self) -> bool:
        """One look at a time, however many requests failed together."""
        if self._picking is None or self._picking.done():
            self._picking = asyncio.ensure_future(self._pick())
        return await asyncio.shield(self._picking)

    # ------------------------------------------------------------ the window's requests

    def _allowed(self, conn) -> bool:
        given = conn.cookies.get(SECRET_COOKIE) or conn.headers.get(SECRET_HEADER) or ""
        return secrets.compare_digest(given, self.secret)

    def headers(self, url: str) -> dict:
        """What the app's player (and the system's media controls) send for `url`: the window's secret, to
        this server only."""
        return {SECRET_HEADER: self.secret} if url.startswith(self.origin + "/") else {}

    def _headers(self, conn, local: bool = False) -> list[tuple[str, str]]:
        """The window's headers for the server: its cookies without the window's own secret. This computer's
        library gets none of the window's cookies (they're the server's), but its own token."""
        out = []
        for k, v in conn.headers.items():
            if k in HOP or (local and k in ("cookie", "authorization")):
                continue
            if k == "cookie":
                for c in v.split("; "):
                    if c.startswith("muzix_session="):
                        self.session = c[len("muzix_session="):]
                v = "; ".join(c for c in v.split("; ") if not c.startswith(SECRET_COOKIE + "="))
                if not v:
                    continue
            out.append((k, v))
        if local:
            out.append(("authorization", f"Bearer {self.local_token}"))
        elif self.session and not any(k == "cookie" and "muzix_session=" in v for k, v in out):
            out.append(("cookie", f"muzix_session={self.session}"))     # the player's: the window's login
        return out + [("user-agent", UA)]

    async def _api(self, request: Request):
        if not self._allowed(request):
            return PlainTextResponse("Only the Muzix window may use this", 403)
        base, local = self._target(request.url.path)
        if not base:
            return JSONResponse({"detail": "No server yet"}, 502)
        if self.offline and not local:
            return self._offline_answer(request)
        path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        again = request.method in ("GET", "HEAD") and not local     # a body can't be sent twice
        for attempt in (0, 1):
            req = self.client.build_request(request.method, base + path, headers=self._headers(request, local),
                                            content=None if request.method in ("GET", "HEAD") else request.stream())
            try:
                r = await self.client.send(req, stream=True)
                break
            except httpx.TransportError:
                # the server isn't at that address any more (left home): the other one, once
                if attempt or not again or not await self._repick():
                    return self._offline_answer(request) if self.offline else JSONResponse({"detail": "The server can't be reached"}, 502)
                base = self.address
        resp = StreamingResponse(r.aiter_raw(), status_code=r.status_code, background=BackgroundTask(r.aclose))
        resp.raw_headers = [(k.encode("latin-1"), self._back(k, v, base).encode("latin-1"))
                            for k, v in r.headers.multi_items()
                            if k.lower() not in HOP and not (local and k.lower() == "set-cookie")]
        return resp

    def _back(self, name: str, value: str, base: str) -> str:
        """The server's headers as the window needs them: its login cookie for 127.0.0.1 (plain http), and
        its redirects here."""
        name = name.lower()
        if name == "set-cookie":
            if m := re.match(r"muzix_session=([^;]*)", value):     # signed in (or out)
                self.session = m.group(1)
                if self.session and self.signed_in:
                    self.signed_in(self.session)
            return re.sub(r";\s*(secure|domain=[^;]*)", "", value, flags=re.I)
        if name == "location" and value.startswith(base):
            return value[len(base):] or "/"
        return value

    async def _socket(self, ws: WebSocket):
        """The Connect socket, passed on both ways."""
        base, local = self._target(ws.url.path)
        if not self._allowed(ws) or not base:
            await ws.close(code=1008)
            return
        await ws.accept()
        url = base.replace("http", "ws", 1) + ws.url.path + (f"?{ws.url.query}" if ws.url.query else "")
        headers = [(k, v) for k, v in self._headers(ws, local) if k in ("cookie", "user-agent", "authorization")]
        try:
            async with websockets.connect(url, additional_headers=headers, max_size=None, open_timeout=10) as up:
                async def down():
                    async for m in up:
                        await (ws.send_text(m) if isinstance(m, str) else ws.send_bytes(m))

                async def upward():
                    while True:
                        m = await ws.receive()
                        if m["type"] == "websocket.disconnect":
                            return
                        await up.send(m["text"] if m.get("text") is not None else m.get("bytes") or b"")

                tasks = [asyncio.ensure_future(down()), asyncio.ensure_future(upward())]
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for t in tasks:
                    t.cancel()
        except (OSError, asyncio.TimeoutError):
            await self._repick()            # the server isn't there: the other address
        except (websockets.WebSocketException, WebSocketDisconnect):
            pass                            # the server said no (signed out), or the socket closed
        try:
            await ws.close()
        except RuntimeError:
            pass

    async def _file(self, request: Request):
        """The interface's files, and its page (index.html) for every other address, as the server answers."""
        if not self.web:
            return PlainTextResponse("The web interface isn't here (frontend/ → npm run build)", 500)
        name = request.path_params["path"]
        f = os.path.realpath(os.path.join(self.web, name))
        if name and f.startswith(self.web + os.sep) and os.path.isfile(f):
            return FileResponse(f)
        return FileResponse(os.path.join(self.web, "index.html"), headers={"Cache-Control": "no-cache"})

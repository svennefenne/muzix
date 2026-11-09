"""The window's own little server (window.py), on 127.0.0.1: it serves the web interface that comes with
the app and passes everything for the Muzix server (`/api/…`, the Connect socket) on to it, at its
address at home while that answers and its outside address otherwise. The login cookie stays with the
window, as in a browser: moving between the addresses changes nothing for the page. Only the window may
use it: it carries a secret cookie, new for each run (window.py sets it)."""

import asyncio
import logging
import os
import platform
import re
import secrets
import socket
import sys
import threading
from urllib.parse import urlsplit

import httpx
import uvicorn
import websockets
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from . import __version__

log = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)       # not a line for each of the window's requests

SECRET_COOKIE = "muzix_window"
# what the server sees: its list of devices names the window after the computer (backend/muzix/security.py)
UA = f"MuzixDesktop/{__version__} ({platform.system() or 'Unknown'}; {platform.node() or 'Computer'})"
# not passed on, either way
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
       "transfer-encoding", "upgrade", "host", "user-agent"}


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

    # ------------------------------------------------------------ the server's address

    def use(self, home: str, away: str):
        """Another server (or its addresses), from the address screen."""
        self.home, self.away = home, away
        self.address = home or away

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
                return True
        return False

    async def _repick(self) -> bool:
        """One look at a time, however many requests failed together."""
        if self._picking is None or self._picking.done():
            self._picking = asyncio.ensure_future(self._pick())
        return await asyncio.shield(self._picking)

    # ------------------------------------------------------------ the window's requests

    def _allowed(self, conn) -> bool:
        return secrets.compare_digest(conn.cookies.get(SECRET_COOKIE, ""), self.secret)

    def _headers(self, conn) -> list[tuple[str, str]]:
        """The window's headers for the server: its cookies without the window's own secret."""
        out = []
        for k, v in conn.headers.items():
            if k in HOP:
                continue
            if k == "cookie":
                for c in v.split("; "):
                    if c.startswith("muzix_session="):
                        self.session = c[len("muzix_session="):]
                v = "; ".join(c for c in v.split("; ") if not c.startswith(SECRET_COOKIE + "="))
                if not v:
                    continue
            out.append((k, v))
        return out + [("user-agent", UA)]

    async def _api(self, request: Request):
        if not self._allowed(request):
            return PlainTextResponse("Only the Muzix window may use this", 403)
        if not self.address:
            return JSONResponse({"detail": "No server yet"}, 502)
        path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        again = request.method in ("GET", "HEAD")      # a body can't be sent twice
        for attempt in (0, 1):
            req = self.client.build_request(request.method, self.address + path, headers=self._headers(request),
                                            content=None if again else request.stream())
            try:
                r = await self.client.send(req, stream=True)
                break
            except httpx.TransportError:
                # the server isn't at that address any more (left home): the other one, once
                if attempt or not again or not await self._repick():
                    return JSONResponse({"detail": "The server can't be reached"}, 502)
        resp = StreamingResponse(r.aiter_raw(), status_code=r.status_code, background=BackgroundTask(r.aclose))
        resp.raw_headers = [(k.encode("latin-1"), self._back(k, v).encode("latin-1"))
                            for k, v in r.headers.multi_items() if k.lower() not in HOP]
        return resp

    def _back(self, name: str, value: str) -> str:
        """The server's headers as the window needs them: its login cookie for 127.0.0.1 (plain http), and
        its redirects here."""
        name = name.lower()
        if name == "set-cookie":
            if m := re.match(r"muzix_session=([^;]*)", value):     # signed in (or out)
                self.session = m.group(1)
            return re.sub(r";\s*(secure|domain=[^;]*)", "", value, flags=re.I)
        if name == "location" and value.startswith(self.address):
            return value[len(self.address):] or "/"
        return value

    async def _socket(self, ws: WebSocket):
        """The Connect socket, passed on both ways."""
        if not self._allowed(ws) or not self.address:
            await ws.close(code=1008)
            return
        await ws.accept()
        url = self.address.replace("http", "ws", 1) + ws.url.path + (f"?{ws.url.query}" if ws.url.query else "")
        headers = [(k, v) for k, v in self._headers(ws) if k in ("cookie", "user-agent", "authorization")]
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
        except (OSError, websockets.WebSocketException, WebSocketDisconnect, asyncio.TimeoutError):
            await self._repick()
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

"""Sharing this computer's folders with Muzix servers: linking (a server's address and code,
answered with this computer's code by its admin) and the connection the client keeps open to
each linked server while sharing is on. The server asks through it for the catalog, a song's
file or a cover (backend/muzix/tunnel.py has its side and the frames), and nothing else is
ever read: only songs in the catalog, which only has the shared folders.

Servers are reached over HTTPS only. MUZIX_DESKTOP_INSECURE=1 lets a test reach a server on this
computer over plain http (localhost and 127.0.0.1 only)."""

import asyncio
import hashlib
import json
import logging
import os
import secrets
import ssl
import struct
import threading
from urllib.parse import urlsplit

import certifi
import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from . import __version__, config
from .catalog import Catalog
from .shared import PROTOCOL, clean_code

log = logging.getLogger(__name__)

HEAD = struct.Struct(">IB")
CHUNK = 256 * 1024
UA = f"MuzixDesktop/{__version__} (+https://github.com/svennefenne/muzix)"
RETRY = (3, 5, 10, 20, 30, 60)          # seconds between tries to reach a server


class LinkError(Exception):
    """Something to show as it is."""


def _insecure_ok(u) -> bool:
    return os.environ.get("MUZIX_DESKTOP_INSECURE") == "1" and u.hostname in ("localhost", "127.0.0.1")


def clean_address(text: str) -> str:
    """A server's address as typed: a name or an https:// address (never plain http)."""
    t = (text or "").strip().rstrip("/")
    if not t:
        raise LinkError("Enter the server's address")
    if "://" not in t:
        t = "https://" + t
    u = urlsplit(t)
    if not u.hostname or u.scheme not in ("https", "http"):
        raise LinkError(f"{text.strip()} isn't a server address")
    if u.scheme != "https" and not _insecure_ok(u):
        raise LinkError("The server has to be reached over HTTPS (https://…)")
    return f"{u.scheme}://{u.netloc}{u.path.rstrip('/')}"


def _http() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": UA}, timeout=15, follow_redirects=True)


def _detail(r: httpx.Response) -> str:
    try:
        d = r.json().get("detail")
        if isinstance(d, str):
            return d
    except (ValueError, AttributeError):
        pass
    return f"HTTP {r.status_code}"


def link(address: str, code: str) -> config.Server:
    """Hand a server its own code: a request there, until its admin enters this computer's code."""
    cfg = config.load()
    if len(clean_code(code)) != 20:
        raise LinkError("A sharing code is 20 letters and digits: XXXXX-XXXXX-XXXXX-XXXXX")
    base = clean_address(address)
    try:
        with _http() as c:
            r = c.get(base + "/api/network/hello")
            info = r.json() if r.status_code == 200 else None
            if not isinstance(info, dict) or not info.get("server_id"):
                raise LinkError(f"{base} doesn't answer as a Muzix server with the Library Network")
            base = str(r.url)[: -len("/api/network/hello")]
            if urlsplit(base).scheme != "https" and not _insecure_ok(urlsplit(base)):
                raise LinkError("The server has to be reached over HTTPS")
            who = info.get("name") or base
            if info.get("protocol") != PROTOCOL:
                raise LinkError(f"{who} links another way: update Muzix Desktop or the server")
            if not info.get("open"):
                raise LinkError(f"{who} has the Library Network turned off")
            sid = str(info["server_id"])
            check = hashlib.sha256(f"{sid}:{clean_code(cfg.code)}".encode()).hexdigest()
            r = c.post(base + "/api/network/link", json={
                "protocol": PROTOCOL, "code": clean_code(code), "server_id": cfg.computer_id, "name": cfg.name,
                "address": "", "key": secrets.token_urlsafe(32), "kind": "computer", "check": check})
    except httpx.HTTPError as e:
        raise LinkError(f"Couldn't reach {base} ({e or e.__class__.__name__})")
    if r.status_code == 403:
        raise LinkError(f"{who} says that isn't its sharing code")
    if r.status_code == 429:
        raise LinkError(f"{who} has had too many wrong codes from here: try again in a few minutes")
    if r.status_code != 200:
        raise LinkError(f"{who} couldn't take the request ({_detail(r)})")
    got = r.json()
    server = config.Server(address=base, server_id=sid, name=str(got.get("name") or who), key=str(got["key"]),
                           state="linked" if got.get("linked") else "waiting")
    with config._lock:
        cfg.servers = [s for s in cfg.servers if s.server_id != sid] + [server]
        config.save()
    return server


def unlink(server: config.Server):
    """This computer leaves a server's network: it's told, and its copy of the catalog goes there."""
    try:
        with _http() as c:
            c.post(server.address + "/api/network/unlink", headers={"Authorization": f"Bearer {server.key}"})
    except httpx.HTTPError as e:
        log.warning("Couldn't tell %s: %s", server.name, e)
    cfg = config.load()
    with config._lock:
        cfg.servers = [s for s in cfg.servers if s.server_id != server.server_id]
        config.save()


class Sharing:
    """The connections to the linked servers, in a thread of their own. `on_status(server_id,
    status)` hears how each stands: connecting, waiting, linked, offline, removed."""

    def __init__(self, catalog: Catalog, on_status=lambda sid, status: None):
        self.catalog, self.on_status = catalog, on_status
        self.status: dict[str, str] = {}
        self.loop = asyncio.new_event_loop()
        self.tasks: dict[str, asyncio.Task] = {}
        self.live: dict[str, object] = {}       # server id → its open connection
        self.cancelled: set[tuple[str, int]] = set()
        self.ssl = ssl.create_default_context(cafile=certifi.where())
        threading.Thread(target=self.loop.run_forever, name="sharing", daemon=True).start()

    def _call(self, fn, *args):
        self.loop.call_soon_threadsafe(fn, *args)

    def _set(self, sid: str, status: str):
        self.status[sid] = status
        try:
            self.on_status(sid, status)
        except Exception:
            log.exception("status callback")

    # ------------------------------------------------------------ from the app

    def start(self):
        """Connect to every server this computer shares with."""
        for s in config.load().servers:
            self._call(self._start, s.server_id)

    def stop(self):
        for sid in list(self.tasks):
            self._call(self._stop, sid)

    def follow(self, server_id: str):
        """A server just added (or its connection to start again)."""
        self._call(self._start, server_id)

    def forget(self, server_id: str):
        self._call(self._stop, server_id)

    def changed(self):
        """The catalog changed: the servers fetch it again."""
        async def tell():
            for ws in list(self.live.values()):
                try:
                    await ws.send(json.dumps({"op": "changed"}))
                except ConnectionClosed:
                    pass
        asyncio.run_coroutine_threadsafe(tell(), self.loop)

    # ------------------------------------------------------------ in the thread

    def _start(self, sid: str):
        if sid in self.tasks and not self.tasks[sid].done():
            return
        self.tasks[sid] = self.loop.create_task(self._run(sid))

    def _stop(self, sid: str):
        task = self.tasks.pop(sid, None)
        if task:
            task.cancel()
        self.live.pop(sid, None)
        if config.load().server(sid):
            self._set(sid, "stopped")

    async def _run(self, sid: str):
        tries = 0
        while True:
            server = config.load().server(sid)
            if server is None:
                return
            url = server.address.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/api/network/tunnel"
            self._set(sid, "connecting")
            try:
                async with connect(url, additional_headers={"Authorization": f"Bearer {server.key}"},
                                   user_agent_header=UA, max_size=None, ping_interval=20, ping_timeout=30,
                                   ssl=self.ssl if url.startswith("wss://") else None, open_timeout=20) as ws:
                    tries = 0
                    self.live[sid] = ws
                    await self._serve(sid, ws)
            except asyncio.CancelledError:
                raise
            except InvalidStatus as e:
                # it doesn't know this key (the link ended while this computer was off), or its
                # Library Network is off: asked again now and then, the user can remove it
                log.info("%s: %s", server.name, e)
                self.live.pop(sid, None)
                self._set(sid, "refused")
                await asyncio.sleep(RETRY[-1])
                continue
            except ConnectionClosed as e:
                if e.rcvd and e.rcvd.code in (4401, 4403):
                    self._removed(sid)
                    return
            except (OSError, asyncio.TimeoutError, ValueError) as e:
                log.info("%s can't be reached: %s", server.name, e)
            finally:
                self.live.pop(sid, None)
            self._set(sid, "offline")
            await asyncio.sleep(RETRY[min(tries, len(RETRY) - 1)])
            tries += 1

    def _removed(self, sid: str):
        """The server ended the link (or never knew this key): it's gone from the list."""
        cfg = config.load()
        with config._lock:
            s = cfg.server(sid)
            if s is not None:
                s.state = "removed"
                config.save()
        self._set(sid, "removed")

    def _state(self, sid: str, state: str):
        cfg = config.load()
        with config._lock:
            s = cfg.server(sid)
            if s is not None and s.state != state:
                s.state = state
                config.save()
        self._set(sid, state)

    async def _serve(self, sid: str, ws):
        async for raw in ws:
            if isinstance(raw, bytes):
                continue
            try:
                m = json.loads(raw)
            except ValueError:
                continue
            op = m.get("op")
            if op == "state":
                if m.get("state") == "removed":
                    self._removed(sid)
                    await ws.close()
                    return
                self._state(sid, m.get("state") or "waiting")
            elif op == "cancel":
                self.cancelled.add((sid, m.get("id")))
            elif "id" in m:
                asyncio.create_task(self._answer(sid, ws, m))

    async def _answer(self, sid: str, ws, m: dict):
        rid, op = m["id"], m.get("op")
        try:
            if op == "catalog":
                page = await asyncio.to_thread(self.catalog.page, str(m.get("part")), int(m.get("after") or 0),
                                               int(m.get("limit") or 1000))
                await ws.send(json.dumps({"id": rid, "result": page}, default=str))
            elif op == "file":
                path = self.catalog.path_of(int(m.get("track") or 0))
                if path is None:
                    raise LookupError("That song isn't shared from here any more")
                await self._send_file(sid, ws, rid, path)
            elif op == "art":
                data = await asyncio.to_thread(self.catalog.cover, int(m.get("item") or 0)) \
                    if m.get("kind") == "album" else None
                if not data:
                    raise LookupError("No picture")
                await self._send_bytes(sid, ws, rid, data)
            elif op == "lyrics":
                await ws.send(json.dumps({"id": rid, "result": None}))
            else:
                raise LookupError(f"Unknown request {op}")
        except (LookupError, OSError, ValueError, KeyError) as e:
            try:
                await ws.send(json.dumps({"id": rid, "error": str(e) or e.__class__.__name__}))
            except ConnectionClosed:
                pass
        except ConnectionClosed:
            pass
        finally:
            self.cancelled.discard((sid, rid))

    async def _send_file(self, sid: str, ws, rid: int, path: str):
        with open(path, "rb") as f:
            while (sid, rid) not in self.cancelled:
                chunk = await asyncio.to_thread(f.read, CHUNK)
                last = len(chunk) < CHUNK
                await ws.send(HEAD.pack(rid, 1 if last else 0) + chunk)
                if last:
                    return

    async def _send_bytes(self, sid: str, ws, rid: int, data: bytes):
        for i in range(0, max(1, len(data)), CHUNK):
            if (sid, rid) in self.cancelled:
                return
            await ws.send(HEAD.pack(rid, 1 if i + CHUNK >= len(data) else 0) + data[i:i + CHUNK])

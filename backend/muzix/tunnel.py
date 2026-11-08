"""Computers in the Library Network: the desktop client (desktop/ in the repository) shares folders
on someone's computer, which can't be called (no address of its own, no certificate). So it calls
in and keeps the connection open, a websocket opened with the key it got when it linked
(network.receive), and this server asks through it for what it needs: the computer's catalog, a
song's file, a cover. While a computer isn't connected its music is hidden (db.py: Peer.away), and
it's back when it is.

What this server asks is a text frame {"id", "op", ...}. The computer answers in text ({"id",
"result"} or {"id", "error"}) or, for a file or a picture, in binary frames that start with the
request's id and a flag (HEAD; flag 1: the last one). It says {"op": "changed"} when its catalog
changed, and this server tells it {"op": "state", "state": "waiting" | "linked" | "removed"}, and
{"op": "playing", "track"} when someone here plays one of its songs.

A song's file comes here once and is kept in the cache (cache_dir(), pruned to CACHE_LIMIT), where the
rest of Muzix plays it like its own: converted, rendered (chiptunes), cast.
"""

import asyncio
import itertools
import json
import logging
import os
import queue
import struct
import threading
import time
from datetime import datetime, timezone

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select, update

from . import db, env, jobs, network
from .models import Peer

log = logging.getLogger(__name__)

HEAD = struct.Struct(">IB")           # the request's id, and 1 on its last frame
ASK_TIMEOUT = 30
CACHE_LIMIT = 4 * 1024 ** 3


def cache_dir() -> str:
    return os.path.join(env.CACHE_DIR, "computers")


class Gone(Exception):
    """The computer isn't connected (any more), or didn't answer."""


class Refused(Exception):
    """The computer answered that it can't give it (the file is gone there, say)."""


class Computer:
    """One computer's connection, asked from any thread."""

    def __init__(self, ws: WebSocket, peer_id: int, sid: str, name: str, loop: asyncio.AbstractEventLoop):
        self.ws, self.peer_id, self.sid, self.name, self.loop = ws, peer_id, sid, name, loop
        self.ids = itertools.count(1)
        self.waiting: dict[int, queue.Queue] = {}

    def send(self, msg: dict):
        try:
            asyncio.run_coroutine_threadsafe(self.ws.send_text(json.dumps(msg)), self.loop).result(10)
        except Exception as e:
            raise Gone(f"{self.name} isn't connected") from e

    def _open(self, op: str, args: dict) -> tuple[int, queue.Queue]:
        rid = next(self.ids)
        q: queue.Queue = queue.Queue()
        self.waiting[rid] = q
        try:
            self.send({"id": rid, "op": op, **args})
        except Gone:
            self.waiting.pop(rid, None)
            raise
        return rid, q

    def _next(self, q: queue.Queue, timeout: float):
        try:
            item = q.get(timeout=timeout)
        except queue.Empty:
            raise Gone(f"{self.name} didn't answer")
        if isinstance(item, Exception):
            raise item
        return item

    def ask(self, op: str, timeout: float = ASK_TIMEOUT, **args):
        """A text answer (its result)."""
        rid, q = self._open(op, args)
        try:
            return self._next(q, timeout)
        finally:
            self.waiting.pop(rid, None)

    def chunks(self, op: str, timeout: float = ASK_TIMEOUT, **args):
        """A binary answer, as it comes."""
        rid, q = self._open(op, args)
        done = False
        try:
            while (chunk := self._next(q, timeout)) is not None:
                yield chunk
            done = True
        finally:
            self.waiting.pop(rid, None)
            if not done:        # nobody wants the rest
                try:
                    self.send({"id": rid, "op": "cancel"})
                except Gone:
                    pass

    def received_text(self, m: dict):
        if (q := self.waiting.get(m.get("id"))) is not None:
            q.put(Refused(str(m["error"])) if "error" in m else m.get("result"))

    def received_bytes(self, data: bytes):
        if len(data) < HEAD.size:
            return
        rid, last = HEAD.unpack_from(data)
        if (q := self.waiting.get(rid)) is not None:
            if len(data) > HEAD.size:
                q.put(data[HEAD.size:])
            if last:
                q.put(None)

    def lost(self):
        for q in list(self.waiting.values()):
            q.put(Gone(f"{self.name} went offline"))


_computers: dict[int, Computer] = {}
_lock = threading.Lock()


def get(peer_id: int) -> Computer:
    with _lock:
        c = _computers.get(peer_id)
    if c is None:
        raise Gone("That computer isn't on right now")
    return c


def connected(peer_id: int) -> bool:
    with _lock:
        return peer_id in _computers


def tell(peer_id: int, state: str):
    """Tell a connected computer how its link stands (from any thread)."""
    with _lock:
        c = _computers.get(peer_id)
    if c is None:
        return
    try:
        c.send({"op": "state", "state": state})
        if state == "removed":
            asyncio.run_coroutine_threadsafe(c.ws.close(code=4403), c.loop)
    except Gone:
        pass


_told: dict[tuple[int, int], float] = {}        # (computer, song) → when it was last told it plays


def playing(peer_id: int, track_id: int):
    """Someone here plays one of a computer's songs (from its connection or the cache here): it's
    told, once a minute per song at most (seeking asks for the song again), so its owner sees it."""
    now = time.monotonic()
    with _lock:
        if now - _told.get((peer_id, track_id), -1e9) < 60:
            return
        if len(_told) > 1000:
            for k in [k for k, at in _told.items() if now - at > 3600]:
                del _told[k]
        _told[(peer_id, track_id)] = now
        c = _computers.get(peer_id)
    if c is not None:       # not waited on: the song doesn't wait for the computer
        asyncio.run_coroutine_threadsafe(c.ws.send_text(json.dumps({"op": "playing", "track": track_id})), c.loop)


# ------------------------------------------------------------ who's away

def refresh_away():
    """Whether any computer's music is hidden now (db.py looks only then)."""
    with db.session() as s:
        db.computers_away = s.scalar(select(Peer.id).where(Peer.away.is_(True)).limit(1)) is not None


def startup():
    """No computer is connected when the server starts."""
    with db.session() as s:
        s.execute(update(Peer).where(Peer.kind == "computer").values(away=True))
    refresh_away()


def _arrived(peer_id: int) -> dict:
    with db.session() as s:
        p = s.get(Peer, peer_id)
        if p is None:
            return {"state": "removed"}
        p.away, p.last_seen = False, datetime.now(timezone.utc)
        linked, name = network.state(p) == "linked", p.name
    refresh_away()
    log.info("%s is connected", name)
    return {"state": "linked" if linked else "waiting", "server": network.name()}


def _left(peer_id: int):
    with db.session() as s:
        p = s.get(Peer, peer_id)
        if p is None:
            return
        p.away, p.last_seen = True, datetime.now(timezone.utc)
        linked, name = network.state(p) == "linked", p.name
    refresh_away()
    if linked:
        jobs.submit("network_away", title=f"Library Network: {name} went offline")
    log.info("%s went offline", name)


def _changed(peer_id: int):
    with db.session() as s:
        p = s.get(Peer, peer_id)
        if p is not None and network.state(p) == "linked":
            network.fetch(p.id, p.name)


@jobs.job("network_away")
def away_job(ctx: jobs.JobContext):
    """A computer went offline: the network's other copies of its albums show instead."""
    from . import mirror      # (it imports this module)
    return mirror.dedupe()


# ------------------------------------------------------------ the connection

async def serve(ws: WebSocket):
    p = network.caller(ws.headers.get("authorization", ""), linked=False)
    if p is None or p.kind != "computer":
        await ws.close(code=4401)
        return
    await ws.accept()
    c = Computer(ws, p.id, p.server_id, p.name, asyncio.get_running_loop())
    with _lock:
        old, _computers[p.id] = _computers.get(p.id), c
    if old is not None:
        old.lost()
        try:
            await old.ws.close(code=4409)       # the same computer again: the new connection is it
        except RuntimeError:
            pass
    loop = asyncio.get_running_loop()
    try:
        hello = await asyncio.to_thread(_arrived, p.id)
        await ws.send_text(json.dumps({"op": "state", **hello}))
        # what changed there while it was away, and its music back in the lists (not awaited:
        # the answers come in below)
        loop.run_in_executor(None, _changed, p.id)
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                c.received_bytes(msg["bytes"])
                continue
            try:
                m = json.loads(msg.get("text") or "")
            except ValueError:
                continue
            if not isinstance(m, dict):
                continue
            if "id" in m:
                c.received_text(m)
            elif m.get("op") == "changed":
                loop.run_in_executor(None, _changed, p.id)
    except WebSocketDisconnect:
        pass
    finally:
        with _lock:
            current = _computers.get(p.id) is c
            if current:
                del _computers[p.id]
        c.lost()
        if current:
            # right here, not in a thread: an await in a task being cancelled (the server stopping,
            # a test client closing) would skip it, and the computer would stay "on"
            _left(p.id)


# ------------------------------------------------------------ what's asked of it

def catalog(peer_id: int, part: str, ctx=None) -> list[dict]:
    """A part of a computer's catalog (as mirror.export makes a server's), page by page."""
    c = get(peer_id)
    out, after = [], 0
    while True:
        if ctx is not None:
            ctx.check()
        try:
            page = c.ask("catalog", timeout=120, part=part, after=after, limit=1000)
        except Refused as e:
            raise Gone(str(e))
        fields = page["fields"]
        out += [dict(zip(fields, row)) for row in page["rows"]]
        if page.get("next") is None:
            return out
        after = page["next"]


def picture(peer_id: int, kind: str, item_id: int) -> bytes:
    return b"".join(get(peer_id).chunks("art", timeout=20, kind=kind, item=item_id))


def lyrics(peer_id: int, track_id: int) -> dict | None:
    try:
        return get(peer_id).ask("lyrics", timeout=10, track=track_id)
    except (Gone, Refused):
        return None


_loading: dict[str, threading.Event] = {}


def file(peer_id: int, sid: str, track_id: int, fmt: str, size: int) -> tuple[str, threading.Event | None]:
    """A song's file from a computer, in the cache here: (its path, an event set once it's all
    there; None when it is). Its .part file grows meanwhile (render.follow reads along)."""
    out = os.path.join(cache_dir(), sid, f"{track_id}-{size}.{fmt}")
    if os.path.exists(out):
        try:
            os.utime(out)       # kept longest when played most recently
        except OSError:
            pass
        return out, None
    get(peer_id)        # Gone now, rather than an empty file later
    with _lock:
        ev = _loading.get(out)
        if ev is None:
            ev = _loading[out] = threading.Event()
            threading.Thread(target=_load, args=(peer_id, track_id, out, ev), daemon=True).start()
    return out, ev


def _load(peer_id: int, track_id: int, out: str, ev: threading.Event):
    part = out + ".part"
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(part, "wb") as f:
            for chunk in get(peer_id).chunks("file", timeout=60, track=track_id):
                f.write(chunk)
                f.flush()
        os.replace(part, out)
    except (Gone, Refused, OSError) as e:
        log.warning("Couldn't get song %s from a computer: %s", track_id, e)
        try:
            os.remove(part)
        except OSError:
            pass
    finally:
        with _lock:
            _loading.pop(out, None)
        ev.set()
    _prune()


def _prune():
    """The cache kept under CACHE_LIMIT, the songs played longest ago going first."""
    files = []
    for d, _, names in os.walk(cache_dir()):
        for n in names:
            if n.endswith(".part"):
                continue
            path = os.path.join(d, n)
            try:
                st = os.stat(path)
            except OSError:
                continue
            files.append((st.st_mtime, st.st_size, path))
    total = sum(f[1] for f in files)
    for _, size, path in sorted(files):
        if total <= CACHE_LIMIT:
            break
        try:
            os.remove(path)
            total -= size
        except OSError:
            pass


def forget_files(sid: str):
    """A computer that left: its songs out of the cache."""
    d = os.path.join(cache_dir(), sid)
    if not os.path.isdir(d):
        return
    for n in os.listdir(d):
        try:
            os.remove(os.path.join(d, n))
        except OSError:
            pass
    try:
        os.rmdir(d)
    except OSError:
        pass


def started(path: str, ev: threading.Event, seconds: float = 20) -> bool:
    """Whether a file on its way here has begun to come (False: it failed, or nothing came)."""
    for _ in range(int(seconds / 0.05)):
        if os.path.exists(path + ".part") or os.path.exists(path):
            return True
        if ev.is_set():
            return os.path.exists(path)
        ev.wait(0.05)
    return False


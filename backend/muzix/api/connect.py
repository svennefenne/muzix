"""Muzix Connect: one account's devices (browser tabs, the Android app) see each other and play on
one another, as with Spotify. Each keeps a WebSocket here. The device that plays tells the others
what it plays, and where; their controls come back to it through here, and choosing another device
moves the music there. Kept in memory only: who's online, which device plays, and what it played
last (so another can carry on with it, even once it's gone).

A device can show a library of its own (the app's: this phone's or this computer's music) instead of the
server's. What it plays is still seen and controlled from the others, but a queue only moves between
devices that show the same library: a song's address means another song in another library. The state
says which library its queue is from ("server", or "local:<device id>").

Messages, as JSON with a "t":
  from a device   hello {id, name, kind, library}   on connecting, and again after a reconnect; library
                                               "local" while it shows its own
                  state {state}                the device that plays: its queue (when it changed),
                                               index, position, playing, ...; playing elsewhere makes
                                               this one the device that plays
                  command {cmd, ...}           for the device that plays (play, pause, next, seek, ...)
                  transfer {to, play, state?}  play on `to` from now on (`state`: what to play, when
                                               nothing played anywhere yet)
                  sync                         back in view: the devices and what plays, again
                  stopped                      the device that plays (as the server has it) started again
                                               with nothing to play: what it played stops where it was
  to a device     devices {devices, active, you, grace}   each with its library; the active device missing from devices
                                               is away: for `grace` seconds it may come back
                  state {state, at?}           what the device that plays plays; on connecting (and sync),
                                               what played last, `at` when it was heard of, for the device
                                               to weigh against what it played itself
                  command {cmd, ...}           to the device that plays
                  takeover {state, play}       play this from here on
                  yield                        another device plays now: stop, and follow it
                  chat {message}               a message in the chat (chat.py) for the account, or one it
                                               sent from another device
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .. import db
from ..security import login_token, session_user

router = APIRouter(tags=["connect"])
log = logging.getLogger("muzix.connect")

GRACE = 45          # seconds the device that plays may be away (a reload, a dropped connection) and still play
KINDS = {"browser", "app"}


@dataclass
class Device:
    id: str
    name: str
    kind: str
    ws: WebSocket
    library: str = "server"          # or "local": the app's own music


def library(dev: Device) -> str:
    """The library a device plays from, as states name it."""
    return f"local:{dev.id}" if dev.library == "local" else "server"


@dataclass
class Account:
    devices: dict[str, Device] = field(default_factory=dict)
    active: str = ""                 # the device that plays
    state: dict | None = None        # what it played last, its queue included
    at: float = 0.0                  # when that came
    away: float = 0.0                # when the device that plays dropped (it's let go after GRACE)


accounts: dict[int, Account] = {}
_loop: asyncio.AbstractEventLoop | None = None      # the one the devices' connections are served on


def tell(uid: int, msg: dict):
    """A word for every device of an account that's online, from anywhere (a request's thread)."""
    acc = accounts.get(uid)
    if acc is None or _loop is None or _loop.is_closed():
        return
    for d in list(acc.devices.values()):
        asyncio.run_coroutine_threadsafe(send(d, msg), _loop)


async def send(dev: Device, msg: dict):
    try:
        await dev.ws.send_text(json.dumps(msg))
    except Exception:       # gone meanwhile: its own loop cleans up
        pass


def settle(acc: Account):
    """The device that plays stayed away: nothing plays any more (what it played is kept, where it got to)."""
    if acc.active and acc.active not in acc.devices and acc.away and time.time() - acc.away > GRACE:
        if acc.state:
            played = acc.away - acc.at if acc.state.get("playing") else 0
            acc.state = {**acc.state, "playing": False, "position": (acc.state.get("position") or 0) + played}
            if played:
                acc.at = acc.away               # where it got to by the time it went
        acc.active, acc.away = "", 0.0


def current(acc: Account) -> dict | None:
    """The last state, with the position carried on to now while it played."""
    settle(acc)
    if not acc.state:
        return None
    st = dict(acc.state)
    if st.get("playing") and acc.active in acc.devices:
        st["position"] = (st.get("position") or 0) + time.time() - acc.at
    return st


async def tell_devices(acc: Account, only: Device | None = None):
    settle(acc)
    listed = [{"id": d.id, "name": d.name, "kind": d.kind, "library": d.library} for d in acc.devices.values()]
    for d in [only] if only else list(acc.devices.values()):
        await send(d, {"t": "devices", "devices": listed, "active": acc.active, "you": d.id, "grace": GRACE})


async def others(acc: Account, but: str, msg: dict):
    for d in list(acc.devices.values()):
        if d.id != but:
            await send(d, msg)


async def on_state(acc: Account, dev: Device, st: dict):
    settle(acc)
    if dev.id != acc.active:
        if not st.get("playing"):
            return              # only what plays counts; a device that follows doesn't tell
        before = acc.devices.get(acc.active)
        acc.active = dev.id
        if before:
            await send(before, {"t": "yield"})
        await tell_devices(acc)
    if "queue" not in st and acc.state:
        st = {**st, "queue": acc.state.get("queue", [])}
    acc.state, acc.at = st, time.time()
    await others(acc, dev.id, {"t": "state", "state": st})


async def on_transfer(acc: Account, dev: Device, m: dict):
    to = acc.devices.get(str(m.get("to") or ""))
    if to is None or to.id == acc.active and acc.active in acc.devices:
        return
    # what plays (or played last) moves; the sender's own queue when nothing else plays
    mine = m.get("state") if acc.active in ("", dev.id) else None
    st = mine or current(acc) or m.get("state")
    if not st or not st.get("queue"):
        return
    if (st.get("library") or "server") != library(to):
        return          # its songs aren't in that device's library
    before = acc.devices.get(acc.active)
    if before and before.id != to.id:
        await send(before, {"t": "yield"})
    acc.active, acc.state, acc.at = to.id, st, time.time()
    await send(to, {"t": "takeover", "state": st, "play": bool(m.get("play", True))})
    await tell_devices(acc)


@router.websocket("/api/connect")
async def connect(ws: WebSocket):
    with db.session() as s:
        user = session_user(s, login_token(ws))
        uid = user.id if user else None
    if uid is None:
        await ws.close(code=4401)
        return
    await ws.accept()
    global _loop
    _loop = asyncio.get_running_loop()
    acc = accounts.setdefault(uid, Account())
    dev: Device | None = None
    try:
        while True:
            try:
                m = json.loads(await ws.receive_text())
            except ValueError:
                continue
            t = m.get("t")
            if t == "hello":
                if dev and acc.devices.get(dev.id) is dev:
                    del acc.devices[dev.id]
                dev = Device(id=str(m.get("id") or "")[:64], name=str(m.get("name") or "A device")[:80],
                             kind=m.get("kind") if m.get("kind") in KINDS else "browser", ws=ws,
                             library="local" if m.get("library") == "local" else "server")
                if not dev.id:
                    break
                old = acc.devices.get(dev.id)
                acc.devices[dev.id] = dev
                if old and old.ws is not ws:
                    await old.ws.close()        # the same device again (a reload): the new connection is it
                if acc.active == dev.id:
                    acc.away = 0.0              # back in time
                await tell_devices(acc)
                if acc.state and acc.active != dev.id:
                    await send(dev, {"t": "state", "state": current(acc), "at": acc.at})
            elif dev is None:
                continue
            elif t == "sync":
                await tell_devices(acc, dev)
                if acc.state and acc.active != dev.id:
                    await send(dev, {"t": "state", "state": current(acc), "at": acc.at})
            elif t == "stopped":
                if acc.active == dev.id and acc.state and acc.state.get("playing"):
                    acc.state, acc.at = {**acc.state, "playing": False, "buffering": False}, time.time()
                    await others(acc, dev.id, {"t": "state", "state": acc.state})
            elif t == "state" and isinstance(m.get("state"), dict):
                await on_state(acc, dev, m["state"])
            elif t == "command" and acc.active != dev.id:
                target = acc.devices.get(acc.active)
                if target:
                    await send(target, {**m, "from": dev.id})
            elif t == "transfer":
                await on_transfer(acc, dev, m)
    except WebSocketDisconnect:
        pass
    finally:
        if dev and acc.devices.get(dev.id) is dev:
            del acc.devices[dev.id]
            if acc.active == dev.id:
                acc.away = time.time()
            await tell_devices(acc)

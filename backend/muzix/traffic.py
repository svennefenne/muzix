"""What Muzix sends out, counted: each answer's bytes as they go, by day, by device and by kind, for the admin's
Data page (api/admin.py). The counts gather in memory and go into the database (the traffic table) once a
minute and whenever the page asks."""

import atexit
import logging
import threading
import time
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from . import db
from .asking import Asker, current
from .models import Traffic, User

log = logging.getLogger(__name__)
KINDS = ("music", "audiobooks", "podcasts", "radio", "pictures", "other")
SHARES = "Share links"

_lock = threading.Lock()
_pending: dict[tuple[str, int, str, str], int] = defaultdict(int)    # (day, user, device, kind): bytes not yet saved
_started = False


def kind_of(path: str, ctype: str) -> str:
    """What an answer is, from its path and type."""
    ctype = ctype.lower()
    if ctype.startswith(("audio/", "video/", "application/ogg")) or (ctype.startswith("application/octet-stream")
                                                                       and "/stream" in path):
        if path.startswith("/api/radio/"):
            return "radio"
        if "/books/" in path:
            return "audiobooks"
        if path.startswith("/api/podcasts/") or "/episode/" in path:
            return "podcasts"
        return "music"
    if ctype.startswith("image/"):
        return "pictures"
    return "other"


def add(user_id: int, device: str, kind: str, n: int, day: str | None = None):
    with _lock:
        _pending[(day or date.today().isoformat(), user_id, device, kind)] += n


class Counted:
    """ASGI middleware, the outermost: who asks (asking.py) and the bytes of the answer as they go out. A song
    counts as it streams, so today's figure grows while it plays."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        a = Asker(scope.get("method", ""), scope.get("path", ""))
        token = current.set(a)
        to: tuple[int, str, str] | None = None

        async def counting(message):
            nonlocal to
            if message["type"] == "http.response.start":
                ctype = next((v for k, v in message.get("headers", []) if k.lower() == b"content-type"), b"")
                device = a.device or (SHARES if a.path.startswith("/api/s/") else "")
                to = (a.user_id, device, kind_of(a.path, ctype.decode("latin-1")))
            elif message["type"] == "http.response.body" and to is not None and (body := message.get("body")):
                add(*to, len(body))
            await send(message)

        try:
            await self.app(scope, receive, counting)
        finally:
            current.reset(token)


def flush():
    """Into the database: what was counted since the last time."""
    with _lock:
        rows = [{"day": d, "user_id": u, "device": dev, "kind": k, "bytes": n} for (d, u, dev, k), n in _pending.items()]
        _pending.clear()
    if not rows:
        return
    stmt = insert(Traffic).values(rows)
    stmt = stmt.on_conflict_do_update(index_elements=["day", "user_id", "device", "kind"],
                                      set_={"bytes": Traffic.bytes + stmt.excluded.bytes})
    try:
        with db.session() as s:
            s.execute(stmt)
    except Exception:
        log.exception("couldn't save the traffic counts")
        with _lock:                 # kept for the next try
            for r in rows:
                _pending[(r["day"], r["user_id"], r["device"], r["kind"])] += r["bytes"]


def start():
    """Saves the counts once a minute, and as Muzix stops."""
    global _started
    if _started:
        return
    _started = True

    def loop():
        while True:
            time.sleep(60)
            flush()
    threading.Thread(target=loop, name="traffic", daemon=True).start()
    atexit.register(flush)


# ---------------------------------------------------------------- what the Data page shows

def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _month(d: date, back: int = 0) -> date:
    m = d.year * 12 + d.month - 1 - back
    return date(m // 12, m % 12 + 1, 1)


def _periods(by: str, today: date) -> list[tuple[date, date]]:
    """The last 14 days, 12 weeks (from Monday) or 12 months, the one going on last."""
    if by == "week":
        w = _monday(today)
        return [(w - timedelta(weeks=k), w - timedelta(weeks=k) + timedelta(days=6)) for k in range(11, -1, -1)]
    if by == "month":
        return [(_month(today, k), _month(today, k - 1) - timedelta(days=1)) for k in range(11, -1, -1)]
    return [(today - timedelta(days=k), today - timedelta(days=k)) for k in range(13, -1, -1)]


def _total(per_day: dict[str, dict[str, int]], start: date, end: date) -> dict:
    kinds = dict.fromkeys(KINDS, 0)
    for day, by_kind in per_day.items():
        if start.isoformat() <= day <= end.isoformat():
            for k, n in by_kind.items():
                kinds[k if k in kinds else "other"] += n
    return {"start": start.isoformat(), "end": end.isoformat(), "bytes": sum(kinds.values()), "kinds": kinds}


def summary(by: str = "day", today: date | None = None) -> dict:
    """Today so far, yesterday, this and last week, this and last month; and the periods `by` lays out."""
    flush()
    today = today or date.today()
    periods = _periods(by, today)
    first = min(periods[0][0], _month(today, 1), _monday(today) - timedelta(weeks=1))
    per_day: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    with db.session() as s:
        for day, kind, n in s.execute(select(Traffic.day, Traffic.kind, Traffic.bytes).where(Traffic.day >= first.isoformat())):
            per_day[day][kind] += n
    week, month = _monday(today), _month(today)
    now = [("today", "Today so far", today, today), ("yesterday", "Yesterday", today - timedelta(days=1), today - timedelta(days=1)),
           ("week", "This week", week, today), ("last_week", "Last week", week - timedelta(weeks=1), week - timedelta(days=1)),
           ("month", "This month", month, today), ("last_month", "Last month", _month(today, 1), month - timedelta(days=1))]
    return {"now": [{"key": key, "label": label, **_total(per_day, a, z)} for key, label, a, z in now],
            "periods": [_total(per_day, a, z) for a, z in periods], "by": by, "kinds": list(KINDS)}


def devices(start: date, end: date) -> list[dict]:
    """Who it went to between two days (both included), the most first."""
    flush()
    got: dict[tuple[int, str], dict[str, int]] = defaultdict(lambda: dict.fromkeys(KINDS, 0))
    with db.session() as s:
        for uid, device, kind, n in s.execute(select(Traffic.user_id, Traffic.device, Traffic.kind, Traffic.bytes)
                                              .where(Traffic.day >= start.isoformat(), Traffic.day <= end.isoformat())):
            got[(uid, device)][kind if kind in KINDS else "other"] += n
        names = dict(s.execute(select(User.id, User.username).where(User.id.in_({uid for uid, _ in got}))).all())
    out = [{"user": names.get(uid, "a removed account") if uid else "", "device": device, "bytes": sum(kinds.values()),
            "kinds": kinds} for (uid, device), kinds in got.items()]
    return sorted(out, key=lambda r: -r["bytes"])

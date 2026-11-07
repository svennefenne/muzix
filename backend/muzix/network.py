"""The Library Network: Muzix servers that share their libraries with each other.

Linking takes both admins. Each server has a sharing code (XXXXX-XXXXX-XXXXX-XXXXX, made here).
An admin enters another server's address and that server's code; this server hands the code
over and the other one checks it, which leaves a request there. It's a link once the other
admin has entered this server's code the same way. Every such exchange also trades keys, and
from then on the servers call each other with those (Authorization: Bearer), never the codes.

The code only opens the door to new links: a new one leaves the links there are, and without
one (the network turned off) nobody can ask for a link.
"""

import hashlib
import hmac
import ipaddress
import logging
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select

from . import db, enrich, jobs, settings
from .models import Peer, Setting
from .serial import iso

log = logging.getLogger(__name__)

PROTOCOL = 1
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"    # no 0/O or 1/I/L to mix up
GROUPS, GROUP = 4, 5
TRIES, TRIES_WINDOW = 10, 600                  # wrong codes from one address before it has to wait


class NetworkError(Exception):
    """Something to tell our admin, as it is."""


class Refused(Exception):
    """Another server's request turned down: the status and why, for it to tell its admin."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------ this server

def _stored(key: str, make=None):
    with db.session() as s:
        row = s.get(Setting, key)
        if row is None and make is not None:
            row = Setting(key=key, value=make())
            s.add(row)
        return row.value if row is not None else None


def server_id() -> str:
    return _stored("network_id", lambda: uuid.uuid4().hex)


def name() -> str:
    return settings.get("site_name") or "Muzix"


def code() -> str | None:
    """The sharing code; None while the network is off."""
    return _stored("network_code")


def new_code() -> str:
    c = "-".join("".join(secrets.choice(ALPHABET) for _ in range(GROUP)) for _ in range(GROUPS))
    with db.session() as s:
        s.merge(Setting(key="network_code", value=c))
    return c


def main() -> str | None:
    """The main library's server id: its copy of an album shows when others have it too (None:
    this server's)."""
    return _stored("network_main")


def set_main(sid: str | None):
    with db.session() as s:
        if sid is None or sid == server_id():
            row = s.get(Setting, "network_main")
            if row is not None:
                s.delete(row)
        else:
            s.merge(Setting(key="network_main", value=sid))


def turn_off():
    """No new links (the ones there are stay)."""
    with db.session() as s:
        row = s.get(Setting, "network_code")
        if row is not None:
            s.delete(row)


def clean_code(text: str) -> str:
    """A code as typed: with or without dashes and brackets, in any case."""
    return "".join(ch for ch in (text or "").upper() if ch.isalnum())


def _matches(typed: str) -> bool:
    mine = code()
    return bool(mine) and hmac.compare_digest(clean_code(typed).encode(), clean_code(mine).encode())


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def clean_address(text: str) -> str:
    """A server's address as typed: an IP and port, a host name or a whole URL. Without a scheme,
    an IP address or a port means plain http (a server at home), a name https."""
    t = (text or "").strip().rstrip("/")
    if not t:
        raise NetworkError("Enter the other server's address")
    if "://" not in t:
        host = t.split("/", 1)[0]
        bare = host.rsplit(":", 1)[0] if host.count(":") == 1 else host     # an IPv6 address has more
        home = ":" in host or bare == "localhost" or _is_ip(bare)
        t = ("http://" if home else "https://") + t
    u = urlsplit(t)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise NetworkError(f"{text.strip()} isn't a server address")
    return f"{u.scheme}://{u.netloc}{u.path.rstrip('/')}"


def state(p: Peer) -> str:
    """linked; waiting (for its admin to enter our code); asked (its admin entered ours)."""
    return "linked" if p.sent and p.received else "waiting" if p.sent else "asked"


def peer_json(p: Peer) -> dict:
    return {
        "id": p.id, "name": p.name, "address": p.address, "state": state(p),
        "linked_at": iso(p.linked_at), "last_seen": iso(p.last_seen), "created_at": iso(p.created_at),
        "synced_at": iso(p.synced_at), "counts": p.counts or {}, "error": p.error,
    }


def linked() -> list[int]:
    with db.session() as s:
        return list(s.scalars(select(Peer.id).where(Peer.sent.is_(True), Peer.received.is_(True))))


# ------------------------------------------------------------ calling another server

def _client(follow: bool = False) -> httpx.Client:
    return httpx.Client(headers={"User-Agent": enrich.UA}, timeout=15, follow_redirects=follow)


def _why(e: Exception) -> str:
    return str(e) or e.__class__.__name__


def _detail(r: httpx.Response) -> str:
    try:
        d = r.json().get("detail")
        if isinstance(d, str):
            return d
    except (ValueError, AttributeError):
        pass
    return f"HTTP {r.status_code}"


def hello(address: str) -> tuple[str, dict]:
    """Whether a Muzix server answers at `address`: where it really is (after redirects, say to
    https) and what it says about itself."""
    try:
        with _client(follow=True) as c:
            r = c.get(address + "/api/network/hello")
    except httpx.HTTPError as e:
        raise NetworkError(f"Couldn't reach {address} ({_why(e)})")
    try:
        info = r.json() if r.status_code == 200 else None
    except ValueError:
        info = None
    if not isinstance(info, dict) or not info.get("server_id"):
        raise NetworkError(f"{address} doesn't answer as a Muzix server with the Library Network"
                           + ("" if r.status_code == 200 else f" (HTTP {r.status_code})"))
    who = info.get("name") or address
    if info.get("protocol") != PROTOCOL:
        raise NetworkError(f"{who} links another way (protocol {info.get('protocol')}, here {PROTOCOL}): "
                           "update both servers to the same Muzix")
    if not info.get("open"):
        raise NetworkError(f"{who} has the Library Network turned off")
    return str(r.url)[: -len("/api/network/hello")], info


def link(address: str, typed: str, own_address: str) -> dict:
    """Our admin entered another server's address and code: hand the code over. A link at once if
    its admin has entered ours already; otherwise it's a request there."""
    if len(clean_code(typed)) != GROUPS * GROUP:
        raise NetworkError("A sharing code is 20 letters and digits: XXXXX-XXXXX-XXXXX-XXXXX")
    if not code():
        raise NetworkError("Turn the Library Network on first: the other server needs this one's code too")
    base, info = hello(clean_address(address))
    sid, who = str(info["server_id"]), info.get("name") or base
    if sid == server_id():
        raise NetworkError("That's this server")
    key = secrets.token_urlsafe(32)
    body = {"protocol": PROTOCOL, "code": clean_code(typed), "server_id": server_id(), "name": name(),
            "address": own_address, "key": key}
    try:
        with _client() as c:
            r = c.post(base + "/api/network/link", json=body)
    except httpx.HTTPError as e:
        raise NetworkError(f"Couldn't reach {who} ({_why(e)})")
    if r.status_code == 403:
        raise NetworkError(f"{who} says that isn't its sharing code")
    if r.status_code == 429:
        raise NetworkError(f"{who} has had too many wrong codes from here: try again in a few minutes")
    if r.status_code != 200:
        raise NetworkError(f"{who} couldn't link ({_detail(r)})")
    try:
        got = r.json()
        theirs = str(got["key"])
        if got["server_id"] != sid or len(theirs) < 32:
            raise ValueError
    except (ValueError, KeyError, TypeError, AttributeError):
        raise NetworkError(f"{who} answered something unexpected")
    with db.session() as s:
        p = s.scalar(select(Peer).where(Peer.server_id == sid))
        if p is None:
            p = Peer(server_id=sid)
            s.add(p)
        p.name = str(got.get("name") or who)[:255]
        p.address = base
        p.key = theirs
        p.their_key = _hash(key)
        p.sent = True
        # its admin entered our code before (and we may have lost that): our admin's link is the yes
        p.received = p.received or bool(got.get("linked"))
        p.error = ""
        p.last_seen = datetime.now(timezone.utc)
        if p.received and p.linked_at is None:
            p.linked_at = p.last_seen
        s.flush()
        out = peer_json(p)
    if out["state"] == "linked":
        fetch(out["id"], out["name"])
    return out


def fetch(peer_id: int, who: str):
    """A linked server's library, mirrored here (mirror.py) in the background."""
    jobs.submit("network_sync", title=f"Library Network: {who}", peer_id=peer_id)


def drop(sid: str, who: str):
    """What was mirrored of a server that left the network goes, in the background."""
    jobs.submit("network_drop", title=f"Library Network: {who} left", server_id=sid)


def unlink(peer_id: int):
    """Our admin ended a link (or turned down a request): gone here, and the other server is told."""
    with db.session() as s:
        p = s.get(Peer, peer_id)
        if p is None:
            raise NetworkError("There's no such server in the network")
        address, key, who, sid = p.address, p.key, p.name, p.server_id
        s.delete(p)
    drop(sid, who)
    if not (address and key):
        return
    try:
        with _client() as c:
            c.post(address + "/api/network/unlink", headers={"Authorization": f"Bearer {key}"})
    except httpx.HTTPError as e:
        log.warning("Couldn't tell %s the link has ended: %s", who, _why(e))


# ------------------------------------------------------------ another server calling

_tries: dict[str, deque] = defaultdict(deque)
_tries_lock = threading.Lock()


def _too_many(ip: str) -> bool:
    with _tries_lock:
        q = _tries[ip]
        while q and q[0] < time.time() - TRIES_WINDOW:
            q.popleft()
        return len(q) >= TRIES


def _wrong(ip: str):
    with _tries_lock:
        _tries[ip].append(time.time())


def receive(body: dict, ip: str) -> dict:
    """Another server hands over our code: its admin wants to link. A link if ours had entered its
    code already; a request otherwise. Its key is kept, and one made for it is the answer."""
    if body.get("protocol") != PROTOCOL:
        raise Refused(400, f"This server links with protocol {PROTOCOL}: update both servers to the same Muzix")
    if _too_many(ip):
        raise Refused(429, "Too many wrong sharing codes: try again in a few minutes")
    if not _matches(body.get("code", "")):
        _wrong(ip)
        raise Refused(403, "That isn't this server's sharing code")
    sid = str(body["server_id"])
    if sid == server_id():
        raise Refused(400, "That's this server")
    key = secrets.token_urlsafe(32)
    with db.session() as s:
        p = s.scalar(select(Peer).where(Peer.server_id == sid))
        if p is None:
            p = Peer(server_id=sid)
            s.add(p)
        p.name = str(body.get("name") or "")[:255] or p.name or "Muzix"
        if not p.address:           # what it says; our admin's own entry wins
            try:
                p.address = clean_address(body.get("address") or "")
            except NetworkError:
                pass
        p.key = str(body["key"])
        p.their_key = _hash(key)
        p.received = True
        p.last_seen = datetime.now(timezone.utc)
        if p.sent and p.linked_at is None:
            p.linked_at = p.last_seen
        linked, peer_id, who = p.sent, p.id, p.name
    log.info("%s %s", who, "linked" if linked else "asks to link")
    if linked:
        fetch(peer_id, who)
    return {"server_id": server_id(), "name": name(), "key": key, "linked": linked}


def caller(authorization: str, linked: bool = True) -> Peer | None:
    """The server calling with this key (Authorization: Bearer); only a linked one, unless `linked`
    is False."""
    scheme, _, key = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or len(key) < 32:
        return None
    with db.session() as s:
        p = s.scalar(select(Peer).where(Peer.their_key == _hash(key)))
        if p is None or (linked and state(p) != "linked"):
            return None
        s.expunge(p)
    return p


def forget(authorization: str) -> bool:
    """The other server ended the link (or took back its request)."""
    p = caller(authorization, linked=False)
    if p is None:
        return False
    with db.session() as s:
        row = s.get(Peer, p.id)
        if row is not None:
            s.delete(row)
    log.info("%s ended the link", p.name)
    drop(p.server_id, p.name)
    return True

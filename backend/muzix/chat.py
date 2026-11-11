"""The Library Network's chat: private messages between two people, on this server or on a server
it's linked with (network.py). Each server keeps what its own people wrote and got, so a
conversation is on both servers; where a message was written (its origin, a server id) and its id
there make it the same message on both.

A message for someone on another server is handed over at once (POST /api/network/chat). One that
doesn't get there waits on this server: each server asks the ones it's linked with for what's
waiting for its people (GET /api/network/chat) on starting and every few minutes, from where it
got to the last time (Peer.chat_after). Messages only go between servers that are linked with each
other: nothing is passed on to a third.

Anyone on this server or a linked one can be written to, unless they left themselves out of the
chat (their "chat_hidden" setting); they can still write, and whoever they wrote to can answer.

A message can link albums and songs. The writer's server puts down what they are (snapshot()):
the server whose own library has it and its id there, its title, artist, cover and songs. The
reader's server finds it in its own library if it's there (its own, or mirrored from that server),
and otherwise plays it from that server through itself (resolve()), if it's linked with it.
"""

import hashlib
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import art, db, env, mirror, modules, network
from .models import Album, ChatMessage, Peer, Track, User
from .serial import iso

log = logging.getLogger(__name__)

TEXT_MAX = 4000
LINKS_MAX = 5
TRACKS_MAX = 400
PAGE = 100
WAITING_PAGE = 500
EVERY = 300             # seconds between asking the linked servers for what's waiting here
PEOPLE_FOR = 60         # seconds a linked server's list of people is kept
KINDS = ("album", "track")
PICTURE = re.compile(r"^[0-9a-f]{24}\.webp$")    # an icon's picture, named by its contents (api/me.py)
PICTURE_MAX = 2 * 1024 * 1024


class ChatError(Exception):
    """Something to tell whoever wrote (or the server that handed it over), with a status."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hidden(u: User) -> bool:
    return bool((u.prefs or {}).get("chat_hidden"))


def _linked(s: Session) -> list[Peer]:
    """The servers this one is linked with (computers have nobody to chat with)."""
    return [p for p in s.scalars(select(Peer).where(Peer.kind == "server").order_by(Peer.id))
            if network.state(p) == "linked"]


def _peer(s: Session, sid: str) -> Peer | None:
    p = s.scalar(select(Peer).where(Peer.server_id == sid, Peer.kind == "server"))
    return p if p is not None and network.state(p) == "linked" else None


def _wrote(s: Session, origin: str, uid: int, to_server: str, to_user: int) -> bool:
    """Whether someone (uid on origin) has written to someone else."""
    return s.scalar(select(ChatMessage.id).where(
        ChatMessage.origin == origin, ChatMessage.from_user == uid,
        ChatMessage.to_server == to_server, ChatMessage.to_user == to_user).limit(1)) is not None


def of_user(uid: int):
    """The messages someone here wrote or got."""
    here = network.server_id()
    return or_(and_(ChatMessage.origin == here, ChatMessage.from_user == uid),
               and_(ChatMessage.to_server == here, ChatMessage.to_user == uid))


def _between(uid: int, sid: str, other: int):
    here = network.server_id()
    return or_(and_(ChatMessage.origin == here, ChatMessage.from_user == uid,
                    ChatMessage.to_server == sid, ChatMessage.to_user == other),
               and_(ChatMessage.origin == sid, ChatMessage.from_user == other,
                    ChatMessage.to_server == here, ChatMessage.to_user == uid))


def _sent(m: ChatMessage, uid: int) -> bool:
    return m.origin == network.server_id() and m.from_user == uid


def _other(m: ChatMessage, uid: int) -> dict:
    """Who a message is with, for someone here who wrote or got it."""
    if _sent(m, uid):
        return person(m.to_server, m.to_user, m.to_name, m.to_place)
    return person(m.origin, m.from_user, m.from_name, m.from_place)


def person(sid: str, uid: int, name: str, place: str) -> dict:
    return {"server": sid, "user": uid, "name": name, "place": place, "here": sid == network.server_id()}


# ------------------------------------------------------------ icons
# Each account's own (api/me.py). Another server's people's come with its list of people and with
# their messages, and are kept here in memory until the next of either; their pictures are fetched
# through this server once and kept (their names are their contents, so they never go stale).

_looks: dict[tuple[str, int], dict] = {}


def own_look(u) -> dict:
    """An account's icon as it goes to another server: its picture's name, or a letter on a colour."""
    a = getattr(u, "avatar", None) or {}
    return {"picture": a.get("picture"), "letter": a.get("letter"), "color": a.get("color")}


def clean_look(d) -> dict | None:
    """An icon as another server said it, made safe to show; None if it's none."""
    if not isinstance(d, dict):
        return None
    pic, letter, color = d.get("picture"), d.get("letter"), d.get("color")
    return {"picture": pic if isinstance(pic, str) and PICTURE.match(pic) else None,
            "letter": letter.strip()[:8] or None if isinstance(letter, str) else None,
            "color": color.lower() if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color) else None}


def _shown(sid: str, look: dict | None, name: str) -> dict:
    """An icon as the pages show it (components/Avatar.tsx): another server's picture through this one."""
    look = look or {}
    if look.get("picture"):
        here = sid == network.server_id()
        return {"picture": f"/api/avatars/{look['picture']}" if here else f"/api/chat/avatars/{sid}/{look['picture']}",
                "letter": None, "color": None}
    return {"picture": None, "letter": look.get("letter") or (name or "?")[:1].upper(), "color": look.get("color")}


def dressed(p: dict) -> dict:
    """A person with their icon."""
    if p["here"]:
        with db.session() as s:
            u = s.get(User, p["user"])
            look = own_look(u) if u is not None else None
    else:
        look = _looks.get((p["server"], p["user"]))
    return {**p, "avatar": _shown(p["server"], look, p["name"])}


def picture(sid: str, name: str) -> str | None:
    """The file of another server's person's icon picture, fetched once and kept."""
    if not PICTURE.match(name):
        return None
    path = env.CACHE_DIR / "avatars" / name
    if path.is_file():
        return str(path)
    with db.session() as s:
        p = _peer(s, sid)
        if p is None:
            return None
        address, key = p.address, p.key
    try:
        with network._client() as c:
            r = c.get(f"{address}/api/network/avatars/{name}", headers={"Authorization": f"Bearer {key}"}, timeout=10)
    except httpx.HTTPError:
        return None
    data = r.content if r.status_code == 200 else b""
    # its name is its contents: anything else isn't that picture
    if not data or len(data) > PICTURE_MAX or hashlib.sha256(data).hexdigest()[:24] != name[:24]:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return str(path)


def own_picture(name: str) -> str | None:
    """One of this server's accounts' icon pictures, for a linked server's people to see."""
    path = env.AVATAR_DIR / name
    if not PICTURE.match(name) or not path.is_file():
        return None
    with db.session() as s:
        used = any((a or {}).get("picture") == name for a in s.scalars(select(User.avatar)))
    return str(path) if used else None


# ------------------------------------------------------------ who can be written to

_people: dict[str, tuple[float, list[dict]]] = {}
_people_lock = threading.Lock()


def visible(s: Session) -> list[dict]:
    """This server's people in the chat, as linked servers see them."""
    return [{"id": u.id, "name": u.username, "avatar": own_look(u)} for u in s.scalars(select(User).order_by(User.username))
            if not _hidden(u)]


def _theirs(sid: str, address: str, key: str, place: str) -> list[dict]:
    with _people_lock:
        at, rows = _people.get(sid, (0.0, []))
    if time.time() - at > PEOPLE_FOR:
        try:
            with network._client() as c:
                r = c.get(address + "/api/network/chat/people", headers={"Authorization": f"Bearer {key}"}, timeout=6)
            got = r.json() if r.status_code == 200 else []
            rows = [{"id": int(p["id"]), "name": str(p["name"])[:64], "avatar": clean_look(p.get("avatar"))}
                    for p in got if isinstance(p, dict)]
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            rows = []           # not up, or a Muzix without the chat: nobody there for now
        with _people_lock:
            _people[sid] = (time.time(), rows)
            _looks.update({(sid, p["id"]): p["avatar"] for p in rows if p["avatar"]})
    return [{**person(sid, p["id"], p["name"], place), "avatar": _shown(sid, p["avatar"], p["name"])} for p in rows]


def people(user: User) -> list[dict]:
    """Everyone the user can write to: here, and on the linked servers."""
    here = network.server_id()
    with db.session() as s:
        out = [{**person(here, p["id"], p["name"], network.name()), "avatar": _shown(here, p["avatar"], p["name"])}
               for p in visible(s) if p["id"] != user.id]
        linked = [(p.server_id, p.address, p.key, p.name) for p in _linked(s)]
    if linked:
        with ThreadPoolExecutor(max_workers=min(len(linked), 8)) as pool:
            for rows in pool.map(lambda a: _theirs(*a), linked):
                out += rows
    return out


# ------------------------------------------------------------ links

def _origin(row, kind: str) -> tuple[str, int]:
    """The server whose own library has an album or song, and its id there."""
    if row.peer_id is None:
        return network.server_id(), row.id
    sid, _, rid, _ = mirror.where(row.folder if kind == "album" else row.path)
    return sid, rid


def _cover(a: Album) -> int:
    """The album cover's version where the album is (0: it has none)."""
    if not a.art:
        return 0
    if a.peer_id is None:
        return art.version("album", a.id)
    try:
        return int(mirror.where(a.art)[3] or 1)
    except ValueError:
        return 1


def _place(s: Session, sid: str) -> str:
    if sid == network.server_id():
        return network.name()
    return s.scalar(select(Peer.name).where(Peer.server_id == sid)) or ""


def snapshot(view: Session, kind: str, id_: int) -> dict:
    """What an album or song the writer sees is, as a link carries it."""
    if kind == "track":
        t = view.scalar(select(Track).where(Track.id == id_))
        if t is None:
            raise ChatError(404, "That song isn't in your library")
        album = view.scalar(select(Album).where(Album.id == t.album_id)) if t.album_id else None
    elif kind == "album":
        t, album = None, view.scalar(select(Album).where(Album.id == id_))
        if album is None:
            raise ChatError(404, "That album isn't in your library")
    else:
        raise ChatError(400, "Only albums and songs can be linked")
    out: dict = {"kind": kind, "album": None, "art": 0}
    if album is not None:
        sid, rid = _origin(album, "album")
        out.update(server=sid, id=rid, title=album.title, artist=album.artist_name, year=album.year,
                   album={"id": rid, "title": album.title}, art=_cover(album))
        songs = list(view.scalars(select(Track).where(Track.album_id == album.id)
                                  .order_by(Track.disc_no, Track.track_no, Track.id).limit(TRACKS_MAX)))
    else:
        songs = [t]
    if t is not None:
        sid, rid = _origin(t, "track")
        out.update(server=sid, id=rid, title=t.title, artist=t.artist or t.albumartist, year=t.year or out.get("year"))
    out["tracks"] = [{"id": _origin(x, "track")[1], "title": x.title, "artist": x.artist or x.albumartist,
                      "duration": round(x.duration or 0, 1), "disc": x.disc_no or 0, "no": x.track_no or 0}
                     for x in songs]
    out["place"] = _place(view, out["server"])
    return out


def _text(v, n: int) -> str:
    return v[:n] if isinstance(v, str) else ""


def _int(v) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError
    return int(v)


def clean_link(d) -> dict | None:
    """A link as another server sent it, made safe to keep: what's expected, cut to size; None if
    it's no link."""
    try:
        if not isinstance(d, dict) or d.get("kind") not in KINDS:
            return None
        album = d.get("album")
        tracks = d.get("tracks") if isinstance(d.get("tracks"), list) else []
        year = d.get("year")
        return {
            "kind": d["kind"], "server": _text(d.get("server"), 64), "id": _int(d.get("id")),
            "title": _text(d.get("title"), 500), "artist": _text(d.get("artist"), 500),
            "year": _int(year) if year else None,
            "album": {"id": _int(album["id"]), "title": _text(album.get("title"), 500)} if isinstance(album, dict) else None,
            "art": max(0, _int(d.get("art") or 0)),
            "tracks": [{"id": _int(x["id"]), "title": _text(x.get("title"), 500), "artist": _text(x.get("artist"), 500),
                        "duration": max(0.0, float(x.get("duration") or 0)), "disc": _int(x.get("disc") or 0),
                        "no": _int(x.get("no") or 0)}
                       for x in tracks[:TRACKS_MAX] if isinstance(x, dict)],
            "place": _text(d.get("place"), 255),
        }
    except (ValueError, KeyError, TypeError):
        return None


def _limited(view: Session) -> bool:
    """Whether the admin left music out for the reader (limits.py): they get a link only as this
    server has it for them, never from elsewhere, where its artist's genres can't be checked."""
    return getattr(view.info.get("viewer"), "limits", None) is not None


def _elsewhere_ok(view: Session, sid: str) -> bool:
    """Whether what the reader can't see here may still come to them from the server it's on.
    Something here the reader can't see (an admin hid it, say) they don't get from elsewhere
    either; but one who left the network's music out of their library can still hear a link."""
    return sid != network.server_id() and getattr(view.info.get("viewer"), "network", True) is False and not _limited(view)


def _here(view: Session, sid: str, kind: str, ids: list[int]) -> tuple[dict[int, int], set[int]]:
    """Of albums or songs on server `sid` (their ids there), the ones this server has ({id there:
    id here}), and of those the ids the reader sees."""
    model = Album if kind == "album" else Track
    with db.session() as s:
        if sid == network.server_id():
            have = {i: i for i in s.scalars(select(model.id).where(model.id.in_(ids), model.peer_id.is_(None)))}
        else:       # mirrored from it: peer:<sid>/albums/<id> (the album's folder) or peer:<sid>/tracks/<id>
            ref = model.folder if model is Album else model.path
            refs = {f"{mirror.ROOT}{sid}/{kind}s/{i}": i for i in ids}
            have = {refs[r]: i for i, r in s.execute(select(model.id, ref).where(ref.in_(list(refs))))}
    seen = set(view.scalars(select(model.id).where(model.id.in_(list(have.values()))))) if have else set()
    return have, seen


def _found(view: Session, sid: str, kind: str, id_: int) -> tuple[int | None, bool]:
    """An album's or song's id here, if the reader sees it here; and whether they may have it at all."""
    have, seen = _here(view, sid, kind, [id_])
    row = have.get(id_)
    if row is None:
        return None, True
    if row in seen:
        return row, True
    return None, _elsewhere_ok(view, sid)


def resolve(view: Session, link: dict, tracks: bool = False) -> dict:
    """A link as the reader's page gets it: the album and song here (`here_album`, `here_track`),
    whether it plays (`reach`: "here", "network" from the server it's on through this one, "away"),
    its cover's address and that server's name; with `tracks`, its songs with where each plays."""
    sid = link["server"]
    album_id = (link.get("album") or {}).get("id")
    here_album, ok_album = _found(view, sid, "album", album_id) if album_id else (None, True)
    here_track, ok_track = _found(view, sid, "track", link["id"]) if link["kind"] == "track" else (None, True)
    mine = sid == network.server_id()
    with db.session() as s:
        peer = None if mine else _peer(s, sid)
        place = network.name() if mine else (peer.name if peer else link.get("place") or "")
        cover_here = here_album and s.scalar(select(Album.art).where(Album.id == here_album))
    allowed = ok_album and ok_track
    through = peer is not None and allowed and not _limited(view)
    here = here_track if link["kind"] == "track" else here_album
    reach = "here" if here else "network" if through else "away"
    if here_album and cover_here:
        cover = art.url("album", here_album)
    elif through and album_id and link.get("art"):
        cover = f"/api/art/network/{sid}/album/{album_id}?v={link['art']}"
    else:
        cover = None
    out = {k: link.get(k) for k in ("kind", "server", "id", "title", "artist", "year", "album")}
    out.update(place=place, elsewhere=not mine, reach=reach, cover=cover, here_album=here_album, here_track=here_track,
               songs=len(link.get("tracks") or []), length=round(sum(x.get("duration") or 0 for x in link.get("tracks") or [])))
    if tracks:
        out["tracks"] = _songs(view, sid, link.get("tracks") or [], through) if allowed else \
            [{**x, "local": None, "stream": None} for x in link.get("tracks") or []]
    return out


def _songs(view: Session, sid: str, songs: list[dict], through: bool) -> list[dict]:
    """A link's songs, each with its id here (`local`, if the reader has it here) and where it
    streams from (None: nowhere for the reader)."""
    have, seen = _here(view, sid, "track", [x["id"] for x in songs])
    elsewhere = through and _elsewhere_ok(view, sid)
    out = []
    for x in songs:
        row = have.get(x["id"])
        if row is not None and row in seen:
            local, stream = row, f"/api/stream/{row}"
        elif through and (row is None or elsewhere):
            local, stream = None, f"/api/chat/stream/{sid}/{x['id']}"
        else:
            local, stream = None, None
        out.append({**x, "local": local, "stream": stream})
    return out


# ------------------------------------------------------------ messages

def _wire(m: ChatMessage, look: dict | None = None) -> dict:
    """A message as it goes to the other server, with its writer's icon."""
    return {"id": m.origin_id, "from_user": m.from_user, "from_name": m.from_name, "to_user": m.to_user,
            "text": m.text, "links": m.links or [], "sent_at": iso(m.sent_at), "from_avatar": look}


def message_json(m: ChatMessage, uid: int, view: Session | None = None) -> dict:
    return {"id": m.id, "mine": _sent(m, uid), "text": m.text, "sent_at": iso(m.sent_at),
            "delivered": m.delivered, "read": m.read_at is not None or _sent(m, uid),
            "links": [resolve(view, link) for link in m.links or []] if view is not None else []}


def _note(uid: int, m: ChatMessage, event: str = "new"):
    """The account's open pages hear of it (api/connect.py)."""
    from .api import connect
    connect.tell(uid, {"t": "chat", "event": event, "with": _other(m, uid), "mine": _sent(m, uid),
                       "text": m.text[:140], "links": len(m.links or [])})


def conversations(user: User) -> dict:
    """The user's conversations, the latest first: who with, the last message and how many unread."""
    here = network.server_id()
    out: dict[tuple[str, int], dict] = {}
    with db.session() as s:
        rows = s.execute(select(ChatMessage.origin, ChatMessage.from_user, func.count())
                         .where(ChatMessage.to_server == here, ChatMessage.to_user == user.id,
                                ChatMessage.read_at.is_(None))
                         .group_by(ChatMessage.origin, ChatMessage.from_user))
        unread = {(sid, uid): n for sid, uid, n in rows}
        for m in s.scalars(select(ChatMessage).where(of_user(user.id))
                           .order_by(ChatMessage.sent_at.desc(), ChatMessage.id.desc())):
            who = _other(m, user.id)
            key = (who["server"], who["user"])
            if key in out:
                continue
            if not who["here"] and (p := _peer(s, who["server"])) is not None:
                who["place"] = p.name
            out[key] = {"with": dressed(who), "at": iso(m.sent_at), "unread": unread.get(key, 0),
                        "last": {"text": m.text[:140], "mine": _sent(m, user.id), "links": len(m.links or [])}}
    return {"conversations": list(out.values()), "unread": sum(unread.values())}


def thread(user: User, sid: str, other: int, view: Session, before: int | None = None) -> dict:
    """A conversation's messages, the latest PAGE of them (before message `before`), oldest first."""
    with db.session() as s:
        q = select(ChatMessage).where(_between(user.id, sid, other))
        if before:
            b = s.get(ChatMessage, before)
            if b is not None:
                q = q.where(or_(ChatMessage.sent_at < b.sent_at, and_(ChatMessage.sent_at == b.sent_at, ChatMessage.id < b.id)))
        rows = list(s.scalars(q.order_by(ChatMessage.sent_at.desc(), ChatMessage.id.desc()).limit(PAGE + 1)))
        more, rows = len(rows) > PAGE, rows[:PAGE]
        who = dressed(_other(rows[0], user.id)) if rows else None
    if who is None:
        who = next((p for p in people(user) if p["server"] == sid and p["user"] == other), None)
        if who is None:
            raise ChatError(404, "There's nobody to write to by that name")
    return {"with": who, "more": more, "messages": [message_json(m, user.id, view) for m in reversed(rows)]}


def read(user: User, sid: str, other: int) -> int:
    """What the other person wrote, seen: how many unread are left in all."""
    here = network.server_id()
    with db.session() as s:
        s.execute(update(ChatMessage).where(ChatMessage.origin == sid, ChatMessage.from_user == other,
                                            ChatMessage.to_server == here, ChatMessage.to_user == user.id,
                                            ChatMessage.read_at.is_(None)).values(read_at=_now()))
        left = s.scalar(select(func.count()).select_from(ChatMessage).where(
            ChatMessage.to_server == here, ChatMessage.to_user == user.id, ChatMessage.read_at.is_(None)))
    from .api import connect
    connect.tell(user.id, {"t": "chat", "event": "read"})
    return left


def _add(s: Session, m: ChatMessage) -> ChatMessage:
    s.add(m)
    s.flush()
    if not m.origin_id:
        m.origin_id = m.id      # written here: its id here is its id
        s.flush()
    return m


def send(user: User, sid: str, other: int, text: str, links: list[dict], view: Session, name: str = "") -> dict:
    """The user writes to someone, here or on a linked server."""
    text = (text or "").strip()
    if len(text) > TEXT_MAX:
        raise ChatError(400, f"A message can be {TEXT_MAX} characters at most")
    if len(links) > LINKS_MAX:
        raise ChatError(400, f"A message can link {LINKS_MAX} albums and songs at most")
    snaps = [snapshot(view, str(link.get("kind")), int(link.get("id") or 0)) for link in links]
    if not text and not snaps:
        raise ChatError(400, "Write something, or link an album or a song")
    here = network.server_id()
    base = {"origin": here, "origin_id": 0, "from_user": user.id, "from_name": user.username,
            "from_place": network.name(), "text": text, "links": snaps, "sent_at": _now()}
    if sid == here:
        if other == user.id:
            raise ChatError(400, "That's you")
        with db.session() as s:
            to = s.get(User, other)
            if to is None:
                raise ChatError(404, "There's nobody by that name here")
            if _hidden(to) and not _wrote(s, here, other, here, user.id):
                raise ChatError(403, f"{to.username} isn't taking messages")
            m = _add(s, ChatMessage(**base, to_server=here, to_user=other, to_name=to.username,
                                    to_place=network.name(), delivered=True))
            out = message_json(m, user.id, view)
        _note(user.id, m)
        _note(other, m)
        return out

    with db.session() as s:
        p = _peer(s, sid)
        if p is None:
            raise ChatError(404, "That server isn't linked with this one any more")
        address, key, place = p.address, p.key, p.name
        m = _add(s, ChatMessage(**base, to_server=sid, to_user=other, to_name=name[:64], to_place=place,
                                delivered=False))
        body, mid = _wire(m, own_look(user)), m.id
    try:
        with network._client() as c:
            r = c.post(address + "/api/network/chat", json=body, headers={"Authorization": f"Bearer {key}"}, timeout=10)
    except httpx.HTTPError as e:
        log.info("Couldn't hand a message to %s (%s): it waits here until it asks", place, e)
        r = None
    refused = None
    with db.session() as s:
        m = s.get(ChatMessage, mid)
        if r is not None and r.status_code == 200:
            m.delivered = True
            got = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            m.to_name = str(got.get("name") or m.to_name)[:64]
        elif r is not None and r.status_code in (403, 404):
            s.delete(m)             # turned down: it isn't kept
            detail = network._detail(r)
            refused = (ChatError(400, f"{place} runs a Muzix without the chat: its admin needs to update it")
                       if detail == "Not Found" else ChatError(r.status_code, detail))   # Not Found: no such route there
        out = None if refused else message_json(m, user.id, view)
    if refused:
        raise refused
    _note(user.id, m)
    return out


# ------------------------------------------------------------ another server

def receive(p: Peer, body: dict) -> dict:
    """A linked server hands over a message one of its people wrote to someone here."""
    try:
        oid, frm, to_user = _int(body["id"]), _int(body["from_user"]), _int(body["to_user"])
        text = body.get("text") or ""
        links = body.get("links") or []
        if oid <= 0 or not isinstance(text, str) or not isinstance(links, list):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise ChatError(400, "That isn't a message")
    if len(text) > TEXT_MAX or len(links) > LINKS_MAX:
        raise ChatError(400, "That message is too long")
    try:
        sent = datetime.fromisoformat(body.get("sent_at") or "")
        sent = (sent if sent.tzinfo else sent.replace(tzinfo=timezone.utc))
        sent = min(sent, _now() + timedelta(minutes=5))         # its clock may run fast
    except (ValueError, TypeError):
        sent = _now()
    here = network.server_id()
    if (look := clean_look(body.get("from_avatar"))) is not None:
        _looks[(p.server_id, frm)] = look
    try:
        with db.session() as s:
            to = s.get(User, to_user)
            if to is None:
                raise ChatError(404, "There's nobody by that name here")
            name = to.username
            known = s.scalar(select(ChatMessage.id).where(ChatMessage.origin == p.server_id, ChatMessage.origin_id == oid))
            if known is not None:
                return {"ok": True, "name": name}
            if _hidden(to) and not _wrote(s, here, to_user, p.server_id, frm):
                raise ChatError(403, f"{name} isn't taking messages")
            m = _add(s, ChatMessage(origin=p.server_id, origin_id=oid, from_user=frm,
                                    from_name=_text(body.get("from_name"), 64), from_place=p.name, to_server=here,
                                    to_user=to_user, to_name=name, to_place=network.name(), text=text,
                                    links=[c for c in map(clean_link, links) if c], sent_at=sent, delivered=True))
    except IntegrityError:          # handed over and fetched at the same moment: it's here once
        return {"ok": True, "name": name}
    _note(to_user, m)
    return {"ok": True, "name": name}


def waiting(p: Peer, after: int = 0) -> dict:
    """What people here wrote to a linked server's people, from `after` on: it has them now."""
    here = network.server_id()
    with db.session() as s:
        rows = list(s.scalars(select(ChatMessage).where(ChatMessage.origin == here, ChatMessage.to_server == p.server_id,
                                                        ChatMessage.origin_id > after)
                              .order_by(ChatMessage.origin_id).limit(WAITING_PAGE)))
        newly = [m for m in rows if not m.delivered]
        for m in newly:
            m.delivered = True
        writers = {u.id: own_look(u) for u in s.scalars(select(User).where(User.id.in_({m.from_user for m in rows})))}
        out = [_wire(m, writers.get(m.from_user)) for m in rows]
    for m in newly:
        _note(m.from_user, m, "delivered")
    return {"messages": out, "more": len(rows) == WAITING_PAGE}


def catch_up(peer_id: int):
    """What's waiting on a linked server for people here, fetched."""
    with db.session() as s:
        p = s.get(Peer, peer_id)
        if p is None or network.state(p) != "linked" or p.kind != "server":
            return
        s.expunge(p)
    after = p.chat_after
    while True:
        try:
            with network._client() as c:
                r = c.get(p.address + "/api/network/chat", params={"after": after},
                          headers={"Authorization": f"Bearer {p.key}"}, timeout=15)
            page = r.json() if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            page = None
        if not isinstance(page, dict) or not isinstance(page.get("messages"), list):
            break
        top = after
        for body in page["messages"]:
            try:
                receive(p, body)
            except ChatError as e:
                log.info("A message from %s wasn't taken: %s", p.name, e)
            try:
                top = max(top, _int(body["id"]))
            except (ValueError, KeyError, TypeError):
                pass
        if top > after:
            with db.session() as s:
                s.execute(update(Peer).where(Peer.id == peer_id).values(chat_after=top))
        if not page.get("more") or top == after:
            break
        after = top


def catch_up_all():
    if not modules.on("network"):
        return
    with db.session() as s:
        linked = [(p.id, p.server_id, p.address, p.key, p.name) for p in _linked(s)]
    for pid, *who in linked:
        try:
            _theirs(*who)
            catch_up(pid)
        except Exception:
            log.exception("Couldn't fetch the messages waiting on a linked server")


def start():
    """Asks the linked servers for what's waiting here: soon after starting, then every EVERY seconds."""
    def loop():
        time.sleep(30)
        while True:
            catch_up_all()
            time.sleep(EVERY)

    threading.Thread(target=loop, name="chat-catch-up", daemon=True).start()

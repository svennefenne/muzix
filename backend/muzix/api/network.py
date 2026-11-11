"""The Library Network (network.py, mirror.py): the admin's side (the sharing code, linking,
syncing and unlinking) and what other Muzix servers call."""

import os

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, WebSocket
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import __version__, art, chat, db, lyrics, mirror, network, settings, tunnel
from ..db import get_db_with_copies
from ..models import Album, Artist, Book, BookPart, Peer, Track
from ..security import admin_user, current_user
from . import books as books_api, library, stream

router = APIRouter(prefix="/api/network", tags=["network"])


# ---------------------------------------------------------------- the admin

@router.get("", dependencies=[Depends(admin_user)])
def overview():
    main = network.main()
    with db.session() as s:
        rows = list(s.scalars(select(Peer).order_by(Peer.created_at)))
        peers = [network.peer_json(p) for p in rows]
        first = next((j["id"] for j, p in zip(peers, rows) if p.server_id == main and j["state"] == "linked"), None)
        copies = {"albums": s.scalar(select(func.count()).select_from(Album).where(Album.shadowed.is_(True))),
                  "books": s.scalar(select(func.count()).select_from(Book).where(Book.shadowed.is_(True)))}
    return {"name": network.name(), "code": network.code(), "address": settings.get("public_url"), "peers": peers,
            "main": first, "copies": copies}


class Main(BaseModel):
    peer_id: int | None = None      # None: this server's library


@router.put("/main", dependencies=[Depends(admin_user)])
def set_main(body: Main):
    """The library whose copy of an album shows when others have it too."""
    sid = None
    if body.peer_id is not None:
        with db.session() as s:
            p = s.get(Peer, body.peer_id)
            if p is None or network.state(p) != "linked":
                raise HTTPException(404, "There's no such server linked")
            sid = p.server_id
    network.set_main(sid)
    return mirror.dedupe()


@router.post("/code", dependencies=[Depends(admin_user)])
def new_code():
    """On, or a new code: the old one no longer links (the links there are stay)."""
    return {"code": network.new_code()}


@router.delete("/code", dependencies=[Depends(admin_user)])
def turn_off():
    network.turn_off()
    return {"code": None}


@router.get("/servers", dependencies=[Depends(current_user)])
def servers():
    """The linked servers' names, for everyone's Settings (whether to leave their music out)."""
    with db.session() as s:
        return [p.name for p in s.scalars(select(Peer).order_by(Peer.id)) if network.state(p) == "linked"]


class LinkTo(BaseModel):
    address: str = Field(max_length=1024)
    code: str = Field(max_length=64)
    own_address: str = Field("", max_length=1024)   # where the admin's browser reaches this server


@router.post("/peers", dependencies=[Depends(admin_user)])
def link(body: LinkTo):
    own = settings.get("public_url") or body.own_address
    try:
        return network.link(body.address, body.code, own)
    except network.NetworkError as e:
        raise HTTPException(400, str(e))


class Accept(BaseModel):
    code: str = Field(max_length=64)


@router.post("/peers/{peer_id}/accept", dependencies=[Depends(admin_user)])
def accept(peer_id: int, body: Accept):
    """Yes to a computer's request: its code, as its Muzix client shows it."""
    try:
        return network.accept(peer_id, body.code)
    except network.NetworkError as e:
        raise HTTPException(400, str(e))


@router.post("/peers/{peer_id}/sync", dependencies=[Depends(admin_user)])
def sync(peer_id: int):
    with db.session() as s:
        p = s.get(Peer, peer_id)
        if p is None or network.state(p) != "linked":
            raise HTTPException(404, "There's no such server linked")
        network.fetch(p.id, p.name)
    return {"ok": True}


@router.delete("/peers/{peer_id}", dependencies=[Depends(admin_user)])
def unlink(peer_id: int):
    try:
        network.unlink(peer_id)
    except network.NetworkError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


# ---------------------------------------------------------------- other servers

@router.get("/hello")
def hello():
    """Who answers here, for a server about to hand over our code."""
    return {"muzix": __version__, "protocol": network.PROTOCOL, "server_id": network.server_id(),
            "name": network.name(), "open": network.code() is not None}


class LinkRequest(BaseModel):
    protocol: int
    code: str = Field(max_length=64)
    server_id: str = Field(min_length=8, max_length=64)
    name: str = Field("", max_length=255)
    address: str = Field("", max_length=1024)
    key: str = Field(min_length=32, max_length=128)
    kind: str = Field("server", pattern="^(server|computer)$")
    check: str = Field("", max_length=64)       # a computer's: network.computer_check of its code


@router.post("/link")
def link_request(body: LinkRequest, request: Request):
    try:
        return network.receive(body.model_dump(), request.client.host if request.client else "")
    except network.Refused as e:
        raise HTTPException(e.status, str(e))


@router.websocket("/tunnel")
async def computer_tunnel(ws: WebSocket):
    """Where a computer in the network (the desktop client) keeps its connection open."""
    await tunnel.serve(ws)


@router.post("/unlink")
def unlinked(authorization: str = Header("")):
    if not network.forget(authorization):
        raise HTTPException(401, "Not a server in this one's network")
    return {"ok": True}


def linked_server(authorization: str = Header("")) -> Peer:
    p = network.caller(authorization)
    if p is None:
        raise HTTPException(401, "Not a server in this one's network")
    return p


@router.get("/catalog/{part}", dependencies=[Depends(linked_server)])
def catalog(part: str, after: int = 0, limit: int = mirror.PAGE):
    """A page of this server's own library, for a linked server to mirror."""
    if part not in mirror.PARTS:
        raise HTTPException(404, "No such part of the catalog")
    return mirror.export(part, after, limit)


# what a linked server's listeners play and see of this library: only its own, nothing hidden

def _own(db: Session, model, id_: int):
    row = db.get(model, id_)
    if row is None or row.hidden or getattr(row, "peer_id", None) is not None:
        raise HTTPException(404, "Not in this server's own library")
    return row


@router.get("/stream/{track_id}", dependencies=[Depends(linked_server)])
def stream_track(track_id: int, q: str = "original", t: float = 0.0, prefetch: bool = False,
                 db: Session = Depends(get_db_with_copies)):
    tr = _own(db, Track, track_id)
    return stream.audio(tr.path, tr.format, tr.codec, tr.sample_rate, tr.bit_depth, tr.subsong, tr.duration,
                        tr.extra, q, t, prefetch)


@router.get("/books/{book_id}/parts/{position}/stream", dependencies=[Depends(linked_server)])
def stream_part(book_id: int, position: int, q: str = "original", t: float = 0.0,
                db: Session = Depends(get_db_with_copies)):
    _own(db, Book, book_id)
    p = db.scalar(select(BookPart).where(BookPart.book_id == book_id, BookPart.position == position))
    if p is None:
        raise HTTPException(404, "No such part")
    return stream.stream_file(p.path, p.format, "", 0, 16, q, t)


@router.get("/art/{kind}/{item_id}", dependencies=[Depends(linked_server)])
def picture(kind: str, item_id: int, s: int = 300, db: Session = Depends(get_db_with_copies)):
    if kind == "album":
        _own(db, Album, item_id)
        return library.album_art(item_id, s, db)
    if kind == "book":
        _own(db, Book, item_id)
        return books_api.book_art(item_id, s, db)
    if kind == "artist":            # its own picture (one of its albums' covers comes with the album)
        a = _own(db, Artist, item_id)
        if a.image and os.path.exists(a.image):
            data, ident = art.source_bytes(a.image)
            return library._send(data, ident, s)
    return Response(status_code=404)


@router.get("/lyrics/{track_id}", dependencies=[Depends(linked_server)])
def track_lyrics(track_id: int, db: Session = Depends(get_db_with_copies)):
    out = lyrics.for_track(db, _own(db, Track, track_id))
    db.commit()
    return out


# the chat (chat.py): a linked server's people writing to people here

@router.get("/chat/people")
def chat_people(p: Peer = Depends(linked_server)):
    """Who here can be written to."""
    with db.session() as s:
        return chat.visible(s)


@router.post("/chat")
def chat_in(body: dict, p: Peer = Depends(linked_server)):
    """A message one of its people wrote to someone here."""
    try:
        return chat.receive(p, body)
    except chat.ChatError as e:
        raise HTTPException(e.status, str(e))


@router.get("/avatars/{name}", dependencies=[Depends(linked_server)])
def chat_avatar(name: str):
    """An account's icon picture, for its people list and messages there."""
    path = chat.own_picture(name)
    if path is None:
        raise HTTPException(404, "No such picture")
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "private, max-age=31536000, immutable"})


@router.get("/chat")
def chat_waiting(after: int = 0, p: Peer = Depends(linked_server)):
    """What people here wrote to its people, from `after` on (the ids here): those it didn't get yet too."""
    return chat.waiting(p, after)

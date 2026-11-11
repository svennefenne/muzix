"""The Library Network's chat (chat.py), for the pages: the user's conversations, who they can write
to, a conversation's messages, writing, and the linked albums and songs (their songs, and the audio
and covers of what's on another server, through this one)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import chat, limits, mirror
from ..db import get_db_with_copies
from ..models import ChatMessage, User
from ..security import current_user, stream_user
from .library import _picture
from .stream import theirs

router = APIRouter(prefix="/api/chat", tags=["chat"])
art_router = APIRouter(prefix="/api/art", tags=["art"])


def _fail(e: chat.ChatError):
    raise HTTPException(e.status, str(e))


@router.get("")
def conversations(user: User = Depends(current_user)):
    return chat.conversations(user)


@router.get("/people")
def people(user: User = Depends(current_user)):
    return chat.people(user)


@router.get("/with/{server}/{other}")
def thread(server: str, other: int, before: int | None = None, user: User = Depends(current_user),
           db: Session = Depends(get_db_with_copies)):
    try:
        return chat.thread(user, server, other, db, before)
    except chat.ChatError as e:
        _fail(e)


class Link(BaseModel):
    kind: str = Field(pattern="^(album|track)$")
    id: int


class Write(BaseModel):
    text: str = Field("", max_length=chat.TEXT_MAX + 1000)
    links: list[Link] = Field(default_factory=list, max_length=chat.LINKS_MAX)
    name: str = Field("", max_length=64)         # the other person's name as the page shows it


@router.post("/with/{server}/{other}")
def write(server: str, other: int, body: Write, user: User = Depends(current_user),
          db: Session = Depends(get_db_with_copies)):
    try:
        return chat.send(user, server, other, body.text, [link.model_dump() for link in body.links], db, body.name)
    except chat.ChatError as e:
        _fail(e)


@router.post("/with/{server}/{other}/read")
def read(server: str, other: int, user: User = Depends(current_user)):
    return {"unread": chat.read(user, server, other)}


@router.get("/messages/{message_id}/links/{index}")
def link(message_id: int, index: int, user: User = Depends(current_user), db: Session = Depends(get_db_with_copies)):
    """A linked album or song with its songs, for "More info"."""
    m = db.scalar(select(ChatMessage).where(ChatMessage.id == message_id, chat.of_user(user.id)))
    if m is None:
        raise HTTPException(404, "No such message")
    links = m.links or []
    if not 0 <= index < len(links):
        raise HTTPException(404, "No such link")
    return chat.resolve(db, links[index], tracks=True)


@router.get("/avatars/{server}/{name}", dependencies=[Depends(current_user)])
def avatar(server: str, name: str):
    """The icon picture of someone on a linked server, through this one."""
    path = chat.picture(server, name)
    if path is None:
        raise HTTPException(404, "No such picture")
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "private, max-age=31536000, immutable"})


@router.get("/stream/{server}/{track_id}")
def stream(server: str, track_id: int, request: Request, q: str = "original", t: float = 0.0, prefetch: bool = False,
           user: User = Depends(stream_user)):
    """A linked song on another server that this one hasn't mirrored (yet), through this one: not
    for an account with limits (chat.resolve doesn't offer it them either)."""
    if limits.of(user) is not None:
        raise HTTPException(404, "No such song")
    return theirs(f"{mirror.ROOT}{server}/tracks/{track_id}", q, t, prefetch, request)


@art_router.get("/network/{server}/album/{album_id}")
def cover(server: str, album_id: int, v: int = 1, s: int = 300, user: User = Depends(current_user)):
    """A linked album's cover on another server, for one this server hasn't mirrored (yet)."""
    if limits.of(user) is not None:
        return _picture(None)
    try:
        return _picture(mirror.picture(f"{mirror.ROOT}{server}/albums/{album_id}/{v}", s))
    except mirror.Away:
        return _picture(None)

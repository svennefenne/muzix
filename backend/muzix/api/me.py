import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from .. import serial
from ..db import get_db
from ..models import (Album, Artist, Book, BookProgress, Feed, Like, Playlist, PlaylistItem, Station,
                      Subscription, Track, User)
from ..security import check_password, current_user, hash_password, optional_user
from .library import file_playlists, tracks_json

router = APIRouter(prefix="/api", tags=["me"])
client_log = logging.getLogger("muzix.client")


class ClientError(BaseModel):
    kind: str = Field("error", max_length=20)
    message: str = Field("", max_length=1000)
    stack: str = Field("", max_length=6000)
    url: str = Field("", max_length=500)


@router.post("/client-errors")
def client_error(body: ClientError, request: Request, user: User | None = Depends(optional_user)):
    """Errors from the web interface, written to the log so they can be looked into."""
    if user is not None:
        client_log.warning("%s in the browser (%s, %s, %s): %s\n%s", body.kind, user.username, body.url,
                           request.headers.get("user-agent", "")[:200], body.message, body.stack)
    return {"ok": True}
LIKE_TYPES = {"track": Track, "album": Album, "artist": Artist}


# ---------------------------------------------------------------- preferences

@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "username": user.username, "is_admin": user.is_admin, "prefs": user.prefs or {}}


@router.patch("/me/prefs")
def set_prefs(prefs: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    u = db.get(User, user.id)
    merged = {**(u.prefs or {}), **prefs}
    u.prefs = {k: v for k, v in merged.items() if v is not None}
    db.commit()
    return u.prefs


class PasswordChange(BaseModel):
    current: str
    new: str = Field(min_length=6, max_length=256)


@router.post("/me/password")
def change_password(body: PasswordChange, db: Session = Depends(get_db), user: User = Depends(current_user)):
    u = db.get(User, user.id)
    if not check_password(u, body.current):
        raise HTTPException(400, "The current password is wrong")
    u.password_hash = hash_password(body.new)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- likes

@router.put("/likes/{kind}/{item_id}")
def like(kind: str, item_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if kind not in LIKE_TYPES or db.get(LIKE_TYPES[kind], item_id) is None:
        raise HTTPException(404, "Nothing to like")
    if db.get(Like, (user.id, kind, item_id)) is None:
        db.add(Like(user_id=user.id, item_type=kind, item_id=item_id))
        db.commit()
    return {"liked": True}


@router.delete("/likes/{kind}/{item_id}")
def unlike(kind: str, item_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    db.execute(delete(Like).where(Like.user_id == user.id, Like.item_type == kind, Like.item_id == item_id))
    db.commit()
    return {"liked": False}


@router.get("/likes/tracks")
def liked_tracks(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.execute(select(Track, Like.created_at).join(Like, (Like.item_id == Track.id) & (Like.item_type == "track"))
                      .where(Like.user_id == user.id).order_by(Like.created_at.desc())).all()
    return tracks_json(db, user, [t for t, _ in rows])


# ---------------------------------------------------------------- playlists

class PlaylistBody(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    public: bool = False


def _playlist(db: Session, user: User, pid: int, write=False) -> Playlist:
    p = db.get(Playlist, pid)
    if p is None or (p.user_id != user.id and (write or not p.public)):
        raise HTTPException(404, "No such playlist")
    return p


def playlist_json(db: Session, p: Playlist, with_tracks=False, user: User | None = None):
    count, duration = db.execute(select(func.count(), func.coalesce(func.sum(Track.duration), 0))
                                 .select_from(PlaylistItem).join(Track, Track.id == PlaylistItem.track_id)
                                 .where(PlaylistItem.playlist_id == p.id)).one()
    arts = db.scalars(select(Track.album_id).join(PlaylistItem, PlaylistItem.track_id == Track.id)
                      .where(PlaylistItem.playlist_id == p.id, Track.album_id.is_not(None))
                      .order_by(PlaylistItem.position).distinct().limit(4)).all()
    out = {"id": p.id, "name": p.name, "description": p.description, "public": p.public,
           "owner_id": p.user_id, "track_count": count, "duration": duration,
           "art": [serial.art_url("album", a) for a in arts],
           "updated_at": p.updated_at.isoformat() if p.updated_at else None}
    if with_tracks:
        rows = db.execute(select(PlaylistItem.id, Track).join(Track, Track.id == PlaylistItem.track_id)
                          .where(PlaylistItem.playlist_id == p.id).order_by(PlaylistItem.position)).all()
        tj = tracks_json(db, user, [t for _, t in rows])
        out["tracks"] = [{**t, "item_id": iid} for (iid, _), t in zip(rows, tj, strict=True)]
    return out


@router.get("/playlists")
def playlists(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(Playlist).where((Playlist.user_id == user.id) | Playlist.public)
                      .order_by(Playlist.updated_at.desc()))
    return [playlist_json(db, p) for p in rows]


@router.post("/playlists")
def create_playlist(body: PlaylistBody, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = Playlist(user_id=user.id, **body.model_dump())
    db.add(p)
    db.commit()
    return playlist_json(db, p)


@router.get("/playlists/{pid}")
def get_playlist(pid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return playlist_json(db, _playlist(db, user, pid), True, user)


@router.patch("/playlists/{pid}")
def edit_playlist(pid: int, body: PlaylistBody, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = _playlist(db, user, pid, write=True)
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    p.updated_at = datetime.now(timezone.utc)
    db.commit()
    return playlist_json(db, p)


@router.delete("/playlists/{pid}")
def delete_playlist(pid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    db.delete(_playlist(db, user, pid, write=True))
    db.commit()
    return {"ok": True}


class AddTracks(BaseModel):
    track_ids: list[int] = Field(max_length=5000)


@router.post("/playlists/{pid}/tracks")
def add_tracks(pid: int, body: AddTracks, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = _playlist(db, user, pid, write=True)
    pos = db.scalar(select(func.coalesce(func.max(PlaylistItem.position), -1))
                    .where(PlaylistItem.playlist_id == pid))
    valid = set(db.scalars(select(Track.id).where(Track.id.in_(body.track_ids))))
    for tid in body.track_ids:
        if tid in valid:
            pos += 1
            db.add(PlaylistItem(playlist_id=pid, track_id=tid, position=pos))
    p.updated_at = datetime.now(timezone.utc)
    db.commit()
    return playlist_json(db, p)


@router.delete("/playlists/{pid}/items/{item_id}")
def remove_item(pid: int, item_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = _playlist(db, user, pid, write=True)
    db.execute(delete(PlaylistItem).where(PlaylistItem.playlist_id == pid, PlaylistItem.id == item_id))
    p.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


class Reorder(BaseModel):
    item_ids: list[int]


@router.put("/playlists/{pid}/order")
def reorder(pid: int, body: Reorder, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _playlist(db, user, pid, write=True)
    for pos, iid in enumerate(body.item_ids):
        db.execute(update(PlaylistItem).where(PlaylistItem.playlist_id == pid, PlaylistItem.id == iid)
                   .values(position=pos))
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- the "Your library" panel

def _recent_albums(db: Session, user: User, kind: str, limit: int) -> list[Album]:
    ids = [r[0] for r in db.execute(text(
        "SELECT t.album_id, max(p.played_at) m FROM plays p JOIN tracks t ON t.id = p.track_id "
        "WHERE p.user_id = :u AND t.kind = :k AND t.album_id IS NOT NULL "
        "GROUP BY t.album_id ORDER BY m DESC LIMIT :l"), {"u": user.id, "k": kind, "l": limit})]
    rows = {a.id: a for a in db.scalars(select(Album).where(Album.id.in_(ids)))}
    return [rows[i] for i in ids if i in rows]


def _album_item(a: Album, liked: set[int]) -> dict:
    return {"id": a.id, "title": a.title, "artist": a.artist_name, "year": a.year, "kind": a.kind,
            "art": serial.art_url("album", a.id) if a.art else None, "liked": a.id in liked}


@router.get("/sidebar")
def sidebar(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Everything the library panel lists, in one request: what you saved, follow,
    listen to or played lately."""
    liked_albums = set(db.scalars(select(Like.item_id).where(Like.user_id == user.id, Like.item_type == "album")))
    liked_ids = liked_albums
    albums = list(db.scalars(select(Album).where(Album.id.in_(liked_albums), Album.kind == "music")
                             .order_by(func.lower(Album.artist_name), Album.year)))
    seen = {a.id for a in albums}
    albums += [a for a in _recent_albums(db, user, "music", 30) if a.id not in seen]
    games = _recent_albums(db, user, "vgm", 24)
    if len(games) < 8:
        have = {a.id for a in games}
        games += [a for a in db.scalars(select(Album).where(Album.kind == "vgm").order_by(Album.added_at.desc()).limit(12))
                  if a.id not in have][: 8 - len(games)]
    liked_artists = set(db.scalars(select(Like.item_id).where(Like.user_id == user.id, Like.item_type == "artist")))
    artists = db.scalars(select(Artist).where(Artist.id.in_(liked_artists)).order_by(func.lower(Artist.name)))
    books = db.execute(select(Book, BookProgress).join(BookProgress, BookProgress.book_id == Book.id)
                       .where(BookProgress.user_id == user.id, BookProgress.position > 0,
                              BookProgress.finished.is_(False))
                       .order_by(BookProgress.updated_at.desc()).limit(20)).all()
    feeds = db.scalars(select(Feed).join(Subscription, Subscription.feed_id == Feed.id)
                       .where(Subscription.user_id == user.id).order_by(func.lower(Feed.title)))
    from .podcasts import fresh_feeds
    fresh = fresh_feeds(db, user.id)
    stations = db.scalars(select(Station).where(Station.user_id == user.id).order_by(func.lower(Station.name)))
    lists = db.scalars(select(Playlist).where(Playlist.user_id == user.id).order_by(Playlist.updated_at.desc()))
    from .radio import saved_json
    return {
        "liked_songs": db.scalar(select(func.count()).select_from(Like)
                                 .where(Like.user_id == user.id, Like.item_type == "track")),
        "playlists": [{"id": p.id, "name": p.name, "art": (playlist_json(db, p)["art"] or [None])[0]} for p in lists],
        "file_playlists": [{**f, "art": (f["art"] or [None])[0]} for f in file_playlists(db)],
        "albums": [_album_item(a, liked_ids) for a in albums],
        "games": [_album_item(a, liked_ids) for a in games],
        "artists": [{"id": a.id, "name": a.name, "art": serial.art_url("artist", a.id)} for a in artists],
        "books": [{"id": b.id, "title": b.title, "author": b.author, "art": f"/api/art/book/{b.id}" if b.art else None,
                   "progress": round(p.position / b.duration, 3) if b.duration else 0} for b, p in books],
        "podcasts": [{"id": f.id, "title": f.title or f.url, "author": f.author, "art": f.image or None,
                      "new": f.id in fresh} for f in feeds],
        "stations": [saved_json(st) for st in stations],
    }

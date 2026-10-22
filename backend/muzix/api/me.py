from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .. import serial
from ..db import get_db
from ..models import Album, Artist, Like, Playlist, PlaylistItem, Track, User
from ..security import check_password, current_user, hash_password
from .library import tracks_json

router = APIRouter(prefix="/api", tags=["me"])
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

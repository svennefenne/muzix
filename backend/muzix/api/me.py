import hashlib
import io
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from .. import env, serial
from ..db import get_db_with_copies
from ..models import (Album, Artist, AuthSession, Book, BookProgress, Feed, Like, Playlist, PlaylistItem, Station,
                      Subscription, Track, User)
from ..security import (SESSION_DAYS, check_password, current_user, device_name, hash_password, login_id, login_token,
                        optional_user)
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
    """Errors from the web interface, and the Android app's crashes (android/.../Crashes.kt), written
    to the log so they can be looked into."""
    if user is not None:
        agent = request.headers.get("user-agent", "")
        where = "the app" if agent.startswith("MuzixApp/") else "the browser"
        client_log.warning("%s in %s (%s, %s, %s): %s\n%s", body.kind, where, user.username, body.url,
                           agent[:200], body.message, body.stack)
    return {"ok": True, "logged": user is not None}     # the app tells its crashes again until they're in
LIKE_TYPES = {"track": Track, "album": Album, "artist": Artist}


# ---------------------------------------------------------------- preferences
# Each device (each login) keeps its own settings; these are the account's, the same everywhere.
ACCOUNT_PREFS = ("network", "chat_hidden")


def _merged(prefs: dict, changes: dict) -> dict:
    return {k: v for k, v in {**prefs, **changes}.items() if v is not None}     # None takes a setting out


def device_prefs(db: Session, user: User, token: str | None) -> dict:
    """The settings a device shows: its own, and the account's. A login without settings of its own (new,
    or from before devices had them) starts from the account's, once."""
    account = user.prefs or {}
    row = db.get(AuthSession, token) if token else None
    if row is not None and row.prefs is None:
        row.prefs = {k: v for k, v in account.items() if k not in ACCOUNT_PREFS}
        db.commit()
    own = account if row is None else row.prefs
    return {**{k: v for k, v in own.items() if k not in ACCOUNT_PREFS}, **{k: account[k] for k in ACCOUNT_PREFS if k in account}}


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    return {"id": user.id, "username": user.username, "is_admin": user.is_admin, "avatar": serial.avatar(user),
            "prefs": device_prefs(db, user, login_token(request))}


@router.patch("/me/prefs")
def set_prefs(prefs: dict, request: Request, db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    u = db.get(User, user.id)
    token = login_token(request)
    device_prefs(db, u, token)
    if account := {k: v for k, v in prefs.items() if k in ACCOUNT_PREFS}:
        u.prefs = _merged(u.prefs or {}, account)
    row = db.get(AuthSession, token) if token else None
    if row is not None:
        row.prefs = _merged(row.prefs or {}, {k: v for k, v in prefs.items() if k not in ACCOUNT_PREFS})
    db.commit()
    return device_prefs(db, u, token)


class PasswordChange(BaseModel):
    current: str
    new: str = Field(min_length=6, max_length=256)


@router.post("/me/password")
def change_password(body: PasswordChange, db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    u = db.get(User, user.id)
    if not check_password(u, body.current):
        raise HTTPException(400, "The current password is wrong")
    u.password_hash = hash_password(body.new)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- the account's icon

AVATAR_SIDE = 256
MAX_AVATAR = 16 * 1024 * 1024
AVATAR_FILE = r"^[0-9a-f]{24}\.webp$"


class AvatarLook(BaseModel):
    """A picture uploaded first (POST /me/avatar/picture), or a letter or two on a colour."""
    picture: str | None = Field(default=None, pattern=AVATAR_FILE)
    letter: str | None = Field(default=None, min_length=1, max_length=8)   # an emoji takes a few code points
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


@router.post("/me/avatar/picture")
async def avatar_picture(file: UploadFile = File(...), x: float = Form(0.5), y: float = Form(0.5),
                         size: float = Form(1.0), user: User = Depends(current_user)):
    """A picture for the icon: the square around (x, y) (fractions of the picture's width and height),
    `size` of its shorter side, as a WebP of 256 px. Kept by its contents; PUT /me/avatar uses it."""
    data = await file.read(MAX_AVATAR + 1)
    if len(data) > MAX_AVATAR:
        raise HTTPException(413, "That picture is too big (16 MB at most)")
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        w, h = img.size
        side = max(1, round(min(w, h) * min(max(size, 0.05), 1)))
        left = min(max(round(x * w - side / 2), 0), w - side)
        top = min(max(round(y * h - side / 2), 0), h - side)
        img = img.crop((left, top, left + side, top + side)).resize((AVATAR_SIDE, AVATAR_SIDE), Image.LANCZOS)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        out = io.BytesIO()
        img.save(out, "WEBP", quality=86, method=4)
    except Exception:
        raise HTTPException(400, "That isn't a picture Muzix can read")
    name = hashlib.sha256(out.getvalue()).hexdigest()[:24] + ".webp"
    path = env.AVATAR_DIR / name
    if not path.exists():
        env.AVATAR_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(out.getvalue())
        os.replace(tmp, path)
    return {"picture": name, "url": f"/api/avatars/{name}"}


@router.get("/me/avatar")
def get_avatar(user: User = Depends(current_user)):
    """The account's icon on its own: the app's own library asks the server for it (it has no account)."""
    return serial.avatar(user)


@router.put("/me/avatar")
def set_avatar(body: AvatarLook, db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    u = db.get(User, user.id)
    if body.picture:
        if not (env.AVATAR_DIR / body.picture).is_file():
            raise HTTPException(400, "Upload the picture first")
        u.avatar = {"picture": body.picture}
    elif body.letter or body.color:
        u.avatar = {k: v for k, v in (("letter", (body.letter or "").strip()), ("color", (body.color or "").lower())) if v} or None
    else:
        u.avatar = None
    db.commit()
    _tidy_avatars(db)
    return serial.avatar(u)


@router.delete("/me/avatar")
def reset_avatar(db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    """Back to the first letter of the name, on the scheme's colours."""
    u = db.get(User, user.id)
    u.avatar = None
    db.commit()
    _tidy_avatars(db)
    return serial.avatar(u)


def _tidy_avatars(db: Session):
    """Pictures no account uses any more, an hour after they were uploaded (one may be on its way)."""
    used = {(a or {}).get("picture") for a in db.scalars(select(User.avatar))}
    for f in env.AVATAR_DIR.glob("*.webp"):
        if f.name not in used and time.time() - f.stat().st_mtime > 3600:
            f.unlink(missing_ok=True)


@router.get("/avatars/{name}")
def avatar_file(name: str, user: User = Depends(current_user)):
    path = env.AVATAR_DIR / os.path.basename(name)
    if not re.match(AVATAR_FILE, name) or not path.is_file():
        raise HTTPException(404, "No such picture")
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "private, max-age=31536000, immutable"})


# ---------------------------------------------------------------- devices: the account's logins

def _logins(db: Session, user: User) -> list[AuthSession]:
    since = datetime.now(timezone.utc) - timedelta(days=SESSION_DAYS)
    return list(db.scalars(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.last_seen > since)
                           .order_by(AuthSession.last_seen.desc())))


@router.get("/me/devices")
def devices(request: Request, db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    """Where the account is signed in: each browser and app, newest seen first, this one marked."""
    mine = login_token(request)
    return [{"id": login_id(r.token), "name": r.name or device_name(r.user_agent), "app": bool(r.name),
             "since": serial.iso(r.created_at), "seen": serial.iso(r.last_seen), "current": r.token == mine}
            for r in _logins(db, user)]


@router.delete("/me/devices/{device_id}")
def sign_out_device(device_id: str, db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    row = next((r for r in _logins(db, user) if login_id(r.token) == device_id), None)
    if row is None:
        raise HTTPException(404, "No such device")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- likes

@router.put("/likes/{kind}/{item_id}")
def like(kind: str, item_id: int, db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    if kind not in LIKE_TYPES or db.get(LIKE_TYPES[kind], item_id) is None:
        raise HTTPException(404, "Nothing to like")
    if db.get(Like, (user.id, kind, item_id)) is None:
        db.add(Like(user_id=user.id, item_type=kind, item_id=item_id))
        db.commit()
    return {"liked": True}


@router.delete("/likes/{kind}/{item_id}")
def unlike(kind: str, item_id: int, db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    db.execute(delete(Like).where(Like.user_id == user.id, Like.item_type == kind, Like.item_id == item_id))
    db.commit()
    return {"liked": False}


@router.get("/likes/tracks")
def liked_tracks(db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
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
           "updated_at": serial.iso(p.updated_at)}
    if with_tracks:
        rows = db.execute(select(PlaylistItem.id, Track).join(Track, Track.id == PlaylistItem.track_id)
                          .where(PlaylistItem.playlist_id == p.id).order_by(PlaylistItem.position)).all()
        tj = tracks_json(db, user, [t for _, t in rows])
        out["tracks"] = [{**t, "item_id": iid} for (iid, _), t in zip(rows, tj, strict=True)]
    return out


@router.get("/playlists")
def playlists(db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    rows = db.scalars(select(Playlist).where((Playlist.user_id == user.id) | Playlist.public)
                      .order_by(Playlist.updated_at.desc()))
    return [playlist_json(db, p) for p in rows]


@router.post("/playlists")
def create_playlist(body: PlaylistBody, db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    p = Playlist(user_id=user.id, **body.model_dump())
    db.add(p)
    db.commit()
    return playlist_json(db, p)


@router.get("/playlists/{pid}")
def get_playlist(pid: int, db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    return playlist_json(db, _playlist(db, user, pid), True, user)


@router.patch("/playlists/{pid}")
def edit_playlist(pid: int, body: PlaylistBody, db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    p = _playlist(db, user, pid, write=True)
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    p.updated_at = datetime.now(timezone.utc)
    db.commit()
    return playlist_json(db, p)


@router.delete("/playlists/{pid}")
def delete_playlist(pid: int, db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    db.delete(_playlist(db, user, pid, write=True))
    db.commit()
    return {"ok": True}


class AddTracks(BaseModel):
    track_ids: list[int] = Field(max_length=5000)


@router.post("/playlists/{pid}/tracks")
def add_tracks(pid: int, body: AddTracks, db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
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
def remove_item(pid: int, item_id: int, db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    p = _playlist(db, user, pid, write=True)
    db.execute(delete(PlaylistItem).where(PlaylistItem.playlist_id == pid, PlaylistItem.id == item_id))
    p.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


class Reorder(BaseModel):
    item_ids: list[int]


@router.put("/playlists/{pid}/order")
def reorder(pid: int, body: Reorder, db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
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
            "art": serial.art_url("album", a.id) if a.art else None, "liked": a.id in liked,
            "peer": serial.peer(a.peer_id)}


@router.get("/sidebar")
def sidebar(db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
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
        games += [a for a in db.scalars(select(Album).where(Album.kind == "vgm", Album.shadowed.is_(False))
                                        .order_by(Album.added_at.desc()).limit(12))
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
        "books": [{"id": b.id, "title": b.title, "author": b.author, "art": serial.art_url("book", b.id) if b.art else None,
                   "progress": round(p.position / b.duration, 3) if b.duration else 0, "peer": serial.peer(b.peer_id)}
                  for b, p in books],
        "podcasts": [{"id": f.id, "title": f.title or f.url, "author": f.author, "art": f.image or None,
                      "new": f.id in fresh} for f in feeds],
        "stations": [saved_json(st) for st in stations],
    }

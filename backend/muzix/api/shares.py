"""Sharing (2026-11-16). "Copy link" is the page's own address, for those with an account here (the
web app builds it). A public link, this module, lets anyone listen in a browser without one: a song,
an album, a playlist, an artist's albums, a podcast or an episode of this server's own library. What
another library of the Library Network shares is never handed on: it isn't ours to give.

Listen only: there's nothing to download. A link runs out after a day, a week, a month or never, as
its maker chose. It stops when they take it away, when an admin turns sharing off for them, or when
what it shows is no longer theirs to see (their limits, hidden by an admin, gone from the library).

Its page, /s/<token>, is the web app's own, with the share's name and cover in the head for the
preview a chat app shows (og_page)."""

import html
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import db as database, serial, settings
from ..db import get_db
from ..lengths import display_duration
from ..models import Album, Artist, Episode, Feed, Playlist, PlaylistItem, Share, Track, User
from ..security import admin_user, current_user, viewing
from .library import album_order
from .proxy import relay
from .stream import audio

router = APIRouter(prefix="/api", tags=["shares"])

KINDS = ("track", "album", "playlist", "artist", "podcast", "episode")
DAYS = (1, 7, 30)               # how long a link lasts, as one is made; None: until it's taken away
MAX_EPISODES = 100              # a podcast's newest
KEEP_RUN_OUT = timedelta(days=30)    # a link that ran out stays in the lists that long, then goes
GONE = "This link has run out or was taken away"


class ShareBody(BaseModel):
    kind: str = Field(pattern="^(" + "|".join(KINDS) + ")$")
    id: int
    days: int | None = 7


def _utc(when: datetime | None) -> datetime | None:
    return when if when is None or when.tzinfo else when.replace(tzinfo=timezone.utc)


def run_out(sh: Share) -> bool:
    return sh.expires_at is not None and _utc(sh.expires_at) <= datetime.now(timezone.utc)


def may_share(u: User) -> bool:
    return u.is_admin or u.can_share


def base_url(request: Request | None = None) -> str:
    """Where the server is found from outside: its public address, else the one this request came to."""
    pub = (settings.get("public_url") or "").rstrip("/")
    return pub or (str(request.base_url).rstrip("/") if request is not None else "")


def _item(db: Session, kind: str, item_id: int, owner: User):
    """What a link shows, as the session's viewer may see it (None: not there for them)."""
    model = {"track": Track, "album": Album, "artist": Artist, "playlist": Playlist,
             "podcast": Feed, "episode": Episode}[kind]
    obj = db.get(model, item_id)
    if obj is None:
        return None
    if kind == "playlist" and obj.user_id != owner.id and not obj.public:
        return None
    if kind == "episode" and db.get(Feed, obj.feed_id) is None:
        return None
    return obj


def _theirs(kind: str, obj) -> bool:
    """It's another library's of the Library Network (or only there)."""
    if kind == "artist":
        return bool(obj.peer_only)
    return getattr(obj, "peer_id", None) is not None


def _cover(db: Session, kind: str, obj) -> str | None:
    if kind == "track":
        a = db.get(Album, obj.album_id) if obj.album_id else None
        return serial.art_url("album", a.id) if a is not None and a.art else None
    if kind == "album":
        return serial.art_url("album", obj.id) if obj.art else None
    if kind == "artist":
        return serial.art_url("artist", obj.id)
    if kind == "playlist":
        first = db.scalar(select(Album.id).join(Track, Track.album_id == Album.id)
                          .join(PlaylistItem, PlaylistItem.track_id == Track.id)
                          .where(PlaylistItem.playlist_id == obj.id, Album.art != "")
                          .order_by(PlaylistItem.position).limit(1))
        return serial.art_url("album", first) if first else None
    if kind == "podcast":
        return obj.image or None
    feed = db.get(Feed, obj.feed_id)
    return obj.image or (feed.image if feed else None) or None


def _names(db: Session, kind: str, obj) -> tuple[str, str]:
    """Its title and the line under it."""
    if kind == "track":
        return obj.title, obj.artist
    if kind == "album":
        return obj.title, " · ".join(x for x in (obj.artist_name, str(obj.year) if obj.year else "") if x)
    if kind == "artist":
        return obj.name, "Artist"
    if kind == "playlist":
        owner = db.get(User, obj.user_id)
        return obj.name, f"Playlist by {owner.username}" if owner else "Playlist"
    if kind == "podcast":
        return obj.title or obj.url, obj.author or "Podcast"
    feed = db.get(Feed, obj.feed_id)
    return obj.title, feed.title if feed else "Podcast"


def _path(db: Session, sh: Share) -> str | None:
    """Its page in the app, for those with an account."""
    if sh.kind == "track":
        t = db.get(Track, sh.item_id)
        return f"/album/{t.album_id}" if t is not None and t.album_id else None
    return {"album": f"/album/{sh.item_id}", "artist": f"/artist/{sh.item_id}", "playlist": f"/playlist/{sh.item_id}",
            "podcast": f"/podcasts/{sh.item_id}", "episode": f"/podcasts/episode/{sh.item_id}"}[sh.kind]


def share_json(db: Session, sh: Share, base: str, by: bool = False) -> dict:
    out = {"token": sh.token, "url": f"{base}/s/{sh.token}", "kind": sh.kind, "item_id": sh.item_id,
           "title": sh.title, "sub": sh.sub, "created_at": serial.iso(sh.created_at),
           "expires_at": serial.iso(sh.expires_at), "run_out": run_out(sh), "opened": sh.opened,
           "path": _path(db, sh)}
    if by:
        out["by"] = sh.user.username if sh.user else ""
    return out


def _tidy(db: Session):
    """Links that ran out a while ago go."""
    db.execute(delete(Share).where(Share.expires_at.is_not(None),
                                   Share.expires_at < datetime.now(timezone.utc) - KEEP_RUN_OUT))
    db.commit()


# ---------------------------------------------------------------- making and keeping links

@router.post("/shares")
def make(body: ShareBody, request: Request, db: Session = Depends(get_db, scope="function"), user: User = Depends(current_user)):
    if not may_share(user):
        raise HTTPException(403, "An admin has turned links off for your account")
    if body.days is not None and body.days not in DAYS:
        raise HTTPException(400, f"A link lasts {', '.join(map(str, DAYS))} days, or until it's taken away")
    obj = _item(db, body.kind, body.id, user)
    if obj is None:
        raise HTTPException(404, "That isn't here")
    if _theirs(body.kind, obj):
        raise HTTPException(400, "This is in a friend's library: only your own music can be shared with a link")
    title, sub = _names(db, body.kind, obj)
    expires = datetime.now(timezone.utc) + timedelta(days=body.days) if body.days else None
    sh = Share(token=secrets.token_urlsafe(12), user_id=user.id, kind=body.kind, item_id=body.id,
               title=title[:512], sub=sub[:512], expires_at=expires)
    db.add(sh)
    db.commit()
    return share_json(db, sh, base_url(request))


@router.get("/shares")
def mine(request: Request, db: Session = Depends(get_db, scope="function"), user: User = Depends(current_user)):
    _tidy(db)
    rows = db.scalars(select(Share).where(Share.user_id == user.id).order_by(Share.created_at.desc())).all()
    return [share_json(db, sh, base_url(request)) for sh in rows]


@router.delete("/shares/{token}")
def take_away(token: str, db: Session = Depends(get_db, scope="function"), user: User = Depends(current_user)):
    sh = db.get(Share, token)
    if sh is not None and (sh.user_id == user.id or user.is_admin):
        db.delete(sh)
        db.commit()
    return {"ok": True}


@router.get("/admin/shares", dependencies=[Depends(admin_user)])
def everyones(request: Request, db: Session = Depends(get_db, scope="function")):
    _tidy(db)
    rows = db.scalars(select(Share).order_by(Share.created_at.desc())).all()
    return [share_json(db, sh, base_url(request), by=True) for sh in rows]


# ---------------------------------------------------------------- the public link

def _open(db: Session, token: str, request: Request):
    """The share and what it shows, as its maker sees this server's own library."""
    sh = db.get(Share, token)
    if sh is None or run_out(sh) or sh.user is None or not may_share(sh.user):
        raise HTTPException(404, GONE)
    viewing(request, sh.user)
    request.state.network = False               # this server's own library only
    obj = _item(db, sh.kind, sh.item_id, sh.user)
    if obj is None or _theirs(sh.kind, obj):
        raise HTTPException(404, "What this link showed isn't here any more")
    return sh, obj


def _songs(db: Session, tracks: list[Track]) -> list[dict]:
    covered = set(db.scalars(select(Album.id).where(Album.id.in_({t.album_id for t in tracks if t.album_id}),
                                                    Album.art != ""))) if tracks else set()
    return [{"id": t.id, "title": t.title or "Untitled", "artist": t.artist, "album": t.album,
             "duration": display_duration(t), "disc": t.disc_no, "no": t.track_no,
             "art": serial.art_url("album", t.album_id) if t.album_id in covered else None} for t in tracks]


@router.get("/s/{token}")
def shared(token: str, request: Request, db: Session = Depends(get_db, scope="function")):
    """What a public link shows: its songs, an artist's albums, or a podcast's episodes."""
    sh, obj = _open(db, token, request)
    title, sub = _names(db, sh.kind, obj)
    out = {"kind": sh.kind, "title": title, "sub": sub, "art": _cover(db, sh.kind, obj), "by": sh.user.username,
           "expires_at": serial.iso(sh.expires_at), "site": settings.get("site_name") or "Muzix"}
    if sh.kind == "track":
        out["tracks"] = _songs(db, [obj])
    elif sh.kind == "album":
        out["tracks"] = _songs(db, db.scalars(select(Track).where(Track.album_id == obj.id).order_by(*album_order())).all())
    elif sh.kind == "playlist":
        out["description"] = obj.description
        out["tracks"] = _songs(db, db.scalars(select(Track).join(PlaylistItem, PlaylistItem.track_id == Track.id)
                                              .where(PlaylistItem.playlist_id == obj.id)
                                              .order_by(PlaylistItem.position)).all())
    elif sh.kind == "artist":
        albums = db.scalars(select(Album).where(Album.artist_id == obj.id).order_by(Album.year.desc(), Album.title)).all()
        songs = db.scalars(select(Track).where(Track.album_id.in_([a.id for a in albums])).order_by(*album_order())).all()
        by_album: dict[int, list[Track]] = {}
        for t in songs:
            by_album.setdefault(t.album_id, []).append(t)
        out["albums"] = [{"id": a.id, "title": a.title, "year": a.year,
                          "art": serial.art_url("album", a.id) if a.art else None,
                          "tracks": _songs(db, by_album[a.id])} for a in albums if a.id in by_album]
    else:
        feed = obj if sh.kind == "podcast" else db.get(Feed, obj.feed_id)
        eps = (db.scalars(select(Episode).where(Episode.feed_id == obj.id).order_by(Episode.published.desc())
                          .limit(MAX_EPISODES)).all() if sh.kind == "podcast" else [obj])
        out["description"] = feed.description if sh.kind == "podcast" else obj.description
        out["episodes"] = [{"id": e.id, "title": e.title, "published": serial.iso(e.published), "duration": e.duration,
                            "art": e.image or feed.image or None} for e in eps]
    sh.opened += 1
    db.commit()
    return out


def _holds(db: Session, sh: Share, obj, t: Track) -> bool:
    if sh.kind == "track":
        return t.id == obj.id
    if sh.kind == "album":
        return t.album_id == obj.id
    if sh.kind == "artist":
        a = db.get(Album, t.album_id) if t.album_id else None
        return a is not None and a.artist_id == obj.id
    if sh.kind == "playlist":
        return db.scalar(select(PlaylistItem.id).where(PlaylistItem.playlist_id == obj.id,
                                                       PlaylistItem.track_id == t.id).limit(1)) is not None
    return False


@router.get("/s/{token}/track/{track_id}")
def shared_song(token: str, track_id: int, request: Request, t: float = 0.0, db: Session = Depends(get_db, scope="function")):
    """A song of a public link: as it is, converted when a browser can't play it, or rendered (chiptunes)."""
    sh, obj = _open(db, token, request)
    tr = db.get(Track, track_id)
    if tr is None or tr.peer_id is not None or not _holds(db, sh, obj, tr):
        raise HTTPException(404, "No such song here")
    song = (tr.path, tr.format, tr.codec, tr.sample_rate, tr.bit_depth, tr.subsong, tr.duration, dict(tr.extra or {}))
    db.close()                      # a render can take a while: not on a database connection
    return audio(*song, q="original", t=max(0.0, t))


@router.get("/s/{token}/episode/{episode_id}")
async def shared_episode(token: str, episode_id: int, request: Request, db: Session = Depends(get_db, scope="function")):
    sh, obj = _open(db, token, request)
    e = db.get(Episode, episode_id)
    if e is None or (sh.kind == "episode" and e.id != obj.id) or (sh.kind == "podcast" and e.feed_id != obj.id) \
            or sh.kind not in ("podcast", "episode"):
        raise HTTPException(404, "No such episode here")
    if e.local_path and os.path.exists(e.local_path):
        return FileResponse(e.local_path)
    return await relay(e.audio_url, request)


# ---------------------------------------------------------------- the link's preview

_KIND = {"track": ("music.song", "Song"), "album": ("music.album", "Album"), "playlist": ("music.playlist", "Playlist"),
         "artist": ("profile", "Artist"), "podcast": ("website", "Podcast"), "episode": ("website", "Podcast episode")}


def og_page(token: str, index: str, request: Request) -> str:
    """The web app's page with the share's name and cover in its head: a chat app shows them as the
    link's preview. A link that's gone gets the page as it is (it says so itself)."""
    with database.session() as s:
        sh = s.get(Share, token)
        if sh is None or run_out(sh):
            return index
        obj = _item(s, sh.kind, sh.item_id, sh.user) if sh.user else None
        if obj is None:
            return index
        title, sub = _names(s, sh.kind, obj)
        cover = _cover(s, sh.kind, obj)
        og, kind = _KIND[sh.kind]
    base = base_url(request)
    site = settings.get("site_name") or "Muzix"
    if cover and cover.startswith("/"):
        cover = f"{base}{cover}{'&' if '?' in cover else '?'}s=600"
    esc = html.escape
    tags = [f'<meta property="og:type" content="{og}" />', f'<meta property="og:title" content="{esc(title)}" />',
            f'<meta property="og:description" content="{esc(" · ".join(x for x in (kind, sub) if x))}" />',
            f'<meta property="og:site_name" content="{esc(site)}" />',
            f'<meta property="og:url" content="{esc(f"{base}/s/{token}")}" />',
            '<meta name="robots" content="noindex" />', '<meta name="twitter:card" content="summary" />']
    if cover:
        tags.append(f'<meta property="og:image" content="{esc(cover)}" />')
    page = re.sub(r"<title>.*?</title>", lambda _: f"<title>{esc(title)} · {esc(site)}</title>", index, count=1, flags=re.DOTALL)
    return page.replace("</head>", "    " + "\n    ".join(tags) + "\n  </head>", 1)

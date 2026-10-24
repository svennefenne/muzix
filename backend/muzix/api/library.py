import os
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from .. import art, serial
from ..db import get_db
from ..models import Album, Artist, Book, Like, PlayEvent, Track, User
from ..security import current_user

router = APIRouter(prefix="/api", tags=["library"])
ALBUM_SORTS = {
    "added": (Album.added_at.desc(),),
    "name": (func.lower(Album.title),),
    "artist": (func.lower(Album.artist_name), Album.year, func.lower(Album.title)),
    "year": (Album.year.desc(), func.lower(Album.title)),
    # oldest first, albums without a year at the end
    "year_asc": (case((Album.year > 0, 0), else_=1), Album.year, func.lower(Album.title)),
    "tracks": (Album.track_count.desc(), func.lower(Album.title)),
}
GENRE_SORTS = {"albums": "n DESC", "name": "lower(genre)", "artists": "a DESC, n DESC"}


def plays_by(column, user: User):
    """(id, plays) for this user's play history, grouped by a track column."""
    return (select(column.label("ref"), func.count().label("plays"))
            .join(PlayEvent, PlayEvent.track_id == Track.id)
            .where(PlayEvent.user_id == user.id).group_by(column).subquery())


def liked(db: Session, user: User, kind: str) -> set[int]:
    return set(db.scalars(select(Like.item_id).where(Like.user_id == user.id, Like.item_type == kind)))


def artist_tags(db: Session, artist_ids) -> dict:
    ids = {i for i in artist_ids if i}
    if not ids:
        return {}
    return {a.id: [t[0] for t in (a.tags or [])[:6]] + ([a.genre] if a.genre else [])
            for a in db.scalars(select(Artist).where(Artist.id.in_(ids)))}


def tracks_json(db: Session, user: User, tracks: list[Track]) -> list[dict]:
    lk = liked(db, user, "track")
    tags = artist_tags(db, (t.artist_id for t in tracks))
    return [serial.track(t, lk, tags) for t in tracks]


def album_order():
    return (Track.disc_no, Track.track_no, Track.subsong, func.lower(Track.title))


# ---------------------------------------------------------------- home & browsing

@router.get("/home")
def home(db: Session = Depends(get_db), user: User = Depends(current_user)):
    lk = liked(db, user, "album")
    recent = db.scalars(select(Album).where(Album.kind == "music").order_by(Album.added_at.desc()).limit(14))
    played_ids = [r[0] for r in db.execute(text(
        "SELECT t.album_id, max(p.played_at) m FROM plays p JOIN tracks t ON t.id = p.track_id "
        "WHERE p.user_id = :u AND t.album_id IS NOT NULL GROUP BY t.album_id ORDER BY m DESC LIMIT 14"),
        {"u": user.id})]
    played = {a.id: a for a in db.scalars(select(Album).where(Album.id.in_(played_ids)))}
    top_ids = [r[0] for r in db.execute(text(
        "SELECT t.album_id, count(*) c FROM plays p JOIN tracks t ON t.id = p.track_id "
        "WHERE p.user_id = :u AND t.album_id IS NOT NULL GROUP BY t.album_id ORDER BY c DESC LIMIT 14"),
        {"u": user.id})]
    top = {a.id: a for a in db.scalars(select(Album).where(Album.id.in_(top_ids)))}
    rnd = db.scalars(select(Album).where(Album.kind == "music", Album.art != "")
                     .order_by(func.random()).limit(14))
    vgm = db.scalars(select(Album).where(Album.kind == "vgm").order_by(func.random()).limit(14))
    stats = db.execute(text(
        "SELECT (SELECT count(*) FROM tracks WHERE kind='music'), (SELECT count(*) FROM albums WHERE kind='music'),"
        " (SELECT count(*) FROM artists), (SELECT count(*) FROM tracks WHERE kind='vgm'),"
        " (SELECT coalesce(sum(duration),0) FROM tracks WHERE kind='music')")).one()
    return {
        "stats": {"tracks": stats[0], "albums": stats[1], "artists": stats[2], "vgm_tracks": stats[3],
                  "hours": round(stats[4] / 3600)},
        "recently_played": [serial.album(played[i], lk) for i in played_ids if i in played],
        "recently_added": [serial.album(a, lk) for a in recent],
        "most_played": [serial.album(top[i], lk) for i in top_ids if i in top],
        "rediscover": [serial.album(a, lk) for a in rnd],
        "vgm": [serial.album(a, lk) for a in vgm],
        "genres": genres(db, user, limit=12),
    }


@router.get("/genres")
def genres(db: Session = Depends(get_db), user: User = Depends(current_user), limit: int = 100,
           sort: str = "albums"):
    order = GENRE_SORTS.get(sort, GENRE_SORTS["albums"])
    rows = db.execute(text(
        "SELECT genre, count(*) n, sum(track_count) t, count(DISTINCT artist_id) a FROM albums "
        f"WHERE kind='music' AND genre != '' GROUP BY genre ORDER BY {order} LIMIT :l"), {"l": limit}).all()
    out = []
    for g, n, t, a in rows:
        arts = db.scalars(select(Album.id).where(Album.genre == g, Album.art != "")
                          .order_by(func.random()).limit(4)).all()
        out.append({"name": g, "albums": n, "tracks": t, "artists": a,
                    "art": [serial.art_url("album", i) for i in arts]})
    return out


@router.get("/albums")
def albums(db: Session = Depends(get_db), user: User = Depends(current_user),
           kind: str = "music", genre: str | None = None, artist_id: int | None = None,
           system: str | None = None, liked_only: bool = False, sort: str = "added",
           limit: int = Query(60, le=500), offset: int = 0):
    q = select(Album)
    if kind != "all":
        q = q.where(Album.kind == kind)
    if genre:
        q = q.where(Album.genre == genre)
    if artist_id:
        q = q.where(Album.artist_id == artist_id)
    if system:
        q = q.where(Album.id.in_(select(Track.album_id).where(
            func.json_extract(Track.extra, "$.system") == system)))
    if liked_only:
        q = q.where(Album.id.in_(select(Like.item_id).where(Like.user_id == user.id, Like.item_type == "album")))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    if sort == "played":
        played = plays_by(Track.album_id, user)
        q = q.outerjoin(played, played.c.ref == Album.id)
        order = (func.coalesce(played.c.plays, 0).desc(), Album.added_at.desc())
    else:
        order = ALBUM_SORTS.get(sort, ALBUM_SORTS["added"])
    items = db.scalars(q.order_by(*order, Album.id).limit(limit).offset(offset))
    lk = liked(db, user, "album")
    return {"total": total, "items": [serial.album(a, lk) for a in items]}


@router.get("/albums/{album_id}")
def album(album_id: int, db: Session = Depends(get_db), user: User = Depends(current_user),
          limit: int = Query(1000, le=5000), offset: int = 0):
    """An album with its tracks (paged: VGM collections can hold thousands of files)."""
    a = db.get(Album, album_id)
    if a is None:
        raise HTTPException(404, "No such album")
    tracks = db.scalars(select(Track).where(Track.album_id == album_id).order_by(*album_order())
                        .limit(limit).offset(offset)).all()
    more = []
    if a.artist_id:
        more = db.scalars(select(Album).where(Album.artist_id == a.artist_id, Album.id != a.id)
                          .order_by(Album.year.desc()).limit(12)).all()
    lk = liked(db, user, "album")
    colors = []
    if a.art and not a.art.startswith("embedded:"):
        colors = art.dominant_colors(a.art)
    return {**serial.album(a, lk), "tracks": tracks_json(db, user, tracks), "offset": offset,
            "more": [serial.album(m, lk) for m in more], "colors": colors,
            "folder": a.folder, "artist_tags": artist_tags(db, [a.artist_id]).get(a.artist_id, [])}


@router.get("/artists")
def artists(db: Session = Depends(get_db), user: User = Depends(current_user),
            genre: str | None = None, liked_only: bool = False, sort: str = "name",
            limit: int = Query(100, le=500), offset: int = 0):
    # through the albums, so an artist shows up in every genre they have albums in
    counts = select(Album.artist_id, func.count().label("n"), func.max(Album.added_at).label("added")) \
        .where(Album.kind == "music")
    if genre:
        counts = counts.where(Album.genre == genre)
    counts = counts.group_by(Album.artist_id).subquery()
    q = select(Artist, counts.c.n).join(counts, counts.c.artist_id == Artist.id)
    if liked_only:
        q = q.where(Artist.id.in_(select(Like.item_id).where(Like.user_id == user.id, Like.item_type == "artist")))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    if sort == "played":
        played = plays_by(Track.artist_id, user)
        q = q.outerjoin(played, played.c.ref == Artist.id)
        order = (func.coalesce(played.c.plays, 0).desc(), func.lower(Artist.name))
    else:
        order = {"albums": (counts.c.n.desc(), func.lower(Artist.name)),
                 "added": (counts.c.added.desc(),)}.get(sort, (func.lower(Artist.name),))
    rows = db.execute(q.order_by(*order, Artist.id).limit(limit).offset(offset)).all()
    lk = liked(db, user, "artist")
    return {"total": total, "items": [serial.artist(a, lk, n) for a, n in rows]}


@router.get("/artists/{artist_id}")
def artist(artist_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    a = db.get(Artist, artist_id)
    if a is None:
        raise HTTPException(404, "No such artist")
    albums_ = db.scalars(select(Album).where(Album.artist_id == artist_id)
                         .order_by(Album.year.desc(), Album.title)).all()
    top_ids = [r[0] for r in db.execute(text(
        "SELECT p.track_id, count(*) c FROM plays p JOIN tracks t ON t.id = p.track_id "
        "WHERE t.artist_id = :a GROUP BY p.track_id ORDER BY c DESC LIMIT 10"), {"a": artist_id})]
    top = db.scalars(select(Track).where(Track.id.in_(top_ids))).all()
    top.sort(key=lambda t: top_ids.index(t.id))
    if len(top) < 10:
        extra = db.scalars(select(Track).where(Track.artist_id == artist_id, Track.id.notin_(top_ids))
                           .order_by(func.random()).limit(10 - len(top))).all()
        top += extra
    lk = liked(db, user, "album")
    return {**serial.artist(a, liked(db, user, "artist"), len(albums_)),
            "albums": [serial.album(x, lk) for x in albums_],
            "top_tracks": tracks_json(db, user, top)}


@router.get("/tracks")
def tracks(ids: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    want = [int(x) for x in ids.split(",") if x.strip().isdigit()][:1000]
    rows = {t.id: t for t in db.scalars(select(Track).where(Track.id.in_(want)))}
    return tracks_json(db, user, [rows[i] for i in want if i in rows])


@router.get("/random")
def random_tracks(db: Session = Depends(get_db), user: User = Depends(current_user),
                  kind: str = "music", genre: str | None = None, artist_id: int | None = None,
                  album_id: int | None = None, system: str | None = None, n: int = Query(50, le=500)):
    q = select(Track)
    if kind != "all":
        q = q.where(Track.kind == kind)
    if genre:
        q = q.where(Track.genre == genre)
    if artist_id:
        q = q.where(Track.artist_id == artist_id)
    if album_id:
        q = q.where(Track.album_id == album_id)
    if system:
        q = q.where(func.json_extract(Track.extra, "$.system") == system)
    return tracks_json(db, user, db.scalars(q.order_by(func.random()).limit(n)).all())


# ---------------------------------------------------------------- search

def fts_query(q: str) -> str:
    words = re.findall(r"\w+", q, re.UNICODE)
    return " ".join(f'"{w}"*' for w in words[:8])


@router.get("/search")
def search(q: str, db: Session = Depends(get_db), user: User = Depends(current_user),
           limit: int = Query(20, le=100)):
    fq = fts_query(q)
    if not fq:
        return {"artists": [], "albums": [], "tracks": [], "books": []}
    out = {}
    for kind, model in (("artist", Artist), ("album", Album), ("track", Track)):
        ids = [int(r[0]) for r in db.execute(text(
            "SELECT ref FROM search_fts WHERE search_fts MATCH :q AND kind = :k ORDER BY rank LIMIT :l"),
            {"q": fq, "k": kind, "l": limit})]
        rows = {x.id: x for x in db.scalars(select(model).where(model.id.in_(ids)))}
        out[kind] = [rows[i] for i in ids if i in rows]
    like = f"%{q.strip()}%"
    books = db.scalars(select(Book).where(Book.title.ilike(like) | Book.author.ilike(like) | Book.series.ilike(like))
                       .order_by(func.lower(Book.title)).limit(min(limit, 10)))
    return {
        "artists": [serial.artist(a, liked(db, user, "artist")) for a in out["artist"]],
        "albums": [serial.album(a, liked(db, user, "album")) for a in out["album"]],
        "tracks": tracks_json(db, user, out["track"]),
        "books": [{"id": b.id, "title": b.title, "author": b.author, "series": b.series,
                   "art": f"/api/art/book/{b.id}" if b.art else None} for b in books],
    }


# ---------------------------------------------------------------- VGM

@router.get("/vgm/systems")
def vgm_systems(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.execute(text(
        "SELECT coalesce(json_extract(extra, '$.system'), ''), count(*), count(DISTINCT album_id) "
        "FROM tracks WHERE kind = 'vgm' GROUP BY 1 ORDER BY 2 DESC")).all()
    return [{"system": s or "Game soundtracks", "tracks": n, "albums": a} for s, n, a in rows]


# ---------------------------------------------------------------- art

def _send(data, ident, size):
    if not data:
        return Response(status_code=404)
    path = art.resized(data, ident, size)
    if not path:
        return Response(status_code=404)
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "public, max-age=604800"})


def _resolved(ref: str, db: Session):
    """The art reference plus the track path it may need, so the session can be released
    before the (slow) image work: a page of covers would otherwise use up the connections."""
    path = None
    if ref.startswith("embedded:"):
        t = db.get(Track, int(ref.split(":", 1)[1]))
        path = t.path if t else None
    db.close()
    return ref, (lambda _id: path)


@router.get("/art/album/{album_id}")
def album_art(album_id: int, s: int = 300, db: Session = Depends(get_db)):
    a = db.get(Album, album_id)
    if a is None or not a.art:
        return Response(status_code=404)
    ref, path_of = _resolved(a.art, db)
    data, ident = art.source_bytes(ref, path_of)
    return _send(data, ident, s)


@router.get("/art/artist/{artist_id}")
def artist_art(artist_id: int, s: int = 300, db: Session = Depends(get_db)):
    a = db.get(Artist, artist_id)
    if a is None:
        return Response(status_code=404)
    if a.image and os.path.exists(a.image):
        data, ident = art.source_bytes(a.image)
        return _send(data, ident, s)
    alb = db.scalar(select(Album).where(Album.artist_id == artist_id, Album.art != "")
                    .order_by(Album.year).limit(1))
    if alb is None:
        return Response(status_code=404)
    ref, path_of = _resolved(alb.art, db)
    data, ident = art.source_bytes(ref, path_of)
    return _send(data, ident, s)

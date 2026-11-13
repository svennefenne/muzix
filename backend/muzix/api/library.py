import os
import random
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import case, delete, func, or_, select, text, true
from sqlalchemy.orm import Session

from .. import art, lyrics, mirror, serial, tagging
from ..db import get_db, get_db_with_copies
from ..models import (Album, Artist, Book, Episode, EpisodeProgress, Feed, FilePlaylist, FilePlaylistItem, Like, PlayEvent,
                      RecentSearch, Station, Subscription, Track, User)
from ..security import current_user, optional_user
from .podcasts import episode_json, whats_new
from .radio import saved_json

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
GENRE_SORTS = {"albums": ("n",), "name": ("name",), "artists": ("a", "n")}
NO_SYSTEM = "Game soundtracks"   # VGM without a chip system: ordinary soundtrack albums


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


def on_system(system: str):
    """Tracks from one VGM system; NO_SYSTEM stands for those without one."""
    return func.coalesce(func.json_extract(Track.extra, "$.system"), "") == ("" if system == NO_SYSTEM else system)


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
    music, seconds = db.execute(select(func.count(), func.coalesce(func.sum(Track.duration), 0))
                                .where(Track.kind == "music")).one()
    return {
        "stats": {"tracks": music, "albums": db.scalar(select(func.count()).select_from(Album).where(Album.kind == "music")),
                  "artists": db.scalar(select(func.count()).select_from(Artist)),
                  "vgm_tracks": db.scalar(select(func.count()).select_from(Track).where(Track.kind == "vgm")),
                  "hours": round(seconds / 3600)},
        "recently_played": [serial.album(played[i], lk) for i in played_ids if i in played],
        "recently_added": [serial.album(a, lk) for a in recent],
        "most_played": [serial.album(top[i], lk) for i in top_ids if i in top],
        "rediscover": [serial.album(a, lk) for a in rnd],
        "vgm": [serial.album(a, lk) for a in vgm],
        "genres": genres(db, user, limit=12),
        **whats_new(db, user),
    }


@router.get("/genres")
def genres(db: Session = Depends(get_db), user: User = Depends(current_user), limit: int = 100,
           sort: str = "albums"):
    n, t, a = func.count().label("n"), func.sum(Album.track_count).label("t"), func.count(Album.artist_id.distinct()).label("a")
    order = {"n": n.desc(), "a": a.desc(), "name": func.lower(Album.genre)}
    rows = db.execute(select(Album.genre, n, t, a).where(Album.kind == "music", Album.genre != "")
                      .group_by(Album.genre).order_by(*(order[k] for k in GENRE_SORTS.get(sort, GENRE_SORTS["albums"])))
                      .limit(limit)).all()
    out = []
    for g, n, t, a in rows:
        arts = db.scalars(select(Album.id).where(Album.genre == g, Album.art != "")
                          .order_by(func.random()).limit(4)).all()
        out.append({"name": g, "albums": n, "tracks": t, "artists": a,
                    "art": [serial.art_url("album", i) for i in arts]})
    return out


def _albums_query(user: User, kind: str, genre: str | None, artist_id: int | None, system: str | None,
                  liked_only: bool, what=Album):
    q = select(what)
    if kind != "all":
        q = q.where(Album.kind == kind)
    if genre:
        q = q.where(Album.genre == genre)
    if artist_id:
        q = q.where(Album.artist_id == artist_id)
    if system:
        q = q.where(Album.id.in_(select(Track.album_id).where(on_system(system))))
    if liked_only:
        q = q.where(Album.id.in_(select(Like.item_id).where(Like.user_id == user.id, Like.item_type == "album")))
    return q


@router.get("/albums")
def albums(db: Session = Depends(get_db), user: User = Depends(current_user),
           kind: str = "music", genre: str | None = None, artist_id: int | None = None,
           system: str | None = None, liked_only: bool = False, sort: str = "added",
           limit: int = Query(60, le=500), offset: int = 0):
    q = _albums_query(user, kind, genre, artist_id, system, liked_only)
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
def album(album_id: int, db: Session = Depends(get_db_with_copies), user: User = Depends(current_user),
          limit: int = Query(1000, le=5000), offset: int = 0):
    """An album with its tracks (paged: VGM collections can hold thousands of files)."""
    a = db.get(Album, album_id)
    if a is None:
        raise HTTPException(404, "No such album")
    tracks = db.scalars(select(Track).where(Track.album_id == album_id).order_by(*album_order())
                        .limit(limit).offset(offset)).all()
    more = []
    if a.artist_id:
        more = db.scalars(select(Album).where(Album.artist_id == a.artist_id, Album.id != a.id,
                                              Album.shadowed.is_(False)).order_by(Album.year.desc()).limit(12)).all()
    lk = liked(db, user, "album")
    colors = mirror.colors(a.art)
    return {**serial.album(a, lk), "tracks": tracks_json(db, user, tracks), "offset": offset,
            "more": [serial.album(m, lk) for m in more], "colors": colors,
            "folder": "" if a.peer_id else a.folder, "artist_tags": artist_tags(db, [a.artist_id]).get(a.artist_id, [])}


def _artists_query(user: User, genre: str | None, liked_only: bool):
    # through the albums, so an artist shows up in every genre they have albums in
    counts = select(Album.artist_id, func.count().label("n"), func.max(Album.added_at).label("added")) \
        .where(Album.kind == "music")
    if genre:
        counts = counts.where(Album.genre == genre)
    counts = counts.group_by(Album.artist_id).subquery()
    q = select(Artist, counts.c.n).join(counts, counts.c.artist_id == Artist.id)
    if liked_only:
        q = q.where(Artist.id.in_(select(Like.item_id).where(Like.user_id == user.id, Like.item_type == "artist")))
    return q, counts


@router.get("/artists")
def artists(db: Session = Depends(get_db), user: User = Depends(current_user),
            genre: str | None = None, liked_only: bool = False, sort: str = "name",
            limit: int = Query(100, le=500), offset: int = 0):
    q, counts = _artists_query(user, genre, liked_only)
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


def initial(name: str) -> str:
    """What a name is listed under by its first letter: "#" for digits and signs (they sort first),
    A to Z, and "…" for other letters (Å, Ä, Ö, other scripts: they sort after Z)."""
    c = (name or "").strip()[:1].upper()
    return c if "A" <= c <= "Z" else "…" if c.isalpha() else "#"


@router.get("/letters")
def letters(db: Session = Depends(get_db), user: User = Depends(current_user), of: str = "albums",
            kind: str = "music", genre: str | None = None, artist_id: int | None = None, liked_only: bool = False,
            sort: str = "name"):
    """Where the names under each first letter run in a list sorted by name (/api/albums or
    /api/artists with the same filters): [{letter, offset}] for each run, in the list's order, for
    jumping to a letter. "#" can run twice: most signs sort before A, a few ({, |, ~) after Z."""
    if of == "artists":
        q, _ = _artists_query(user, genre, liked_only)
        names = db.scalars(q.with_only_columns(Artist.name).order_by(func.lower(Artist.name), Artist.id))
    else:
        column = Album.artist_name if sort == "artist" else Album.title
        q = _albums_query(user, kind, genre, artist_id, None, liked_only, column)
        names = db.scalars(q.order_by(*ALBUM_SORTS["artist" if sort == "artist" else "name"], Album.id))
    out = []
    for i, name in enumerate(names):
        letter = initial(name)
        if not out or out[-1]["letter"] != letter:
            out.append({"letter": letter, "offset": i})
    return out


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
    # album, EP or single: its guessed albums looked up at MusicBrainz, once, in the background (releases.py)
    from .. import releases
    if releases.unchecked(db, artist_id):
        releases.check_artist(artist_id)
    return {**serial.artist(a, liked(db, user, "artist"), len(albums_)),
            "tag_groups": tagging.groups(db, a),
            "albums": [serial.album(x, lk) for x in albums_],
            "top_tracks": tracks_json(db, user, top),
            "checking": releases.checking(artist_id)}     # the page asks again until it's done


@router.get("/tracks")
def tracks(ids: str, db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    want = [int(x) for x in ids.split(",") if x.strip().isdigit()][:1000]
    rows = {t.id: t for t in db.scalars(select(Track).where(Track.id.in_(want)))}
    return tracks_json(db, user, [rows[i] for i in want if i in rows])


@router.get("/random")
def random_tracks(db: Session = Depends(get_db), user: User = Depends(current_user),
                  kind: str = "music", genre: str | None = None, artist_id: int | None = None,
                  album_id: int | None = None, system: str | None = None, tag: str | None = None,
                  n: int = Query(50, le=500)):
    q = select(Track)
    if kind != "all":
        q = q.where(Track.kind == kind)
    if genre:
        q = q.where(Track.genre == genre)
    if tag:
        q = q.where(tagged(tag))
    if artist_id:
        q = q.where(Track.artist_id == artist_id)
    if album_id:
        q = q.where(Track.album_id == album_id)
    if system:
        q = q.where(on_system(system))
    return tracks_json(db, user, db.scalars(q.order_by(func.random()).limit(n)).all())


# ---------------------------------------------------------------- lyrics

@router.get("/tracks/{track_id}/lyrics")
def track_lyrics(track_id: int, db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    """The song's lyrics, synced when there are times: {source, synced, lines: [{t, text}],
    instrumental, colors} (colors: the cover's, for the lyrics' background)."""
    t = db.get(Track, track_id)
    if t is None:
        raise HTTPException(404, "No such song")
    out = lyrics.for_track(db, t)
    db.commit()
    return out


# ---------------------------------------------------------------- autoplay

class Seeds(BaseModel):
    seeds: list[int]                # what played, the latest first
    exclude: list[int] = []         # already in the queue
    n: int = 10


def tag_profile(a: Artist) -> dict[str, float]:
    """An artist's genre tags weighed 0..1 (its strongest is 1). The genre folder counts as a weak
    tag, so artists Last.fm knows nothing about still meet the others in their folder."""
    tags = [(str(t).casefold(), float(w or 0)) for t, w in (a.tags or [])[:8]]
    top = max((w for _, w in tags), default=0) or 1
    out = {t: max(w / top, 0.05) for t, w in tags}
    if a.genre:
        out.setdefault(a.genre.casefold(), 0.3)
    return out


def likeness(p: dict[str, float], q: dict[str, float]) -> float:
    """How alike two tag profiles are (cosine): 1 for the same tags in the same proportions."""
    dot = sum(w * q[t] for t, w in p.items() if t in q)
    return dot / (sum(w * w for w in p.values()) * sum(w * w for w in q.values())) ** 0.5 if dot else 0.0


def pick_weighted(scored: list[tuple[float, int]], n: int, rnd: random.Random) -> list[int]:
    """n of the ids at random, the better scored the likelier (weighted sampling without replacement)."""
    return [i for _, i in sorted(((rnd.random() ** (1 / s), i) for s, i in scored if s > 0), reverse=True)[:n]]


@router.post("/similar")
def similar(body: Seeds, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Autoplay: songs like the seeds, to keep the music going once the queue runs out. For music,
    songs by the artists whose genre tags are most like the seeds' artists' (now and then the
    seeds' artists themselves); for game music, more from the same chips. Never anything queued,
    nor what this user played lately."""
    n = max(1, min(body.n, 50))
    seeds = [t for t in (db.get(Track, i, execution_options={"include_copies": True}) for i in body.seeds[:10]) if t]
    if not seeds:
        return []
    recent = db.scalars(select(PlayEvent.track_id).where(PlayEvent.user_id == user.id)
                        .order_by(PlayEvent.played_at.desc()).limit(300))
    skip = {*body.exclude[:5000], *body.seeds, *recent}
    fresh = Track.id.not_in(skip)
    music = [t for t in seeds if t.kind == "music"]
    if not music:
        chips = {("system", s) if (s := (t.extra or {}).get("system")) else ("format", t.format) for t in seeds}
        q = select(Track).where(Track.kind == "vgm", fresh,
                                or_(*(on_system(v) if k == "system" else Track.format == v for k, v in chips)))
        return tracks_json(db, user, db.scalars(q.order_by(func.random()).limit(n)).all())

    # what the seeds sound like: their artists' tags, the latest seed counting the most
    profile: dict[str, float] = {}
    for k, t in enumerate(music):
        if t.artist_id and (a := db.get(Artist, t.artist_id)):
            for tag, w in tag_profile(a).items():
                profile[tag] = profile.get(tag, 0) + w * 0.8 ** k
    rnd = random.Random()
    picked: list[Track] = []
    if profile:
        own = {t.artist_id for t in music}
        scored = sorted(((likeness(profile, tag_profile(a)) * (0.35 if a.id in own else 1), a.id)
                         for a in db.scalars(select(Artist))), reverse=True)[:40]
        artists = pick_weighted([(s * s, i) for s, i in scored], n, rnd)
        rows = db.execute(select(Track.id, Track.artist_id)
                          .where(Track.artist_id.in_(artists), Track.kind == "music", fresh)
                          .order_by(func.random())).all()
        first: dict[int, int] = {}
        for tid, aid in rows:
            first.setdefault(aid, tid)
        ids = [first[a] for a in artists if a in first]
        ids += [tid for tid, _ in rows if tid not in ids][:n - len(ids)]     # few alike artists: more songs each
        got = {t.id: t for t in db.scalars(select(Track).where(Track.id.in_(ids)))}
        picked = [got[i] for i in ids if i in got]
    # nothing tagged alike: the seeds' genre folders, then anything
    folders = {t.genre for t in music if t.genre}
    for where in ([Track.genre.in_(folders)] if folders else []) + [true()]:
        if len(picked) >= n:
            break
        have = [t.id for t in picked]
        picked += db.scalars(select(Track).where(Track.kind == "music", fresh, Track.id.not_in(have), where)
                             .order_by(func.random()).limit(n - len(picked))).all()
    rnd.shuffle(picked)
    return tracks_json(db, user, picked)


# ---------------------------------------------------------------- playlist files

def file_playlists(db: Session) -> list[dict]:
    """The playlist files the scan kept, with their song count and up to four covers."""
    out = []
    for pl in db.scalars(select(FilePlaylist).order_by(func.lower(FilePlaylist.name))):
        albums = db.scalars(select(Track.album_id).join(FilePlaylistItem, FilePlaylistItem.track_id == Track.id)
                            .where(FilePlaylistItem.playlist_id == pl.id, Track.album_id.is_not(None))
                            .group_by(Track.album_id).order_by(func.min(FilePlaylistItem.position)).limit(4)).all()
        count = db.scalar(select(func.count()).select_from(FilePlaylistItem).where(FilePlaylistItem.playlist_id == pl.id))
        out.append({"id": pl.id, "name": pl.name, "tracks": count, "entries": pl.entries,
                    "art": [serial.art_url("album", a) for a in albums], "peer": serial.peer(pl.peer_id)})
    return out


@router.get("/file-playlists")
def list_file_playlists(db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    return file_playlists(db)


@router.get("/file-playlists/{playlist_id}")
def file_playlist(playlist_id: int, db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    pl = db.get(FilePlaylist, playlist_id)
    if pl is None:
        raise HTTPException(404, "No such playlist")
    tracks = db.scalars(select(Track).join(FilePlaylistItem, FilePlaylistItem.track_id == Track.id)
                        .where(FilePlaylistItem.playlist_id == pl.id).order_by(FilePlaylistItem.position)).all()
    return {"id": pl.id, "name": pl.name, "path": "" if pl.peer_id else pl.path, "peer": serial.peer(pl.peer_id),
            "entries": pl.entries, "tracks": tracks_json(db, user, tracks)}


# ---------------------------------------------------------------- tags

def tag_artists(tag: str):
    """Artists showing this tag: one of the (up to eight) genre tags their page shows, one in a
    category shown apart (tagging.py), or their genre folder. Case doesn't matter, so the folder
    "Electronic" and the tag "electronic" meet."""
    return select(Artist.id).where(or_(
        text("EXISTS (SELECT 1 FROM json_each(artists.tags) j WHERE j.key < 8 "
             "AND casefold(json_extract(j.value, '$[0]')) = casefold(:tag))").bindparams(tag=tag),
        text("EXISTS (SELECT 1 FROM json_each(artists.other_tags) j "
             "WHERE casefold(json_extract(j.value, '$[0]')) = casefold(:tag))").bindparams(tag=tag),
        func.casefold(Artist.genre) == func.casefold(tag)))


def tagged(tag: str):
    """Tracks carrying a tag: by an artist with it, or filed in a genre folder of that name."""
    return or_(Track.artist_id.in_(tag_artists(tag)),
               Track.album_id.in_(select(Album.id).where(func.casefold(Album.genre) == func.casefold(tag))))


@router.get("/tags/{tag}")
def tag_page(tag: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """What a tag gathers: its artists (most albums first), albums and a song count."""
    album_ids = select(Track.album_id).where(tagged(tag), Track.album_id.is_not(None)).distinct()
    counts = select(Album.artist_id, func.count().label("n")).where(Album.id.in_(album_ids)) \
        .group_by(Album.artist_id).subquery()
    artists_ = db.execute(select(Artist, counts.c.n).join(counts, counts.c.artist_id == Artist.id)
                          .order_by(counts.c.n.desc(), func.lower(Artist.name)).limit(24)).all()
    albums_ = db.scalars(select(Album).where(Album.id.in_(album_ids))
                         .order_by(func.random()).limit(24)).all()
    lk_artists, lk_albums = liked(db, user, "artist"), liked(db, user, "album")
    return {"name": tag,
            "tracks": db.scalar(select(func.count()).select_from(Track).where(tagged(tag))),
            "albums": db.scalar(select(func.count()).select_from(album_ids.subquery())),
            "artists": [serial.artist(a, lk_artists, n) for a, n in artists_],
            "album_list": [serial.album(a, lk_albums) for a in albums_]}


@router.get("/tags/{tag}/tracks")
def tag_tracks(tag: str, db: Session = Depends(get_db), user: User = Depends(current_user),
               limit: int = Query(100, le=500), offset: int = 0):
    """A tag's songs, artist by artist and album by album."""
    q = select(Track).where(tagged(tag))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.outerjoin(Album, Album.id == Track.album_id)
                      .order_by(func.lower(Track.albumartist), Album.year, func.lower(Track.album), *album_order(), Track.id)
                      .limit(limit).offset(offset)).all()
    return {"total": total, "items": tracks_json(db, user, rows)}


# ---------------------------------------------------------------- search

def fts_query(q: str) -> str:
    words = re.findall(r"\w+", q, re.UNICODE)
    return " ".join(f'"{w}"*' for w in words[:8])


# what each section's search field finds (frontend/src/search/scope.ts); "": the library as before (older apps)
SCOPES = {
    "": {"artist", "album", "track", "book"},
    "all": {"artist", "album", "track", "book", "podcast", "episode", "station"},
    "music": {"artist", "album", "track"},
    "vgm": {"album", "track"},
    "audiobooks": {"book"},
    "podcasts": {"podcast", "episode"},
    "radio": {"station"},
}


@router.get("/search")
def search(q: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user),
           limit: int = Query(20, le=100), scope: str = ""):
    """What the search field finds in a section (scope): music, vgm, audiobooks, podcasts (the user's own and
    their episodes), radio (the user's saved stations), or all of them. Without a scope, music, games and
    audiobooks together, as the apps before sections asked."""
    if scope not in SCOPES:
        raise HTTPException(400, "No such section to search")
    wanted = SCOPES[scope]
    found = {"artists": [], "albums": [], "tracks": [], "books": [], "podcasts": [], "episodes": [], "stations": []}
    fq = fts_query(q)
    if not fq:
        return found
    # a section's own: VGM's games and tunes, or music's; everything when there's no section
    kind = scope if scope in ("music", "vgm") else None
    out = {}
    # what's hidden from this account isn't found: ask the index for more, to have enough of the rest
    ask = limit * 5 if getattr(request.state, "limits", None) else limit
    for what, model in (("artist", Artist), ("album", Album), ("track", Track)):
        if what not in wanted:
            out[what] = []
            continue
        own = f" AND ref IN (SELECT id FROM {model.__tablename__} WHERE kind = :kind)" if kind and what != "artist" else ""
        ids = [int(r[0]) for r in db.execute(text(
            f"SELECT ref FROM search_fts WHERE search_fts MATCH :q AND kind = :k{own} ORDER BY rank LIMIT :l"),
            {"q": fq, "k": what, "l": ask, "kind": kind})]
        rows = {x.id: x for x in db.scalars(select(model).where(model.id.in_(ids)))}
        out[what] = [rows[i] for i in ids if i in rows][:limit]
    found["artists"] = [serial.artist(a, liked(db, user, "artist")) for a in out["artist"]]
    found["albums"] = [serial.album(a, liked(db, user, "album")) for a in out["album"]]
    found["tracks"] = tracks_json(db, user, out["track"])
    like = f"%{q.strip()}%"
    few = min(limit, 10)
    if "book" in wanted:
        found["books"] = [_book_hit(b) for b in db.scalars(
            select(Book).where(Book.title.ilike(like) | Book.author.ilike(like) | Book.series.ilike(like))
            .order_by(func.lower(Book.title)).limit(few))]
    if "podcast" in wanted:
        mine = (Subscription.feed_id == Feed.id) & (Subscription.user_id == user.id)
        found["podcasts"] = [{"id": f.id, "title": f.title or f.url, "author": f.author, "image": f.image}
                             for f in db.scalars(select(Feed).join(Subscription, mine)
                                                 .where(Feed.title.ilike(like) | Feed.author.ilike(like))
                                                 .order_by(func.lower(Feed.title)).limit(few))]
        rows = db.execute(select(Episode, Feed, Subscription, EpisodeProgress)
                          .join(Feed, Feed.id == Episode.feed_id).join(Subscription, mine)
                          .outerjoin(EpisodeProgress, (EpisodeProgress.episode_id == Episode.id)
                                     & (EpisodeProgress.user_id == user.id))
                          .where(Episode.title.ilike(like))
                          .order_by(func.coalesce(Episode.published, Episode.added_at).desc()).limit(few)).all()
        found["episodes"] = [episode_json(e, prog, f, sub) for e, f, sub, prog in rows]
    if "station" in wanted:
        found["stations"] = [saved_json(st) for st in db.scalars(
            select(Station).where(Station.user_id == user.id, Station.name.ilike(like) | Station.tags.ilike(like))
            .order_by(func.lower(Station.name)).limit(few))]
    return found


def _book_hit(b: Book) -> dict:
    return {"id": b.id, "title": b.title, "author": b.author, "series": b.series,
            "art": serial.art_url("book", b.id) if b.art else None, "peer": serial.peer(b.peer_id)}


# ---------------------------------------------------------------- recent searches (Spotify's search history)

RECENT_KINDS = {"artist": Artist, "album": Album, "track": Track, "book": Book}
KEEP_RECENT = 30


class Picked(BaseModel):
    kind: str
    id: int


@router.get("/search/recent")
def recent_searches(db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    """What the user picked from search results lately, newest first, each as search gives it
    now: one that has since gone (or been hidden) drops out."""
    rows = db.execute(select(RecentSearch.kind, RecentSearch.item_id).where(RecentSearch.user_id == user.id)
                      .order_by(RecentSearch.at.desc()).limit(KEEP_RECENT)).all()
    found = {}
    for kind, model in RECENT_KINDS.items():
        ids = [i for k, i in rows if k == kind]
        found[kind] = {x.id: x for x in db.scalars(select(model).where(model.id.in_(ids)))} if ids else {}
    tracks = {t["id"]: t for t in tracks_json(db, user, list(found["track"].values()))}
    artists, albums = liked(db, user, "artist"), liked(db, user, "album")
    show = {"artist": lambda a: serial.artist(a, artists), "album": lambda a: serial.album(a, albums),
            "track": lambda t: tracks[t.id], "book": _book_hit}
    return [{"kind": kind, "item": show[kind](found[kind][i])} for kind, i in rows if i in found[kind]]


@router.post("/search/recent")
def remember_search(body: Picked, db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    if body.kind not in RECENT_KINDS:
        raise HTTPException(400, "Not something search finds")
    db.merge(RecentSearch(user_id=user.id, kind=body.kind, item_id=body.id, at=datetime.now(timezone.utc)))
    db.flush()
    oldest_kept = db.scalar(select(RecentSearch.at).where(RecentSearch.user_id == user.id)
                            .order_by(RecentSearch.at.desc()).offset(KEEP_RECENT - 1).limit(1))
    if oldest_kept is not None:
        db.execute(delete(RecentSearch).where(RecentSearch.user_id == user.id, RecentSearch.at < oldest_kept))
    db.commit()
    return {"ok": True}


@router.delete("/search/recent/{kind}/{item_id}")
def forget_search(kind: str, item_id: int, db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    db.execute(delete(RecentSearch).where(RecentSearch.user_id == user.id, RecentSearch.kind == kind,
                                          RecentSearch.item_id == item_id))
    db.commit()
    return {"ok": True}


@router.delete("/search/recent")
def clear_searches(db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    db.execute(delete(RecentSearch).where(RecentSearch.user_id == user.id))
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- VGM

@router.get("/vgm/systems")
def vgm_systems(db: Session = Depends(get_db), user: User = Depends(current_user)):
    system, n = func.coalesce(func.json_extract(Track.extra, "$.system"), ""), func.count()
    rows = db.execute(select(system, n, func.count(Track.album_id.distinct())).where(Track.kind == "vgm")
                      .group_by(system).order_by(n.desc())).all()
    return [{"system": s or NO_SYSTEM, "tracks": n, "albums": a} for s, n, a in rows]


# ---------------------------------------------------------------- art

def _send(data, ident, size):
    if not data:
        return Response(status_code=404)
    return _picture(art.resized(data, ident, size))


def _picture(path: str | None):
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
def album_art(album_id: int, s: int = 300, db: Session = Depends(get_db_with_copies),
              user: User | None = Depends(optional_user)):
    a = db.get(Album, album_id)
    if a is None or not a.art:
        return Response(status_code=404)
    if a.art.startswith(mirror.ROOT):           # another server's (the Library Network)
        ref = a.art
        db.close()
        return _picture(mirror.picture(ref, s))
    ref, path_of = _resolved(a.art, db)
    data, ident = art.source_bytes(ref, path_of)
    return _send(data, ident, s)


@router.get("/art/artist/{artist_id}")
def artist_art(artist_id: int, s: int = 300, db: Session = Depends(get_db_with_copies),
               user: User | None = Depends(optional_user)):
    a = db.get(Artist, artist_id)
    if a is None:
        return Response(status_code=404)
    if a.image.startswith(mirror.ROOT):
        ref = a.image
        db.close()
        return _picture(mirror.picture(ref, s))
    if a.image and os.path.exists(a.image):
        data, ident = art.source_bytes(a.image)
        return _send(data, ident, s)
    alb = db.scalar(select(Album).where(Album.artist_id == artist_id, Album.art != "")
                    .order_by(Album.year).limit(1))
    if alb is None:
        return Response(status_code=404)
    if alb.art.startswith(mirror.ROOT):
        ref = alb.art
        db.close()
        return _picture(mirror.picture(ref, s))
    ref, path_of = _resolved(alb.art, db)
    data, ident = art.source_bytes(ref, path_of)
    return _send(data, ident, s)

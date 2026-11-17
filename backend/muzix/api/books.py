from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import art, mirror, serial
from ..db import get_db, get_db_with_copies
from ..meta import tags
from ..models import Book, BookPart, BookProgress, User
from ..security import current_user, stream_user
from .library import _picture, _send
from .stream import stream_file, theirs

router = APIRouter(prefix="/api/books", tags=["audiobooks"])
SORTS = {
    "title": (func.lower(Book.title),),
    "author": (func.lower(Book.author), func.lower(Book.series), func.lower(Book.title)),
    "series": (Book.series == "", func.lower(Book.series), func.lower(Book.title)),
    "added": (Book.added_at.desc(),),
    "listened": (BookProgress.updated_at.is_(None), BookProgress.updated_at.desc(), func.lower(Book.title)),
    "length": (Book.duration.desc(),),
}


def book_json(b: Book, prog: BookProgress | None, full=False, parts=None):
    out = {"id": b.id, "title": b.title, "author": b.author, "narrator": b.narrator, "series": b.series,
           "series_part": b.series_part or "", "genre": b.genre or "", "language": b.language or "", "review": bool(b.review),
           "year": b.year, "duration": b.duration, "art": serial.art_url("book", b.id) if b.art else None,
           "position": prog.position if prog else 0, "finished": bool(prog and prog.finished),
           "updated_at": serial.iso(prog.updated_at) if prog else None, "peer": serial.peer(b.peer_id)}
    if full:
        out["description"] = b.description
        out["chapters"] = b.chapters or []
        out["parts"] = [{"position": p.position, "title": p.title, "duration": p.duration, "offset": p.offset,
                         "format": p.format, "stream": f"/api/books/{b.id}/parts/{p.position}/stream"}
                        for p in parts or []]
    return out


def _part_key(v: str) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 1e9


@router.get("/facets")
def facets(db: Session = Depends(get_db, scope="function"), user: User = Depends(current_user)):
    """The genres and languages the books have, with how many of each: the Audiobooks page's filters."""
    from ..audiobook.place import GENRES, NAMES
    genres = dict(db.execute(select(Book.genre, func.count()).group_by(Book.genre)).all())
    langs = dict(db.execute(select(Book.language, func.count()).group_by(Book.language)).all())
    order = {g: i for i, g in enumerate(GENRES)}
    return {"genres": [{"name": g or "Uncategorized", "value": g, "count": n}
                       for g, n in sorted(genres.items(), key=lambda x: (order.get(x[0] or "Uncategorized", 99), x[0] or ""))],
            "languages": [{"code": c, "name": NAMES.get(c, c.upper()) if c else "Unknown", "count": n}
                          for c, n in sorted(langs.items(), key=lambda x: (-x[1], x[0] or "~"))]}


@router.get("")
def books(db: Session = Depends(get_db, scope="function"), user: User = Depends(current_user), q: str = "",
          sort: str = "title", status: str = "all", limit: int = Query(200, le=1000), offset: int = 0,
          genre: str | None = None, language: str | None = None, author: str | None = None, series: str | None = None):
    query = select(Book, BookProgress).outerjoin(
        BookProgress, (BookProgress.book_id == Book.id) & (BookProgress.user_id == user.id))
    if genre is not None:
        query = query.where(Book.genre == ("" if genre == "Uncategorized" else genre))
    if language is not None:
        query = query.where(Book.language == language)
    if author is not None:
        query = query.where(Book.author == author)
    if series is not None:
        query = query.where(Book.series == series)
    if q:
        like = f"%{q}%"
        query = query.where(Book.title.ilike(like) | Book.author.ilike(like) | Book.series.ilike(like))
    if status == "listening":
        query = query.where(BookProgress.position > 0, BookProgress.finished.is_(False))
    elif status == "finished":
        query = query.where(BookProgress.finished.is_(True))
    elif status == "new":
        query = query.where(BookProgress.book_id.is_(None))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    order = (BookProgress.updated_at.desc(),) if status == "listening" else SORTS.get(sort, SORTS["title"])
    rows = db.execute(query.order_by(*order, Book.id).limit(limit).offset(offset)).all()
    if sort == "series" or series is not None:      # a series in its order: 1, 2, 2.5, 3 … (not 1, 10, 2)
        rows = sorted(rows, key=lambda r: ((r[0].series or "~").casefold(), _part_key(r[0].series_part), r[0].title.casefold()))
    return {"total": total, "items": [book_json(b, p) for b, p in rows]}


@router.get("/{book_id}")
def book(book_id: int, db: Session = Depends(get_db_with_copies, scope="function"), user: User = Depends(current_user)):
    b = db.get(Book, book_id)
    if b is None:
        raise HTTPException(404, "No such book")
    parts = db.scalars(select(BookPart).where(BookPart.book_id == book_id).order_by(BookPart.position)).all()
    out = book_json(b, db.get(BookProgress, (user.id, book_id)), True, parts)
    out["in_series"] = []
    if b.series:
        rows = db.execute(select(Book, BookProgress).outerjoin(
            BookProgress, (BookProgress.book_id == Book.id) & (BookProgress.user_id == user.id))
            .where(Book.series == b.series)).all()        # whoever wrote them: The Horus Heresy has many authors
        rows.sort(key=lambda r: (_part_key(r[0].series_part), r[0].title.casefold()))
        out["in_series"] = [book_json(x, p) for x, p in rows]
        mine = _part_key(b.series_part)
        later = [x for x in out["in_series"] if _part_key(x["series_part"]) > mine and x["id"] != b.id]
        out["next"] = later[0] if later and mine < 1e9 else None
    return out


@router.get("/{book_id}/parts/{position}/stream")
def part_stream(book_id: int, position: int, request: Request, q: str = "original", t: float = 0.0,
                db: Session = Depends(get_db_with_copies, scope="function"), user: User = Depends(stream_user)):
    p = db.scalar(select(BookPart).where(BookPart.book_id == book_id, BookPart.position == position))
    if p is None:
        raise HTTPException(404, "No such part")
    if p.path.startswith(mirror.ROOT):          # another server's book (the Library Network)
        path = p.path
        db.close()
        return theirs(path, q, t, False, request)
    return stream_file(p.path, p.format, "", 0, 16, q, t)


class Progress(BaseModel):
    position: float
    finished: bool = False


@router.put("/{book_id}/progress")
def progress(book_id: int, body: Progress, db: Session = Depends(get_db_with_copies, scope="function"), user: User = Depends(current_user)):
    if db.get(Book, book_id) is None:
        raise HTTPException(404, "No such book")
    row = db.get(BookProgress, (user.id, book_id)) or BookProgress(user_id=user.id, book_id=book_id)
    row.position, row.finished = max(0.0, body.position), body.finished
    row.updated_at = datetime.now(timezone.utc)
    db.merge(row)
    db.commit()
    return {"ok": True}


art_router = APIRouter(prefix="/api/art", tags=["art"])


@art_router.get("/book/{book_id}")
def book_art(book_id: int, s: int = 300, db: Session = Depends(get_db_with_copies, scope="function")):
    b = db.get(Book, book_id)
    if b is None or not b.art:
        return Response(status_code=404)
    if b.art.startswith(mirror.ROOT):
        ref = b.art
        db.close()
        return _picture(mirror.picture(ref, s))
    if b.art.startswith("embedded-file:"):
        path = b.art.split(":", 1)[1]
        data = tags.picture(path)
        return _send(data, f"{path}:book", s)
    data, ident = art.source_bytes(b.art)
    return _send(data, ident, s)


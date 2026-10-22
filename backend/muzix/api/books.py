from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import art
from ..db import get_db
from ..meta import tags
from ..models import Book, BookPart, BookProgress, User
from ..security import current_user
from .library import _send
from .stream import stream_file

router = APIRouter(prefix="/api/books", tags=["audiobooks"])
SORTS = {"title": func.lower(Book.title), "author": func.lower(Book.author), "added": Book.added_at.desc()}


def book_json(b: Book, prog: BookProgress | None, full=False, parts=None):
    out = {"id": b.id, "title": b.title, "author": b.author, "narrator": b.narrator, "series": b.series,
           "year": b.year, "duration": b.duration, "art": f"/api/art/book/{b.id}" if b.art else None,
           "position": prog.position if prog else 0, "finished": bool(prog and prog.finished),
           "updated_at": prog.updated_at.isoformat() if prog and prog.updated_at else None}
    if full:
        out["description"] = b.description
        out["chapters"] = b.chapters or []
        out["parts"] = [{"position": p.position, "title": p.title, "duration": p.duration, "offset": p.offset,
                         "format": p.format, "stream": f"/api/books/{b.id}/parts/{p.position}/stream"}
                        for p in parts or []]
    return out


@router.get("")
def books(db: Session = Depends(get_db), user: User = Depends(current_user), q: str = "",
          sort: str = "title", status: str = "all", limit: int = Query(200, le=1000), offset: int = 0):
    query = select(Book, BookProgress).outerjoin(
        BookProgress, (BookProgress.book_id == Book.id) & (BookProgress.user_id == user.id))
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
    order = BookProgress.updated_at.desc() if status == "listening" else SORTS.get(sort, SORTS["title"])
    rows = db.execute(query.order_by(order, Book.id).limit(limit).offset(offset)).all()
    return {"total": total, "items": [book_json(b, p) for b, p in rows]}


@router.get("/{book_id}")
def book(book_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    b = db.get(Book, book_id)
    if b is None:
        raise HTTPException(404, "No such book")
    parts = db.scalars(select(BookPart).where(BookPart.book_id == book_id).order_by(BookPart.position)).all()
    return book_json(b, db.get(BookProgress, (user.id, book_id)), True, parts)


@router.get("/{book_id}/parts/{position}/stream")
def part_stream(book_id: int, position: int, q: str = "original", t: float = 0.0,
                db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = db.scalar(select(BookPart).where(BookPart.book_id == book_id, BookPart.position == position))
    if p is None:
        raise HTTPException(404, "No such part")
    return stream_file(p.path, p.format, "", 0, 16, q, t)


class Progress(BaseModel):
    position: float
    finished: bool = False


@router.put("/{book_id}/progress")
def progress(book_id: int, body: Progress, db: Session = Depends(get_db), user: User = Depends(current_user)):
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
def book_art(book_id: int, s: int = 300, db: Session = Depends(get_db)):
    b = db.get(Book, book_id)
    if b is None or not b.art:
        return Response(status_code=404)
    if b.art.startswith("embedded-file:"):
        path = b.art.split(":", 1)[1]
        data = tags.picture(path)
        return _send(data, f"{path}:book", s)
    data, ident = art.source_bytes(b.art)
    return _send(data, ident, s)


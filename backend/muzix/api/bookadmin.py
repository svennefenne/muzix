"""The admin's side of audiobooks coming in (audiobook/pipeline.py): the latest imports, the books filed unsure
("Needs a look": the right one picked from any source, or kept as it is), and those set aside as duplicates
(Audiobooks/_Duplicates: filed beside the library's copy, in its place, or thrown away)."""

import json
import os
import shutil

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import jobs, serial
from ..audiobook import make, place, sources
from ..db import get_db
from ..models import Book, BookPart, Job, Root
from ..organize import importer
from ..security import admin_user
from ..serial import iso

router = APIRouter(prefix="/api/admin/books", tags=["audiobooks"], dependencies=[Depends(admin_user)])


def _root() -> str:
    root = importer.upload_root("audiobooks")
    if not root or not os.access(root, os.W_OK):
        raise HTTPException(400, "There's no audiobook folder Muzix may write to")
    return root


@router.get("/imports")
def imports(limit: int = 10, db: Session = Depends(get_db, scope="function")):
    out = []
    for job in db.scalars(select(Job).where(Job.type.in_(("import_books", "import_books_watched")))
                          .order_by(Job.id.desc()).limit(limit)):
        r = job.result or {}
        out.append({"id": job.id, "status": job.status, "progress": job.progress, "message": job.message,
                    "batch": (job.params or {}).get("batch", ""), "watched": (job.params or {}).get("name", ""),
                    "started_at": iso(job.started_at), "finished_at": iso(job.finished_at),
                    "books": r.get("books") or [], "failed": r.get("failed") or []})
    return out


def _brief(b: Book) -> dict:
    return {"id": b.id, "title": b.title, "author": b.author, "narrator": b.narrator, "series": b.series,
            "series_part": b.series_part or "", "year": b.year, "genre": b.genre, "language": b.language,
            "duration": b.duration, "asin": b.asin, "art": serial.art_url("book", b.id) if b.art else None,
            "path": b.path}


@router.get("/review")
def review(db: Session = Depends(get_db, scope="function")):
    """The books filed without a source being sure of them."""
    return [_brief(b) for b in db.scalars(select(Book).where(Book.review.is_(True), Book.peer_id.is_(None))
                                           .order_by(Book.added_at.desc()))]


@router.get("/sources")
def lookup_sources():
    """The sources "Pick the right book" asks, in order."""
    return [{"id": k, "name": v} for k, v in sources.SOURCES.items()]


@router.get("/lookup")
def lookup(q: str, author: str = "", source: str = "audible"):
    """A source's books for a search, or for a link to one of its books: to pick the right one."""
    if source not in sources.SOURCES:
        raise HTTPException(400, "No such source")
    return [{**{k: p[k] for k in ("source", "id", "asin", "url", "title", "subtitle", "authors", "narrators", "runtime",
                                   "release", "year", "series", "image")}, "language": place.language_code(p["language"])}
            for p in sources.search(source, q, author)]


def _folder(b: Book) -> str:
    return os.path.dirname(b.path) if os.path.isfile(b.path) else b.path


def _sidecar(folder: str) -> dict:
    try:
        with open(os.path.join(folder, "metadata.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write_sidecar(folder: str, d: dict):
    with open(os.path.join(folder, "metadata.json"), "w") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def _move_book(s: Session, b: Book, new_folder: str):
    """The book's folder to ``new_folder``, and its rows with it (so its place in it, its plays, stay)."""
    old = _folder(b)
    if os.path.normpath(old) == os.path.normpath(new_folder):
        return
    if os.path.exists(new_folder):
        raise HTTPException(409, f"{new_folder} is taken")
    os.makedirs(os.path.dirname(new_folder), exist_ok=True)
    shutil.move(old, new_folder)
    b.path = new_folder + b.path[len(old):]
    for p in s.scalars(select(BookPart).where(BookPart.book_id == b.id)):
        p.path = new_folder + p.path[len(old):]
    if b.art.startswith(old):
        b.art = new_folder + b.art[len(old):]
    elif b.art.startswith("embedded-file:" + old):
        b.art = "embedded-file:" + new_folder + b.art[len("embedded-file:" + old):]
    parent = os.path.dirname(old)
    while parent and not os.listdir(parent) and not any(parent == r for r in _roots(s)):
        os.rmdir(parent)
        parent = os.path.dirname(parent)


def _roots(s: Session) -> list[str]:
    return [r.path for r in s.scalars(select(Root).where(Root.kind == "audiobooks"))]


class Match(BaseModel):
    source: str = "audible"
    id: str = ""
    asin: str = ""          # what the apps before 0.10.35 / 0.4.42 send


@router.post("/{book_id}/match")
def match(book_id: int, body: Match, db: Session = Depends(get_db, scope="function")):
    """The book is this one of a source's: tagged and named as it, and moved where that puts it."""
    root = _root()
    b = db.get(Book, book_id)
    if b is None:
        raise HTTPException(404, "No such book")
    if not b.path.lower().endswith(".m4b") or not os.path.isfile(b.path):
        raise HTTPException(400, "Only a book that is one .m4b can be matched (Muzix makes uploads so)")
    if body.source not in sources.SOURCES:
        raise HTTPException(400, "No such source")
    p = sources.get(body.source, body.id or body.asin)
    if p is None:
        raise HTTPException(404, f"{sources.SOURCES[body.source]} doesn't know that book")
    g = sources.Guess(title=sources.bare_title(p["title"]), authors=p["authors"][:1], asin=p["asin"], duration=b.duration,
                      language=p["language"])
    f = sources.identify(g, chosen=p)
    genre = "Warhammer" if f.warhammer else place.author_genre(root, f.authors[0] if f.authors else "") or place.genre_of(f)
    language = place.language_code(f.language)
    cover = None
    for url in f.images:
        try:
            import urllib.request
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as r:
                cover = make.as_jpeg(r.read())
                break
        except Exception:  # noqa: BLE001
            continue
    description = make.plain(f.description)
    make.write_tags(b.path, f, genre, language, cover, description)
    folder = _folder(b)
    named = os.path.join(folder, make.safe(f.title) + ".m4b")       # the file as the book is called now
    if os.path.normpath(named) != os.path.normpath(b.path) and not os.path.exists(named):
        os.rename(b.path, named)
        for p in db.scalars(select(BookPart).where(BookPart.book_id == b.id, BookPart.path == b.path)):
            p.path = named
        if b.art == "embedded-file:" + b.path:
            b.art = "embedded-file:" + named
        b.path = named
    if cover:
        with open(os.path.join(folder, "cover.jpg"), "wb") as cf:
            cf.write(cover)
    side = _sidecar(folder)
    side.update({"title": f.title, "subtitle": f.subtitle or None, "authors": f.authors, "narrators": f.narrators,
                 "series": [f.series + (f" #{f.vol}" if f.vol else "")] if f.series else [], "genres": [genre],
                 "publishedYear": f.year or None, "publisher": f.publisher or None, "description": description or None,
                 "asin": f.asin or None, "language": language or None,
                 "muzix": {**(side.get("muzix") or {}), "review": False, "sources": f.sources}})
    _write_sidecar(folder, side)
    new_folder = place.target(root, f, genre) if os.path.commonpath([folder, root]) == root else folder
    if os.path.basename(os.path.dirname(folder)) == place.DUPLICATES:
        new_folder = folder                     # one set aside stays there till the admin files it
    b.title, b.author, b.narrator, b.series, b.series_part = f.title, ", ".join(f.authors), ", ".join(f.narrators), f.series, f.vol
    b.year, b.genre, b.language, b.asin, b.description, b.review = int(f.year or 0), genre, language, f.asin, description, False
    _move_book(db, b, new_folder)
    db.commit()
    jobs.submit("scan_books", "Scan the audiobooks")
    return _brief(b)


@router.post("/{book_id}/ok")
def looks_right(book_id: int, db: Session = Depends(get_db, scope="function")):
    """The book is right as it was filed: off the list."""
    b = db.get(Book, book_id)
    if b is None:
        raise HTTPException(404, "No such book")
    folder = _folder(b)
    side = _sidecar(folder)
    if side:
        side["muzix"] = {**(side.get("muzix") or {}), "review": False}
        _write_sidecar(folder, side)
    b.review = False
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- duplicates

def _dupes_dirs(db: Session) -> list[tuple[str, str]]:
    out = []
    for root in _roots(db):
        d = os.path.join(root, place.DUPLICATES)
        if os.path.isdir(d):
            out += [(root, os.path.join(d, n)) for n in sorted(os.listdir(d)) if os.path.isdir(os.path.join(d, n))]
    return out


@router.get("/duplicates")
def duplicates(db: Session = Depends(get_db, scope="function")):
    out = []
    for root, folder in _dupes_dirs(db):
        side = _sidecar(folder)
        size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(folder) for f in fs)
        theirs = db.get(Book, (side.get("muzix") or {}).get("duplicate_of") or 0)
        out.append({"name": os.path.basename(folder), "title": side.get("title") or os.path.basename(folder),
                    "authors": side.get("authors") or [], "narrators": side.get("narrators") or [], "size": size,
                    "seconds": (side.get("chapters") or [{}])[-1].get("end", 0) if side.get("chapters") else 0,
                    "library": _brief(theirs) if theirs else None})
    return out


class DupAction(BaseModel):
    name: str
    how: str          # keep: filed as another copy; replace: in the library copy's place; delete


def _found_from(side: dict) -> sources.Found:
    series = (side.get("series") or [""])[0] or ""
    name, _, vol = series.partition(" #")
    return sources.Found(title=side.get("title") or "", authors=side.get("authors") or [],
                         narrators=side.get("narrators") or [], series=name, vol=vol, year=str(side.get("publishedYear") or ""),
                         language=side.get("language") or "", asin=side.get("asin") or "")


@router.post("/duplicates")
def duplicate_action(body: DupAction, db: Session = Depends(get_db, scope="function")):
    match_ = next(((r, f) for r, f in _dupes_dirs(db) if os.path.basename(f) == body.name), None)
    if match_ is None:
        raise HTTPException(404, "No such duplicate")
    root, folder = match_
    if body.how == "delete":
        shutil.rmtree(folder)
        return {"ok": True}
    side = _sidecar(folder)
    f = _found_from(side)
    genre = (side.get("genres") or ["Uncategorized"])[0]
    if body.how == "keep":
        dest = place.target(root, f, genre)
        base, n = dest, 2
        while os.path.exists(dest):
            dest, n = f"{base} ({n})", n + 1
    elif body.how == "replace":
        theirs = db.get(Book, (side.get("muzix") or {}).get("duplicate_of") or 0)
        if theirs is None:
            raise HTTPException(409, "The library's copy is gone: file it as a book instead")
        dest = _folder(theirs)
        aside = place.aside(root, sources.Found(title=theirs.title, authors=[theirs.author], narrators=[]))
        shutil.move(dest, aside)
    else:
        raise HTTPException(400, "keep, replace or delete")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.move(folder, dest)
    if body.how == "replace":         # the library's book is the new file now: its place in it, its plays, stay
        m4b = next((os.path.join(dest, n) for n in os.listdir(dest) if n.lower().endswith(".m4b")), None)
        if m4b:
            theirs.path, theirs.signature = m4b, ""
            db.commit()
    side["muzix"] = {**(side.get("muzix") or {}), "duplicate_of": None}
    _write_sidecar(dest, side)
    jobs.submit("scan_books", "Scan the audiobooks")
    return {"ok": True, "folder": os.path.relpath(dest, root)}

"""Audiobook scanning.

A book is either a single file with chapters (.m4b and friends) or a folder of
audio files read in order (CD1/CD2 subfolders belong to their parent book).
Ebooks and other files lying around are ignored.
"""

import hashlib
import json
import logging
import os
import re
import subprocess
import time

from sqlalchemy import delete, select

from . import db, formats, jobs
from .meta import tags
from .models import Book, BookPart, Root
from .scanner import find_cover

log = logging.getLogger("muzix.books")
DISC_DIR = re.compile(r"^(cd|disc|disk|part|del)[\s._-]*\d+$", re.I)
SINGLE_BOOK_EXT = {"m4b"}
# what Windows Media Player and friends write when a rip had no lookup
PLACEHOLDER = re.compile(r"^unknown (album|artist)\b", re.I)


def real_tag(value: str) -> str:
    return "" if PLACEHOLDER.match(value or "") else value or ""


def natural_key(s: str):
    return [int(x) if x.isdigit() else x.casefold() for x in re.split(r"(\d+)", s)]


def find_books(root: str):
    """Yield (book path, [part file paths]) for every book under root."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort(key=natural_key)
        if DISC_DIR.match(os.path.basename(dirpath)) and dirpath != root:
            continue   # read together with its parent folder
        audio = sorted((f for f in filenames if formats.is_audio(f) and not f.startswith(".")), key=natural_key)
        singles = [f for f in audio if formats.ext_of(f) in SINGLE_BOOK_EXT]
        if singles and len(singles) == len(audio):
            for f in singles:
                yield os.path.join(dirpath, f), [os.path.join(dirpath, f)]
            continue
        parts = [os.path.join(dirpath, f) for f in audio]
        for d in dirnames:
            if DISC_DIR.match(d):
                sub = os.path.join(dirpath, d)
                parts += [os.path.join(sub, f) for f in sorted(os.listdir(sub), key=natural_key)
                          if formats.is_audio(f) and not f.startswith(".")]
        if parts:
            yield dirpath, parts


def signature(parts: list[str]) -> str:
    h = hashlib.sha1()
    for p in parts:
        try:
            st = os.stat(p)
        except OSError:
            continue
        h.update(f"{p}|{st.st_size}|{st.st_mtime}".encode())
    return h.hexdigest()


def ffprobe_chapters(path: str) -> list:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_chapters", path],
                             capture_output=True, text=True, timeout=60).stdout
        return [{"title": (c.get("tags") or {}).get("title") or f"Chapter {i + 1}",
                 "start": float(c.get("start_time", 0))}
                for i, c in enumerate(json.loads(out or "{}").get("chapters", []))]
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return []


def read_book(path: str, parts: list[str]) -> dict:
    infos = []
    for p in parts:
        try:
            infos.append(tags.read(p))
        except Exception as e:
            log.info("unreadable %s: %s", p, e)
            infos.append(tags.AudioInfo(title=os.path.splitext(os.path.basename(p))[0]))
    first = infos[0]
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    stem = os.path.splitext(os.path.basename(path))[0] if os.path.isfile(path) else os.path.basename(path)
    album = real_tag(first.album)
    title = album or stem
    author = real_tag(first.albumartist) or real_tag(first.artist)
    m = re.match(r"^(.+?)\s+-\s+(.+)$", stem)
    if not author and m:
        author, title = m.group(1), album or m.group(2)
    chapters, offset, part_rows = [], 0.0, []
    for i, (p, info) in enumerate(zip(parts, infos, strict=True)):
        part_title = info.title or os.path.splitext(os.path.basename(p))[0]
        part_rows.append(dict(position=i, path=p, title=part_title, duration=info.duration,
                              offset=offset, format=formats.ext_of(p)))
        inner = info.chapters or (ffprobe_chapters(p) if formats.ext_of(p) in ("m4b", "m4a", "mp3") and len(parts) == 1 else [])
        if inner:
            chapters += [{"title": c["title"], "start": offset + c["start"]} for c in inner]
        else:
            chapters.append({"title": part_title, "start": offset})
        offset += info.duration or 0
    cover = find_cover(folder)
    if not cover and first.embedded_art:
        cover = f"embedded-file:{parts[0]}"
    return dict(title=title, author=author, narrator=first.extra.get("narrator", ""),
                series=os.path.basename(os.path.dirname(folder)) if os.path.isdir(path) else "",
                year=first.year, art=cover, duration=offset, chapters=chapters), part_rows


@jobs.job("scan_books")
def scan_books(ctx: jobs.JobContext, full: bool = False):
    gen = int(time.time())
    with db.session() as s:
        roots = [(r.id, r.path) for r in s.scalars(select(Root).where(Root.kind == "audiobooks", Root.enabled.is_(True)))]
    added = updated = 0
    for rid, root in roots:
        if not os.path.isdir(root):
            ctx.log(f"{root} is not mounted, skipped")
            continue
        ctx.log(f"scanning {root}")
        found = list(find_books(root))
        ctx.log(f"  {len(found)} books")
        for i, (path, parts) in enumerate(found):
            ctx.check()
            sig = signature(parts)
            with db.session() as s:
                book = s.scalar(select(Book).where(Book.path == path))
                if book is not None and book.signature == sig and not full:
                    book.seen_scan = gen
                    continue
            meta, part_rows = read_book(path, parts)
            with db.session() as s:
                book = s.scalar(select(Book).where(Book.path == path))
                if book is None:
                    book = Book(root_id=rid, path=path, **meta)
                    s.add(book)
                    added += 1
                else:
                    for k, v in meta.items():
                        setattr(book, k, v)
                    for k, v in (book.custom or {}).items():   # the admin's edits win over the files
                        setattr(book, k, v)
                    s.execute(delete(BookPart).where(BookPart.book_id == book.id))
                    updated += 1
                book.signature, book.seen_scan = sig, gen
                s.flush()
                for row in part_rows:
                    s.add(BookPart(book_id=book.id, **row))
            if i % 10 == 0:
                ctx.update(i / max(1, len(found)), f"{root}: {i}/{len(found)} books")
        with db.session() as s:
            gone = s.execute(delete(Book).where(Book.root_id == rid, Book.seen_scan != gen)).rowcount
        ctx.log(f"  +{added} ~{updated} -{gone}")
    return {"added": added, "updated": updated}

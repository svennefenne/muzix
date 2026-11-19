"""Audiobooks in, the way music comes in: uploaded on the admin page (import_books) or put in the audiobook watch
folder (import_books_watched). Each book found (group.py) is looked up (sources.py), made one .m4b (make.py) and
filed (place.py) in the audiobook upload folder; one the library has already goes to its _Duplicates. A book the
sources weren't sure of is filed all the same and marked for review. Once a book's .m4b is made and as long as
its files, those files are deleted; a book that fails keeps them."""

import logging
import os
import shutil
from pathlib import Path

from .. import env, formats, jobs, watch
from ..organize import importer
from . import group, make, place, sources

log = logging.getLogger("muzix.audiobook")


def file_books(ctx: jobs.JobContext, source: Path, label: str, named: bool = False) -> dict:
    """Every book under ``source`` into the library. {"books": [...], "failed": [...]}. ``named``: the folder's
    name is the user's (the watch folder's), and says what a book lying loose in it is."""
    root = importer.upload_root("audiobooks")
    if not root or not os.access(root, os.W_OK):
        raise RuntimeError("there's no audiobook folder Muzix may write to: Admin → Library, an audiobook folder "
                           "as the upload target, mounted read-write")
    ctx.log(f"looking for books in {label}")
    found = group.scan(str(source), named_root=named)
    if not found:
        raise RuntimeError("there are no audiobooks in it")
    ctx.log(f"{len(found)} book{'s' if len(found) != 1 else ''}")
    names = [b.guess.title or os.path.basename(b.home or b.files[0].path) for b in found]
    ids = identify_all(ctx, found, names)
    out: dict = {"books": [], "failed": [], "root": root}
    made_here: list[tuple] = []         # (Found, seconds, the files' sizes, title) of the books made so far
    for i, (b, f) in enumerate(zip(found, ids, strict=True)):
        ctx.check()
        name = names[i]
        ctx.update(0.25 + 0.7 * i / len(found), f"{i + 1} of {len(found)}: {name}")
        sizes = sorted(os.path.getsize(p.path) for p in b.files if os.path.exists(p.path))
        copy = next((m for m in made_here if sizes and m[2] == sizes), None)
        if copy:                        # the same files again (a collection's copy of a book in another folder)
            ctx.log(f"{name}: the same files as “{copy[3]}”, made already: left in the upload")
            out["failed"].append({"title": name, "error": f"a copy of “{copy[3]}”, made from this upload already",
                                  "files": len(b.files)})
            continue
        try:
            language = place.language_code(f.language)
            author = f.authors[0] if f.authors else ""
            genre = "Warhammer" if f.warhammer else place.author_genre(root, author) or place.genre_of(f)
            dup = place.duplicate_of(f, b.guess.duration)
            twin = next((m for m in made_here if place.alike(f, b.guess.duration, m[0].title, (m[0].authors or [""])[0],
                                                             m[0].narrators, m[1])), None)
            folder = place.aside(root, f) if dup or twin else place.target(root, f, genre)
            ctx.log(f"{name}: {', '.join(f.sources) or 'no source knew it'}"
                    f"{' (not sure)' if not f.sure else ''}{f' (another copy of “{twin[3]}” here)' if twin else ''}"
                    f" → {os.path.relpath(folder, root)}")
            made = make.make([p.path for p in b.files], f, genre, language, folder, home=b.home,
                             muzix={"review": not f.sure, "sources": f.sources, "uploaded": label,
                                    "duplicate_of": dup.id if dup else None})
            for p in b.files:
                try:
                    os.remove(p.path)
                except OSError:
                    pass
            if b.home and os.path.isdir(b.home) and not _sound_in(b.home):   # never another book's files with it
                shutil.rmtree(b.home, ignore_errors=True)
            made_here.append((f, made["seconds"], sizes, f.title))
            out["books"].append({"title": f.title, "author": author, "folder": os.path.relpath(folder, root),
                                 "genre": genre, "language": language, "sure": f.sure, "sources": f.sources,
                                 "duplicate_of": dup.id if dup else None, "seconds": made["seconds"],
                                 "chapters": made["chapters"], "cover": made["cover"]})
        except make.Failed as e:
            ctx.log(f"{name}: couldn't be made: {e}")
            out["failed"].append({"title": name, "error": str(e), "files": len(b.files)})
    _prune(source)
    jobs.submit("scan_books", "Scan the audiobooks")
    return out


def identify_all(ctx: jobs.JobContext, found: list, names: list[str]) -> list[sources.Found]:
    """Every book looked up; then, when most of those the sources were sure of are part of one thing (Star Wars), the
    others looked for as that too: "Crucible" by no one a tag names is Troy Denning's Star Wars book, not another."""
    ids = []
    for i, b in enumerate(found):
        ctx.check()
        ctx.update(0.05 + 0.1 * i / len(found), f"looking up {i + 1} of {len(found)}: {names[i]}")
        ids.append(sources.identify(b.guess))
    theme = sources.theme_of(ids)
    if not theme:
        return ids
    rest = [i for i, f in enumerate(ids) if not f.sure]
    if rest:
        ctx.log(f"most of the books are {theme}: {len(rest)} the sources weren't sure of looked for as that too")
    for n, i in enumerate(rest):
        ctx.check()
        ctx.update(0.15 + 0.1 * n / len(rest), f"looking up {names[i]} again, as {theme}")
        found[i].guess.keywords = theme
        f = sources.identify(found[i].guess)
        if f.sure or (f.sources and (not ids[i].sources or (sources.in_theme(f.context, theme)
                                                            and not sources.in_theme(ids[i].context, theme)))):
            ids[i] = f
    return ids


def _sound_in(folder: str) -> bool:
    return any(formats.is_audio(f) for _, _, fs in os.walk(folder) for f in fs)


def _prune(folder: Path):
    """What the books were in, once it holds nothing but leftovers from them (empty folders)."""
    if not folder.is_dir():
        return
    for r, _dirs, _files in os.walk(folder, topdown=False):
        try:
            if not os.listdir(r):
                os.rmdir(r)
        except OSError:
            pass


@jobs.job("import_books")
def import_books(ctx: jobs.JobContext, batch: str):
    """An upload batch of audiobooks (api/upload.py)."""
    source = env.UPLOAD_DIR / batch
    if not source.is_dir():
        raise RuntimeError("the upload is gone")
    out = file_books(ctx, source, f"upload {batch}")
    if source.exists() and not any(os.path.isfile(os.path.join(r, f)) for r, _, fs in os.walk(source) for f in fs
                                   if not f.startswith(".")):
        shutil.rmtree(source, ignore_errors=True)
    kind = env.UPLOAD_DIR / f".{batch}.audiobooks"
    if kind.exists() and not source.exists():
        kind.unlink()
    return out


@jobs.job("import_books_watched")
def import_books_watched(ctx: jobs.JobContext, name: str, key: str, held: str = "", parts: list | None = None):
    """One book (or a folder of them) from the audiobook watch folder; ``parts``: a book's files lying loose in it
    (watch.loose_books), ``name`` the book. From a computer, it is deleted there once every book in it is in the
    library; what's left goes to _Done, and to _Failed when a book couldn't be made."""
    where = watch.place(key)
    if where is None or where.key != key:
        raise RuntimeError("the watch folder changed or can't be reached")
    if parts and isinstance(where, watch.ServerPlace):
        name, parts = where.gather(name, parts), None       # into a folder of their own there, filed as one
    names = list(parts or [name])
    work = env.UPLOAD_DIR / watch._batch()
    try:
        if parts:
            folder = work / name
            for p in parts:
                got = where.fetch(p, held, work / ".parts")
                folder.mkdir(parents=True, exist_ok=True)
                shutil.move(str(got), str(folder / p))
        else:
            folder = where.fetch(name, held, work)
            if folder.is_file():
                (work / folder.stem).mkdir(parents=True, exist_ok=True)
                folder = Path(shutil.move(str(folder), str(work / folder.stem / folder.name))).parent
        out = {"name": name, **file_books(ctx, folder, f"the watch folder: {name}", named=True)}
        if out["failed"]:
            for n in names:
                where.move(n, held, "_Failed")
            ctx.log(f"{len(out['failed'])} couldn't be made: set aside in _Failed")
        elif isinstance(where, watch.ComputerPlace):
            for n in names:
                where.remove(n, held)
            out["removed"] = True
            ctx.log("every book in it is in the library: deleted from the computer's watch folder")
        elif folder.exists():
            where.move(name, held, "_Done")
        return out
    except Exception:
        for n in names:
            try:
                where.move(n, held, "_Failed")
            except Exception:
                log.exception("audiobook watch folder: couldn't set %s aside", n)
        raise
    finally:
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)

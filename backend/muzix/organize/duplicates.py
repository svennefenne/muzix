"""Before an upload: files that came before (the very same file uploaded again, or still waiting to
be imported) and songs the library seems to have already, going by the names of the files and their
folders. Quick, and only a warning: the uploader decides what to skip."""

import os
import re
import unicodedata
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import env, formats
from ..meta import tags
from ..models import Track, UploadedFile
from ..serial import iso

_SEP = re.compile(r"\s+[-–—]\s+")
_NUMBER = re.compile(r"^\s*(?:(?:cd|disc|disk)\s*\d+\s*[-._]?\s*)?\d{1,3}(?:\s*[-.]\s*\d{1,3})?(?:\s*[-._)]\s*|\s+)", re.I)
_BRACKETS = re.compile(r"[(\[{][^)\]}]*[)\]}]")
_NOT_WORD = re.compile(r"[\W_]+")
_LETTER = re.compile(r"[^\W\d_]")
_APOSTROPHE = re.compile(r"['’`´]")
_NOISE = re.compile(r"\s+bonus(?:\s+track)?$")      # what Bandcamp adds to a title: "...-remix-bonus-track"
MUSIC = ("native", "decode")


def norm(s: str) -> str:
    """Case, accents and punctuation aside: "Motörhead - Ace of Spades!" -> "motorhead ace of spades"; an
    apostrophe goes without a space, as file names leave it out: "Devil's Cave" -> "devils cave"."""
    s = unicodedata.normalize("NFKD", _APOSTROPHE.sub("", s.casefold()).replace("&", " and "))
    return " ".join(_NOT_WORD.sub(" ", "".join(c for c in s if not unicodedata.combining(c))).split())


def base(s: str) -> str:
    """Without what's in brackets: "Battery (Remastered 2017)" -> "battery"."""
    return norm(_BRACKETS.sub(" ", s))


def title_keys(title: str) -> set[str]:
    """The ways a song's title may be written in a file's name: as it is and without what's in brackets, each
    without "and" (Bandcamp's names drop an "&": "parts-1-2") or an added "bonus track", and squashed (its
    punctuation dropped rather than spaced: "isaiah-1320" for "Isaiah 13:20")."""
    out = set()
    for t in (norm(title), base(title)):
        t = _NOISE.sub("", t)
        for k in (t, " ".join(w for w in t.split() if w != "and")):
            if k:
                out |= {k, k.replace(" ", "")}
    return out


def same_title(a: str, b: str) -> bool:
    """Whether two titles are one, punctuation, "&" and "and" aside: "Death Walks Parts 1 and 2", "death-walks-parts-1-2"."""
    squash = lambda t: "".join(w for w in _NOISE.sub("", norm(t)).split() if w != "and")
    return squash(a) == squash(b)


def titles(stem: str) -> set[str]:
    """The song titles a file name may hold: "3. Band - Album - Title (2001)", "03 Title", "Band - Title"."""
    last = _SEP.split(stem)[-1]
    return {t for t in (last, _NUMBER.sub("", last), _NUMBER.sub("", stem)) if t.strip()}


def _tags(batch: str, rel: str) -> dict:
    """Album artist, album, title and year of an uploaded song, for the upload area."""
    if formats.family(rel) not in MUSIC:
        return {}
    try:
        t = tags.read(str(env.UPLOAD_DIR / batch / rel))
    except Exception:       # whatever it is, it's still uploaded; it's shown by its folder
        return {}
    return {"artist": (t.albumartist or t.artist or "")[:512], "album": (t.album or "")[:512],
            "title": (t.title or "")[:512], "year": t.year or 0}


def remember(db: Session, batch: str, saved: list[dict]):
    db.add_all(UploadedFile(name=os.path.basename(f["path"]).lower(), size=f["size"], path=f["path"], batch=batch,
                            **_tags(batch, f["path"]))
               for f in saved)
    db.commit()


def forget(db: Session, batch: str):
    """A discarded batch: its files weren't kept, so they may come again."""
    db.execute(delete(UploadedFile).where(UploadedFile.batch == batch))
    db.commit()


def _waiting() -> dict[tuple[str, int], str]:
    """(name, size) of the files in the upload area -> when their batch came."""
    out = {}
    if not env.UPLOAD_DIR.is_dir():
        return out
    for d in env.UPLOAD_DIR.iterdir():
        # an import going on moves files out and takes emptied batches away: what's gone isn't waiting
        try:
            when = datetime.fromtimestamp(d.stat().st_ctime, timezone.utc).isoformat()
        except FileNotFoundError:
            continue
        if not d.is_dir():
            continue
        for r, _, fs in os.walk(d):
            for f in fs:
                if not f.endswith(".part"):
                    try:
                        out[(f.lower(), os.path.getsize(os.path.join(r, f)))] = when
                    except FileNotFoundError:
                        pass
    return out


def _chunks(items, n=500):
    items = list(items)
    for i in range(0, len(items), n):
        yield items[i:i + n]


def _song(t) -> dict:
    return {"title": t.title, "artist": t.artist or t.albumartist, "album": t.album, "format": t.format, "path": t.path}


def check(files: list[tuple[str, int]], db: Session) -> dict:
    """files: (path as uploaded, size). Which look like duplicates, and the files to leave out to
    skip them: their lyrics too and, for a folder skipped whole, its covers and such."""
    found: dict[str, dict] = {}
    keys = {(os.path.basename(p).lower(), size) for p, size in files}

    # the very same file: waiting in the upload area, uploaded before, or in the library as it is
    waiting = _waiting()
    before: dict[tuple[str, int], datetime] = {}
    for names in _chunks({name for name, _ in keys}):
        for row in db.scalars(select(UploadedFile).where(UploadedFile.name.in_(names))):
            before[(row.name, row.size)] = max(row.uploaded_at, before.get((row.name, row.size), row.uploaded_at))
    same_file: dict[tuple[str, int], Track] = {}
    for sizes in _chunks({size for _, size in keys if size}):
        for t in db.scalars(select(Track).where(Track.size.in_(sizes), Track.peer_id.is_(None))
                            .execution_options(include_hidden=True)):
            same_file.setdefault((os.path.basename(t.path).lower(), t.size), t)
    for path, size in files:
        key = (os.path.basename(path).lower(), size)
        if key in waiting:
            found[path] = {"path": path, "why": "waiting", "when": waiting[key]}
        elif key in before:
            found[path] = {"path": path, "why": "uploaded", "when": iso(before[key])}
        elif key in same_file:
            found[path] = {"path": path, "why": "library", "match": _song(same_file[key])}

    # the same song by name: its title, with its artist or album in the file or folder names
    songs = [(p, s) for p, s in files if p not in found and formats.family(p) in MUSIC]
    if songs:
        index: dict[str, list] = {}
        rows = db.execute(select(Track.title, Track.artist, Track.albumartist, Track.album, Track.format, Track.path)
                          .where(Track.kind == "music", Track.peer_id.is_(None))
                          .execution_options(include_hidden=True))
        for t in rows:
            for key in title_keys(t.title or ""):
                index.setdefault(key, []).append(t)
        for path, _ in songs:
            folder, stem = os.path.split(os.path.splitext(path)[0])
            context = f" {norm(' '.join([folder, *_SEP.split(stem)[:-1]]))} "
            loose = not _LETTER.search(context)          # a bare title: nothing else to go by
            best, rank = None, None
            for title in titles(stem):
                for t in {id(t): t for k in title_keys(title) for t in index.get(k, ())}.values():
                    named = {norm(t.artist), norm(t.albumartist)} - {"", "various artists"}
                    albums = {a for a in (norm(t.album), base(t.album)) if len(a) > 2}
                    by_artist = any(f" {n} " in context for n in named)
                    on_album = any(f" {a} " in context for a in albums)
                    if not (by_artist or on_album or loose):
                        continue
                    same = (by_artist or on_album) and same_title(title, t.title)
                    # the same title on the same album beats a live or compilation version
                    if rank is None or (same, on_album, by_artist) > rank:
                        best, rank = t, (same, on_album, by_artist)
            if best:
                found[path] = {"path": path, "why": "library" if rank[0] else "similar", "match": _song(best)}

    # what goes with them
    skip = set(found)
    folders: dict[str, list[str]] = {}
    for path, _ in files:
        folders.setdefault(os.path.dirname(path), []).append(path)
    for paths in folders.values():
        playable = [p for p in paths if formats.family(p) is not None]
        others = [p for p in paths if formats.family(p) is None]
        if playable and all(p in found for p in playable):
            skip.update(others)
        else:
            skipped = {os.path.splitext(p)[0].lower() for p in playable if p in found}
            skip.update(p for p in others if os.path.splitext(p)[0].lower() in skipped)
    return {"found": [found[p] for p, _ in files if p in found], "skip": [p for p, _ in files if p in skip]}

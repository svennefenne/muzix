"""Whose a song is, to go to: the artist its own artist tag names, when the library has a page for them, rather
than its album's artist (a song on a compilation, filed under Various Artists; a guest's song on another
artist's album). The tag "A feat. B" names A, "A & B" names A (unless the library has "A & B" itself). Its
album's artist when they're one of its main artists ("A & B" on B's album, not "A feat. B"), as before. Various Artists isn't
anyone's: a compilation's song by someone without a page of their own has no artist to go to.

On an artist's page, "Appears on": the albums of others with songs whose tag names them first (appears_on())."""

import re
from collections.abc import Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

VARIOUS = {"various artists", "various artist", "various", "va", "v.a.", "v/a", "[unknown]"}
GUEST = re.compile(r"\s+[(\[]?(?:feat\.?|ft\.?|featuring|with|vs\.?)\s+", re.I)     # A feat. B, A (ft. B), A vs. B
AND = re.compile(r"\s*(?:&|,|;|\+)\s*|\s+(?:x|and|/)\s+", re.I)                     # A & B, A, B, A x B, A and B
CHUNK = 400         # names asked for at a time (SQLite's limit on a query's values)


def norm(name: str) -> str:
    return " ".join((name or "").split()).casefold()


def names(tag: str) -> tuple[list[str], set[str]]:
    """(those it may be, most likely first: the whole tag, its main artist before a "feat.", the first of them;
    its main artists, not its guests, norm()ed)."""
    whole = " ".join((tag or "").split())
    if not whole:
        return [], set()
    main = GUEST.split(whole, maxsplit=1)[0]
    first = AND.split(main)[0].strip()
    likely = list(dict.fromkeys(n for n in (whole, main.strip(), first) if n))
    return likely, {norm(n) for n in likely} | {norm(p) for p in AND.split(main) if p.strip()}


def _sqlite_lower(name: str) -> str:
    """As SQLite's lower() has it: ASCII letters only."""
    return "".join(c.lower() if c.isascii() else c for c in name)


def pages(db: Session, wanted: Iterable[str]) -> dict[str, int]:
    """{norm(name): artist id} of the names the library has an artist page for (hidden ones, and those left out
    for the account, aren't: the session leaves them out)."""
    from .models import Artist
    wanted = sorted({n for n in wanted if n})
    out: dict[str, int] = {}
    for i in range(0, len(wanted), CHUNK):
        part = wanted[i:i + CHUNK]
        rows = db.execute(select(Artist.id, Artist.name).where(or_(
            Artist.name.in_(part), func.lower(Artist.name).in_({_sqlite_lower(n) for n in part}))).order_by(Artist.id))
        for aid, name in rows:
            out.setdefault(norm(name), aid)
    asked = {norm(n) for n in wanted}
    return {k: v for k, v in out.items() if k in asked}


def credit(db: Session, tracks: list) -> dict[int, int | None]:
    """{song id: the artist to go to for it} (see above)."""
    from .models import Artist
    album_artists = {aid: name for aid, name in db.execute(select(Artist.id, Artist.name).where(
        Artist.id.in_({t.artist_id for t in tracks if t.artist_id})))} if tracks else {}
    said = {t.id: names(t.artist) for t in tracks}
    found = pages(db, (n for likely, _ in said.values() for n in likely))
    out: dict[int, int | None] = {}
    for t in tracks:
        likely, main = said[t.id]
        theirs = norm(album_artists.get(t.artist_id, "")) if t.artist_id else ""
        if not likely or (theirs and theirs in main):
            out[t.id] = t.artist_id
            continue
        own = next((found[norm(n)] for n in likely if norm(n) in found), None)
        out[t.id] = own if own is not None else (None if theirs in VARIOUS else t.artist_id)
    return out


def _like(name: str) -> str:
    return name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def appears_on(db: Session, artist, limit: int = 60) -> list:
    """The albums of others (Various Artists' compilations, another artist's with them as a guest) with a song
    whose tag names this artist first, newest first."""
    from .models import Album, Track
    if norm(artist.name) in VARIOUS:
        return []
    tags = set(db.scalars(select(Track.artist).where(
        Track.artist.like(_like(artist.name), escape="\\"), or_(Track.artist_id != artist.id, Track.artist_id.is_(None)),
        Track.album_id.is_not(None)).distinct()))
    me = norm(artist.name)
    # those that name it at all; then that it's them they name first, not another artist the library has
    # ("Simon & Garfunkel" isn't Simon's)
    maybe = {t: names(t)[0] for t in tags}
    maybe = {t: likely for t, likely in maybe.items() if me in {norm(n) for n in likely}}
    found = pages(db, (n for likely in maybe.values() for n in likely))
    mine = [t for t, likely in maybe.items()
            if next((found[norm(n)] for n in likely if norm(n) in found), None) == artist.id]
    if not mine:
        return []
    ids = set(db.scalars(select(Track.album_id).where(Track.artist.in_(mine)).distinct()))
    return list(db.scalars(select(Album).where(Album.id.in_(ids), or_(Album.artist_id != artist.id, Album.artist_id.is_(None)))
                           .order_by(Album.year.desc(), func.lower(Album.title)).limit(limit)))

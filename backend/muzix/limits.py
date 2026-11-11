"""What an admin leaves out for one account (Admin → Users): music by genre folder, by its artists'
genre tags (a tag takes its subgenres along: "death metal" also leaves out "melodic death metal";
it counts when it's one of the artist's main tags, or any of their tags if the admin says so), by artist, the untagged artists of chosen genre folders, and whole sections (VGM, Audiobooks,
Podcasts, Radio). Artists can be let through whatever else would leave them out.

It's applied where everything the pages show is read (db.py), so for that account the music isn't
there at all: not in lists, search, counts, radio, autoplay, streams or covers, and nothing says
something is missing. The account can't change it; only an admin can."""

import json
import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import Select, and_, func, literal_column, not_, or_, select

SECTIONS = ("vgm", "audiobooks", "podcasts", "radio")
MAX_ITEMS = 500
MAIN_TAG = 1 / 3        # a tag is one of an artist's main tags at a third of the weight of their strongest
CACHE_SECONDS = 60      # how long what's left out is kept before it's worked out again (new tags, scans)


@dataclass(frozen=True)
class Limits:
    genres: frozenset[str] = frozenset()     # genre folders (Album.genre); "" is music without one
    tags: tuple[str, ...] = ()               # genre tags, as norm() writes them
    untagged: frozenset[str] = frozenset()   # genre folders whose artists without tags are left out
    artists: frozenset[int] = frozenset()
    allow: frozenset[int] = frozenset()      # artists let through, whatever else says
    sections: frozenset[str] = frozenset()
    every_tag: bool = False                  # any of an artist's tags counts, not only their main ones

    @property
    def music(self) -> bool:
        return bool(self.genres or self.tags or self.untagged or self.artists)


def norm(tag: str) -> str:
    """A tag as rules compare it: "Hip-Hop" and "hip hop" are the same."""
    return " ".join(re.sub(r"[-_/]+", " ", tag.casefold()).split())


def clean(raw: dict | None) -> dict:
    """What's stored on the account (User.limits): only what's there, tidied."""
    raw = raw or {}

    def words(key, size):
        seen = {}
        for v in raw.get(key) or []:
            if isinstance(v, str) and len(v) <= size:
                seen.setdefault(v.strip(), None)
        return list(seen)[:MAX_ITEMS]

    def ids(key):
        return sorted({int(v) for v in raw.get(key) or [] if isinstance(v, int) and not isinstance(v, bool)})[:MAX_ITEMS]

    tags = list(dict.fromkeys(t for t in (norm(t) for t in words("tags", 100)) if t))
    out = {"genres": words("genres", 128), "tags": tags, "untagged": [g for g in words("untagged", 128) if g],
           "artists": ids("artists"), "allow": ids("allow"),
           "sections": [k for k in SECTIONS if k in (raw.get("sections") or [])], "every_tag": raw.get("every_tag") is True}
    return {k: v for k, v in out.items() if v}


def of(user) -> Limits | None:
    """The account's limits, or None when nothing is left out for it."""
    raw = getattr(user, "limits", None)
    if not raw:
        return None
    lim = Limits(genres=frozenset(raw.get("genres") or ()), tags=tuple(raw.get("tags") or ()),
                 untagged=frozenset(raw.get("untagged") or ()), artists=frozenset(raw.get("artists") or ()),
                 allow=frozenset(raw.get("allow") or ()), sections=frozenset(raw.get("sections") or ()),
                 every_tag=raw.get("every_tag") is True)
    return lim if lim.music or lim.sections else None


# ---------------------------------------------------------------- which artists

@dataclass(frozen=True)
class Left:
    """The artists a Limits leaves out, worked out from their tags and albums."""
    artists: tuple[int, ...]    # every album and song of theirs
    names: tuple[str, ...]      # their names, for songs on other artists' albums (compilations)
    untagged: tuple[int, ...]   # artists without tags: their albums in Limits.untagged


_cache: dict[Limits, tuple[float, Left]] = {}
_built: dict[Limits, tuple[Left, dict]] = {}     # criteria(), for as long as what they're made of
_lock = threading.Lock()


def forget():
    """Work it out again next time (the limits or the tags changed)."""
    with _lock:
        _cache.clear()
        _built.clear()


def left_out(lim: Limits) -> Left:
    with _lock:
        hit = _cache.get(lim)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
    left = _work_out(lim)
    with _lock:
        if len(_cache) > 64:
            _cache.clear()
            _built.clear()
        _cache[lim] = (time.monotonic(), left)
    return left


def main_tags(tags: list | None) -> list[str]:
    """An artist's tags that weigh at least a third of their strongest (tags without weights all do)."""
    weight = lambda t: t[1] if len(t) > 1 and isinstance(t[1], (int, float)) else 0   # noqa: E731
    top = max((weight(t) for t in tags or []), default=0)
    return [t[0] for t in tags or [] if weight(t) >= top * MAIN_TAG]


def _work_out(lim: Limits) -> Left:
    from . import db
    from .models import Album, Artist
    pattern = re.compile(r"(?<!\w)(?:%s)(?!\w)" % "|".join(map(re.escape, lim.tags))) if lim.tags else None
    with db.session() as s:     # a plain session: everything, whoever is asking
        folders: dict[int, set[str]] = defaultdict(set)
        for aid, genre in s.execute(select(Album.artist_id, Album.genre).where(Album.kind == "music",
                                                                                Album.artist_id.is_not(None)).distinct()):
            folders[aid].add(genre)
        rows = s.execute(select(Artist.id, Artist.name, Artist.genre, Artist.tags, Artist.other_tags)).all()
    artists, names, untagged = [], [], []
    for aid, name, genre, tags, other in rows:
        if aid in lim.allow:
            continue
        own = folders.get(aid) or {genre or ""}
        bare = not tags
        if bare and own & lim.untagged:
            untagged.append(aid)
        named = [t[0] for t in [*(tags or []), *(other or [])]] if lim.every_tag else [*main_tags(tags), *main_tags(other)]
        tagged = pattern is not None and any(pattern.search(norm(t)) for t in named)
        # left out by folder only when every album of theirs is
        folder = all(g in lim.genres or (bare and g in lim.untagged) for g in own)
        if aid in lim.artists or tagged or folder:
            artists.append(aid)
            names.append(name)
    return Left(tuple(sorted(artists)), tuple(sorted(names)), tuple(sorted(untagged)))


# ---------------------------------------------------------------- what the pages leave out

def _among(values) -> Select:
    """One of these values: hundreds of them go to SQLite as one JSON parameter, not one each."""
    return select(literal_column("value")).select_from(func.json_each(json.dumps(list(values))))


def _album_out(c, lim: Limits, left: Left):
    """Albums left out, on Album or its plain table's columns (c); None when none are."""
    parts = []
    if left.artists:
        parts.append(and_(c.artist_id.is_not(None), c.artist_id.in_(_among(left.artists))))
    if lim.genres:
        by_folder = c.genre.in_(sorted(lim.genres))
        if lim.allow:
            by_folder = and_(by_folder, or_(c.artist_id.is_(None), c.artist_id.not_in(_among(lim.allow))))
        parts.append(by_folder)
    if left.untagged:
        parts.append(and_(c.genre.in_(sorted(lim.untagged)), c.artist_id.is_not(None), c.artist_id.in_(_among(left.untagged))))
    return and_(c.kind == "music", or_(*parts)) if parts else None


def criteria(lim: Limits) -> dict:
    """{model: what of it the account sees}, for db.py's loader criteria."""
    from .models import Album, Artist, Track
    left = left_out(lim)
    with _lock:
        built = _built.get(lim)
    if built and built[0] is left:
        return built[1]
    out = {}
    if left.artists:
        out[Artist] = Artist.id.not_in(_among(left.artists))
    album_out = _album_out(Album, lim, left)
    if album_out is not None:
        out[Album] = not_(album_out)
    # the plain table, not Album: the loader criteria would otherwise leave the left-out albums out of this too
    albums = Album.__table__
    gone = _album_out(albums.c, lim, left)
    parts = []
    if gone is not None:
        parts.append(and_(Track.album_id.is_not(None), Track.album_id.in_(select(albums.c.id).where(gone))))
    if left.artists:
        parts.append(and_(Track.artist_id.is_not(None), Track.artist_id.in_(_among(left.artists))))
        parts.append(Track.artist.in_(_among(left.names)))
    if lim.genres:      # songs without an album: their own genre
        parts.append(and_(Track.album_id.is_(None), Track.genre.in_(sorted(lim.genres))))
    if parts:
        out[Track] = not_(and_(Track.kind == "music", or_(*parts)))
    with _lock:
        _built[lim] = (left, out)
    return out


def preview(lim: Limits | None, sample: int = 12) -> dict:
    """How much of the music a Limits leaves out, and the artists of most albums among it."""
    from types import SimpleNamespace

    from . import db
    from .models import Album, Artist, Track

    def counts(lim):
        s = db.SessionLocal()
        s.info["hide"] = True
        s.info["viewer"] = SimpleNamespace(network=True, limits=lim)
        try:
            return (s.scalar(select(func.count()).select_from(Artist)),
                    s.scalar(select(func.count()).select_from(Album).where(Album.kind == "music")),
                    s.scalar(select(func.count()).select_from(Track).where(Track.kind == "music")))
        finally:
            s.close()

    if lim is None or not lim.music:
        return {"artists": 0, "albums": 0, "songs": 0, "examples": []}
    everything, seen = counts(None), counts(lim)
    left = left_out(lim)
    with db.session() as s:
        examples = s.scalars(select(Artist.name).join(Album, Album.artist_id == Artist.id)
                             .where(Artist.id.in_(left.artists), Artist.hidden.is_(False))
                             .group_by(Artist.id).order_by(func.count().desc(), Artist.name).limit(sample)).all()
    return {"artists": everything[0] - seen[0], "albums": everything[1] - seen[1], "songs": everything[2] - seen[2],
            "examples": examples}

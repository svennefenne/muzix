"""Album, EP or single: the artist's page sorts their releases so, and an album's page and card say which.

MusicBrainz's release group type, as beets writes it in the files' tags (albumtypes: "album,live", "ep"...),
read when a song is scanned (meta/tags.py) and kept on the album (Album.release_tag). Without one (what
MusicBrainz didn't match: Bandcamp's, mostly) a guess: the title ("… EP", "… (Single)"), else the length, as
Spotify counts (up to 3 songs under 30 minutes a single, up to 6 an EP). An admin's choice
(Album.release_set) is over both.

A guessed one is looked up at MusicBrainz once, quietly, the first time its artist's page is opened (check_artist):
one artist at a time, at MusicBrainz's pace (a request a second); what isn't there stays a guess."""

import logging
import queue
import re
import threading
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

log = logging.getLogger("muzix.releases")

TYPES = ("album", "ep", "single")
SHORT = 30 * 60                     # seconds: shorter is a single's or an EP's length
NONE = "none"                       # release_tag of an album whose files were read, and had no type
EP = re.compile(r"(?:^|[\s(\[\-–—])e\.?p\.?(?:[)\]]|$)", re.I)
SINGLE = re.compile(r"(?:^|[\s(\[\-–—])single(?:[)\]]|$)", re.I)
VERSION = "1"                       # settings' release_tags_read: the albums scanned before had their files read


def from_tag(tag: str) -> str:
    """The primary type in MusicBrainz's ("album,live", "album/compilation"): album, ep or single; "" if none.
    Its broadcasts and others are albums here."""
    for t in re.split(r"[,;/]", (tag or "").lower()):
        t = t.strip()
        if t in TYPES:
            return t
        if t in ("broadcast", "other"):
            return "album"
    return ""


def classify(tag: str, title: str, tracks: int, seconds: float) -> tuple[str, bool]:
    """(type, guessed): the tags' type, else a guess from the title, then from the length."""
    if kind := from_tag(tag):
        return kind, False
    title = (title or "").strip()
    if EP.search(title):
        return "ep", True
    if SINGLE.search(title):
        return "single", True
    if 0 < tracks <= 3 and seconds < SHORT:
        return "single", True
    if 0 < tracks <= 6 and seconds < SHORT:
        return "ep", True
    return "album", True


def update(s: Session) -> int:
    """Every album's type worked out again (after a scan: new songs, new tags); the ones changed."""
    from .models import Album
    changed = 0
    for a in s.scalars(select(Album)):
        kind, guessed = classify(a.release_tag, a.title, a.track_count, a.duration)
        if (a.release_type, a.release_guessed) != (kind, guessed):
            a.release_type, a.release_guessed = kind, guessed
            changed += 1
    return changed


def _read_tags() -> int:
    """The albums scanned before types were read: one of each one's files read for its type."""
    from . import db
    from .meta import tags
    from .models import Album, Track
    with db.session() as s:
        todo = s.execute(select(Album.id, Track.path).join(Track, Track.album_id == Album.id)
                         .where(Album.release_tag == "", Album.peer_id.is_(None))
                         .order_by(Album.id, Track.disc_no, Track.track_no)).all()
    first: dict[int, str] = {}
    for aid, path in todo:
        first.setdefault(aid, path)
    found = {}
    for aid, path in first.items():
        try:
            found[aid] = tags.read(path).extra.get("albumtypes") or NONE
        except Exception:           # gone, or unreadable: a guess
            found[aid] = NONE
    with db.session() as s:
        for aid, tag in found.items():
            a = s.get(Album, aid)
            if a is not None and a.release_tag == "":
                a.release_tag = tag
        update(s)
    return len(found)


# ---------------------------------------------------------------- looked up at MusicBrainz, once

def _norm(text: str) -> str:
    return re.sub(r"[\W_]+", "", (text or "").casefold())


def _bare(title: str) -> str:
    """The title without a trailing "EP" or "(Single)", as MusicBrainz names the release group."""
    return SINGLE.sub("", EP.sub("", (title or "").strip())).strip(" -–—")


def match(groups: list[dict], artist: str, title: str) -> str:
    """MusicBrainz's types ("ep", "album,live") of the release group of the album's title by its artist; "" if
    none is: a title or an artist that's only alike isn't taken."""
    want_title, want_artist = _norm(_bare(title)), _norm(artist)
    for g in groups:
        if _norm(_bare(g.get("title", ""))) != want_title:
            continue
        credit = g.get("artist-credit") or []
        names = {_norm("".join(c.get("name", "") + c.get("joinphrase", "") for c in credit))}
        names |= {_norm(c.get("name", "")) for c in credit} | {_norm((c.get("artist") or {}).get("name", "")) for c in credit}
        primary = (g.get("primary-type") or "").lower()
        if want_artist in names and primary:
            return ",".join([primary] + [t.lower() for t in g.get("secondary-types") or []])
    return ""


def ask_musicbrainz(artist: str, title: str) -> list[dict]:
    """MusicBrainz's release groups of that title by that artist (its search: the closest first)."""
    from . import providers
    clean = lambda t: t.replace('"', " ").replace("\\", " ")      # noqa: E731  (inside the query's quotes)
    query = f'releasegroup:"{clean(_bare(title))}" AND artist:"{clean(artist)}"'
    with providers._client() as c:
        data = providers._get(c, "https://musicbrainz.org/ws/2/release-group", {"query": query, "fmt": "json", "limit": 10},
                              mb=True)
    return data.get("release-groups") or []


def _unchecked(artist_id: int):
    from .models import Album
    return select(Album).where(Album.artist_id == artist_id, Album.kind == "music", Album.peer_id.is_(None),
                               Album.release_set == "", Album.release_guessed.is_(True), Album.release_checked.is_(None))


def unchecked(s: Session, artist_id: int) -> bool:
    """Whether the artist has a guessed album not looked up yet."""
    return s.scalar(_unchecked(artist_id).limit(1)) is not None


def check_now(artist_id: int, ask=None) -> int:
    """The artist's guessed albums looked up (`ask`: MusicBrainz's search); the ones looked up. One that couldn't be
    (MusicBrainz didn't answer) is asked again the next time."""
    from . import db
    from .models import Album, Artist
    ask = ask or ask_musicbrainz
    with db.session() as s:
        artist = s.get(Artist, artist_id)
        todo = [(a.id, a.title) for a in s.scalars(_unchecked(artist_id))] if artist else []
        name = artist.name if artist else ""
    found: dict[int, str] = {}
    for aid, title in todo:
        try:
            found[aid] = match(ask(name, title), name, title)
        except Exception as e:
            log.info("release type of %s – %s: %s", name, title, e)
    with db.session() as s:
        for aid, tag in found.items():
            a = s.get(Album, aid)
            if a is None:
                continue
            a.release_checked = datetime.now(timezone.utc)
            if tag:
                a.release_tag = tag
            a.release_type, a.release_guessed = classify(a.release_tag, a.title, a.track_count, a.duration)
    return len(found)


_artists: "queue.Queue[int]" = queue.Queue()
_pending: set[int] = set()
_lock = threading.Lock()
_worker: threading.Thread | None = None


def _work():
    while True:
        aid = _artists.get()
        try:
            check_now(aid)
        except Exception:
            log.exception("release types of artist %s", aid)
        finally:
            with _lock:
                _pending.discard(aid)


def check_artist(artist_id: int) -> None:
    """Its guessed albums looked up in the background (one artist after another), unless it's already waiting."""
    global _worker
    with _lock:
        if artist_id in _pending:
            return
        _pending.add(artist_id)
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, name="release-lookups", daemon=True)
            _worker.start()
    _artists.put(artist_id)


def checking(artist_id: int) -> bool:
    """Whether the artist's albums are being looked up now (its page looks again in a moment)."""
    with _lock:
        return artist_id in _pending


def catch_up():
    """At start, once: the types of the albums scanned before they were read (Muzix 2026-11-13), in the
    background (a file of each album)."""
    from . import settings
    if settings.get("release_tags_read") == VERSION:
        return

    def run():
        try:
            n = _read_tags()
            settings.set_many({"release_tags_read": VERSION})
            log.info("release types: %d albums' files read", n)
        except Exception:
            log.exception("release types")
    threading.Thread(target=run, name="release-types", daemon=True).start()

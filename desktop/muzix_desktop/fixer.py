"""Fix Metadata & Artwork: albums dropped on the window, the sources' suggestions for each (the
same sources as the server's Edit metadata, muzix.providers), and the one the user picks written
into the songs' tags, with a cover. Depending on Settings the songs and the album folder are then
renamed where they are, or filed into the library folder the way the server files its own
(Genre/Artist/Artist - Year - Album). Everything done can be undone."""

import io
import logging
import os
from collections import Counter
from dataclasses import dataclass, field

import httpx
from PIL import Image

from . import config
from .shared import formats, manage, providers, tags, tagwrite

log = logging.getLogger(__name__)

DISC_FOLDER = ("cd", "disc", "disk")
ALBUM_SOURCES = {"musicbrainz", "deezer", "itunes", "bandcamp", "discogs"}
COVER_SOURCES = {"musicbrainz", "deezer", "itunes", "bandcamp", "discogs", "fanarttv", "web"}
PAIR_WITHIN = 20        # seconds a song may differ in length from the source's and still be it


class FixError(Exception):
    pass


@dataclass
class Song:
    path: str
    title: str = ""
    artist: str = ""
    albumartist: str = ""
    album: str = ""
    track_no: int = 0
    disc_no: int = 0
    year: int = 0
    genre: str = ""
    duration: float = 0


@dataclass
class Album:
    folder: str
    songs: list[Song] = field(default_factory=list)
    whole_folder: bool = True       # nothing else to play in its folder: the folder may be renamed

    def _most(self, values) -> str:
        values = [v for v in values if v]
        return Counter(values).most_common(1)[0][0] if values else ""

    @property
    def artist(self) -> str:
        return self._most(s.albumartist or s.artist for s in self.songs)

    @property
    def title(self) -> str:
        return self._most(s.album for s in self.songs) or os.path.basename(self.folder)

    @property
    def year(self) -> int:
        return max((s.year for s in self.songs), default=0)


def _album_folder(path: str) -> str:
    folder = os.path.dirname(path)
    name = os.path.basename(folder).lower()
    return os.path.dirname(folder) if name.startswith(DISC_FOLDER) and len(name) < 8 else folder


def _audio_under(folder: str) -> list[str]:
    out = []
    for d, dirs, names in os.walk(folder):
        dirs[:] = [x for x in dirs if not x.startswith(".")]
        out += [os.path.join(d, n) for n in names if not n.startswith(".") and formats.is_audio(os.path.join(d, n))]
    return out


def read_song(path: str) -> Song:
    try:
        t = tags.read(path)
    except Exception as e:
        log.info("can't read %s: %s", path, e)
        return Song(path=path, title=os.path.splitext(os.path.basename(path))[0])
    return Song(path=path, title=t.title, artist=t.artist, albumartist=t.albumartist, album=t.album,
                track_no=t.track_no, disc_no=t.disc_no, year=t.year, genre=t.genre, duration=t.duration)


def albums_from(paths: list[str]) -> list[Album]:
    """What was dropped as albums: the songs grouped by their album's folder (CD1/Disc 2 folders
    are one album). A folder of album folders gives each of them."""
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += _audio_under(p)
        elif os.path.isfile(p) and formats.is_audio(p):
            files.append(p)
    groups: dict[str, list[str]] = {}
    for f in dict.fromkeys(files):
        groups.setdefault(_album_folder(f), []).append(f)
    albums = []
    for folder, songs in sorted(groups.items()):
        a = Album(folder=folder, songs=sorted((read_song(p) for p in songs),
                                              key=lambda s: (s.disc_no, s.track_no, s.path)))
        a.whole_folder = set(_audio_under(folder)) <= set(songs)
        albums.append(a)
    return albums


# ------------------------------------------------------------ the sources

def search(artist: str, title: str) -> dict:
    """{results, errors}: the albums the sources switched on in Settings suggest."""
    only = config.load().enabled_sources() & ALBUM_SOURCES
    if not only:
        return {"results": [], "errors": {"settings": "No source is switched on in Settings"}}
    return providers.search("album", artist, title, only=only)


def details(source: str, id_: str) -> dict:
    try:
        return providers.details(source, "album", id_)
    except (providers.SourceError, httpx.HTTPError, ValueError, KeyError) as e:
        raise FixError(f"{source} couldn't give that album ({e or e.__class__.__name__})")


def other_covers(artist: str, title: str) -> dict:
    cfg = config.load()
    only = cfg.enabled_sources() & COVER_SOURCES
    web = f"{artist} {title} album cover" if "web" in only else ""
    return providers.covers("album", artist, title, web=web, only=only)


def pair(songs: list[Song], theirs: list[dict]) -> list[tuple[Song, dict | None]]:
    """Each song with the source's song it is: by length where the source has lengths (closest
    first), otherwise, or for what's left when both have as many, in order."""
    ours = sorted(songs, key=lambda s: (s.disc_no, s.track_no, s.path))
    match: dict[int, int] = {}
    if any(t.get("length") for t in theirs):
        pairs = sorted((abs(s.duration - t["length"]), i, j) for i, s in enumerate(ours) for j, t in enumerate(theirs)
                       if t.get("length") and s.duration)
        used = set()
        for diff, i, j in pairs:
            if diff > PAIR_WITHIN:
                break
            if i not in match and j not in used:
                match[i] = j
                used.add(j)
    if len(ours) == len(theirs):
        left = [j for j in range(len(theirs)) if j not in match.values()]
        for i in range(len(ours)):
            if i not in match and left:
                match[i] = left.pop(0)
    return [(s, theirs[match[i]] if i in match else None) for i, s in enumerate(ours)]


def fetch_cover(url: str) -> bytes:
    """A cover as JPEG, at most 1500 px."""
    try:
        with httpx.Client(headers={"User-Agent": providers.enrich.UA}, timeout=30, follow_redirects=True) as c:
            r = c.get(url)
            r.raise_for_status()
        img = Image.open(io.BytesIO(r.content))
        img.load()
    except (httpx.HTTPError, OSError) as e:
        raise FixError(f"Couldn't get the cover ({e or e.__class__.__name__})")
    img = img.convert("RGB")
    img.thumbnail((1500, 1500))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90)
    return out.getvalue()


# ------------------------------------------------------------ fixing

@dataclass
class Done:
    """What fixing an album did, to show and to undo."""
    folder: str                         # where the album was
    target: str                         # where it is now
    moves: dict[str, str]               # song paths: before → after
    tags: dict[str, dict]               # song path (before) → its tags before
    pictures: dict[str, dict]           # song path (before) → its pictures before
    cover: tuple[str, bytes | None] | None   # the cover file written (path before moving), what it held
    skipped: list[str]                  # songs whose tags couldn't be written


def _changes(song: Song, theirs: dict | None, album: dict, multi: bool) -> dict:
    want = {"albumartist": album["artist"], "album": album["title"], "year": album["year"]}
    if album.get("genre"):
        want["genre"] = album["genre"]
    if theirs:
        want.update(title=theirs["title"], artist=theirs.get("artist") or album["artist"],
                    track_no=theirs.get("no") or 0, disc_no=(theirs.get("disc") or 1) if multi else 0)
    return {k: v for k, v in want.items() if v != getattr(song, k)}


def apply(album: Album, chosen: dict, pairs: list[tuple[Song, dict | None]], cover: bytes | None) -> Done:
    """Writes the chosen album's tags (and cover) into the songs, then renames or files them as
    Settings say."""
    cfg = config.load()
    info = {"artist": chosen.get("artist") or album.artist, "title": chosen.get("title") or album.title,
            "year": chosen.get("year") or 0, "genre": chosen.get("genre") or ""}
    multi = len({(t or {}).get("disc") or 1 for _, t in pairs}) > 1
    done = Done(folder=album.folder, target=album.folder, moves={}, tags={}, pictures={}, cover=None, skipped=[])
    try:
        for song, theirs in pairs:
            changes = _changes(song, theirs, info, multi)
            if not tagwrite.writable(song.path):
                done.skipped.append(os.path.basename(song.path))
                continue
            done.tags[song.path] = tagwrite.snapshot(song.path, tagwrite.FIELDS)
            if cover and cfg.embed_cover:
                done.pictures[song.path] = tagwrite.pictures(song.path)
            if changes:
                tagwrite.write(song.path, changes)
            if cover and cfg.embed_cover:
                tagwrite.embed_cover(song.path, cover)
            for k, v in changes.items():
                setattr(song, k, v)
        if cover:
            path = os.path.join(album.folder, "cover.jpg")
            before = None
            if os.path.exists(path):
                with open(path, "rb") as f:
                    before = f.read()
            with open(path, "wb") as f:
                f.write(cover)
            done.cover = (path, before)
    except (tagwrite.TagError, OSError) as e:
        undo(done)
        raise FixError(f"Couldn't write the tags: {e}")
    if cfg.organize != "tags":
        try:
            _organize(album, info, done, cfg)
        except (manage.ManageError, OSError) as e:
            raise FixError(f"The tags are written, but the files couldn't be renamed: {e}")
    return done


def _organize(album: Album, info: dict, done: Done, cfg: config.Config):
    artist = info["artist"] or "Unknown Artist"
    songs = [{"path": s.path, "track_no": s.track_no, "disc_no": s.disc_no, "title": s.title or "Untitled",
              "artist": s.artist, "year": s.year} for s in album.songs]
    folder = album.folder
    if cfg.organize == "library" and cfg.library and album.whole_folder:
        top = manage.genre_folder(cfg.library, info["genre"]) or manage.broad_genre(info["genre"]) \
            or info["genre"] or manage.UNSORTED.title()
        target, moves = manage.plan(cfg.library, folder, {**info, "artist": artist}, songs, manage.clean(top))
    else:
        # rename where it is (the folder too, unless other songs are in it)
        target = manage.free(os.path.join(os.path.dirname(folder), manage.album_name(info, artist)), folder) \
            if album.whole_folder else folder
        moves = manage.song_names(target, folder, info, songs, artist)
    manage.refile(folder, target, moves)
    done.target, done.moves = target, moves
    for s in album.songs:
        s.path = moves.get(s.path, s.path)
    album.folder = target


def undo(done: Done):
    """Puts the album back as it was: its files where they were, its tags and its cover."""
    if done.moves or done.target != done.folder:
        manage.refile(done.target, done.folder, {new: old for old, new in done.moves.items()})
    if done.cover:
        path, before = done.cover
        if before is None:
            try:
                os.remove(path)
            except OSError:
                pass
        else:
            with open(path, "wb") as f:
                f.write(before)
    for path, snap in done.pictures.items():
        tagwrite.put_pictures(path, snap)
    for path, snap in done.tags.items():
        tagwrite.put_back(path, snap)

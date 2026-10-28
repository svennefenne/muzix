"""The admin's changes to the library: hiding things, the trash, and editing metadata and covers.

Hiding sets a flag that keeps an item out of every page (db.py leaves hidden rows out of web
requests); an album takes its songs with it, an artist their albums and songs.

Deleting moves the files into a ".muzix-trash" folder at the top of their library folder (the
scanner skips dot folders), so they can be put back until the trash is emptied. Playlists,
stations and podcasts have no files of their own and are simply removed.

Editing writes the new tags into the files (or, for chip and tracker formats that have none, keeps
them in TagOverride), then files an album in a music folder the way the rest of the library is
filed, "<Genre>/<Album artist>/<Artist - Year - Album>/<n>. <Artist> - <Album> - <Title> (<Year>)",
and reads the files again so the database matches what a scan would find.

Every edit leaves an EditRecord of what it changed: the tags it touched exactly as the files had
them, file and folder names, an item's own fields. `undo_edit` puts those back, unless something
has changed the same files or fields since (then the later edit has to be undone first).
"""

import functools
import hashlib
import io
import json
import logging
import os
import re
import shutil
import threading
import time
from collections import Counter
from datetime import datetime, timezone

import httpx
from PIL import Image, ImageOps
from sqlalchemy import delete, func, or_, select, update

from . import art, db, enrich, env, formats, jobs, scanner, serial
from .meta import tagwrite
from .models import (Album, Artist, Book, EditRecord, Episode, Feed, FilePlaylist, Like, Playlist, Root, Station,
                     TagOverride, Track, TrashItem)

log = logging.getLogger("muzix.manage")
TRASH = ".muzix-trash"
MODELS = {"album": Album, "track": Track, "artist": Artist, "book": Book, "podcast": Feed, "playlist": Playlist,
          "fileplaylist": FilePlaylist, "station": Station}
MAX_IMAGE = 20 * 1024 * 1024
DISC_FOLDER = re.compile(r"^(cd|disc|disk)\s*\d+$", re.I)


class ManageError(Exception):
    pass


def _row(s, kind: str, id_: int):
    model = MODELS.get(kind)
    if model is None:
        raise ManageError(f"Unknown kind of item: {kind}")
    row = s.get(model, id_)
    if row is None:
        raise ManageError("That item isn't there any more")
    return row


def _tidy_later():
    """Search and empty albums/artists catch up in the background."""
    def run():
        try:
            with db.session() as s:
                s.execute(delete(Album).where(~Album.id.in_(select(Track.album_id).where(Track.album_id.is_not(None)))))
                s.execute(delete(Artist).where(~Artist.id.in_(select(Track.artist_id).where(Track.artist_id.is_not(None))),
                                               ~Artist.id.in_(select(Album.artist_id).where(Album.artist_id.is_not(None)))))
            scanner.rebuild_search()
        except Exception:
            log.exception("tidying after an edit failed")
    threading.Thread(target=run, daemon=True, name="manage-tidy").start()


# ---------------------------------------------------------------- hiding

def set_hidden(kind: str, id_: int, hidden: bool):
    with db.session() as s:
        _row(s, kind, id_)
        if kind == "album":
            s.execute(update(Album).where(Album.id == id_).values(hidden=hidden))
            s.execute(update(Track).where(Track.album_id == id_).values(hidden=hidden))
        elif kind == "artist":
            albums = select(Album.id).where(Album.artist_id == id_)
            s.execute(update(Track).where(or_(Track.artist_id == id_, Track.album_id.in_(albums))).values(hidden=hidden))
            s.execute(update(Album).where(Album.artist_id == id_).values(hidden=hidden))
            s.execute(update(Artist).where(Artist.id == id_).values(hidden=hidden))
        else:
            s.execute(update(MODELS[kind]).where(MODELS[kind].id == id_).values(hidden=hidden))


def hidden_items() -> list[dict]:
    """What's hidden, at the level it was hidden (an artist, not each of their songs)."""
    out = []
    with db.session() as s:
        hidden_artists = set(s.scalars(select(Artist.id).where(Artist.hidden.is_(True))))
        hidden_albums = set(s.scalars(select(Album.id).where(Album.hidden.is_(True))))
        for a in s.scalars(select(Artist).where(Artist.hidden.is_(True)).order_by(Artist.name)):
            out.append({"kind": "artist", "id": a.id, "title": a.name, "subtitle": "Artist"})
        for a in s.scalars(select(Album).where(Album.hidden.is_(True)).order_by(Album.artist_name, Album.title)):
            if a.artist_id not in hidden_artists:
                out.append({"kind": "album", "id": a.id, "title": a.title, "subtitle": f"Album · {a.artist_name}",
                            "art": serial.art_url("album", a.id) if a.art else None})
        for t in s.scalars(select(Track).where(Track.hidden.is_(True)).order_by(Track.artist, Track.title)):
            if t.album_id not in hidden_albums and t.artist_id not in hidden_artists:
                out.append({"kind": "track", "id": t.id, "title": t.title, "subtitle": f"Song · {t.artist}"})
        for kind, model, label, name in (("book", Book, "Audiobook", "title"), ("podcast", Feed, "Podcast", "title"),
                                         ("playlist", Playlist, "Playlist", "name"), ("fileplaylist", FilePlaylist, "Playlist file", "name"),
                                         ("station", Station, "Radio station", "name")):
            for r in s.scalars(select(model).where(model.hidden.is_(True))):
                out.append({"kind": kind, "id": r.id, "title": getattr(r, name) or "", "subtitle": label})
    return out


# ---------------------------------------------------------------- the trash

def _root_for(s, path: str) -> Root | None:
    roots = [r for r in s.scalars(select(Root)) if path == r.path or path.startswith(r.path.rstrip("/") + "/")]
    return max(roots, key=lambda r: len(r.path), default=None)


def _writable(path: str) -> bool:
    return os.access(path if os.path.isdir(path) else os.path.dirname(path), os.W_OK)


def album_dir(paths: list[str]) -> str:
    """The folder that holds an album's files ("CD 1"/"CD 2" folders: the one above them)."""
    folder = os.path.commonpath([os.path.dirname(p) for p in paths]) if paths else ""
    if DISC_FOLDER.match(os.path.basename(folder)):
        folder = os.path.dirname(folder)
    return folder


def _owns_folder(folder: str, paths: set[str], root: str) -> bool:
    """Whether every audio file in `folder` (and below) is one of `paths`: the folder is the album's own."""
    if not folder or os.path.normpath(folder) == os.path.normpath(root) or not folder.startswith(root.rstrip("/") + "/"):
        return False
    for d, dirs, files in os.walk(folder):
        dirs[:] = [x for x in dirs if not x.startswith(".")]
        for f in files:
            if formats.is_audio(f) and os.path.join(d, f) not in paths:
                return False
    return True


def _move(src: str, dst: str):
    if os.path.lexists(dst):
        raise ManageError(f"{dst} is already there; nothing was moved over it")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        os.rename(src, dst)
    except OSError as e:
        if e.errno != 18:          # EXDEV: another file system
            raise
        shutil.move(src, dst)


def _to_trash(root: Root, kind: str, title: str, subtitle: str, sources: list[str]) -> TrashItem:
    """Moves files or folders into the root's trash, remembering where they were."""
    folder = os.path.join(root.path, TRASH, time.strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}-{time.monotonic_ns() % 100000}")
    moves, size = [], 0
    try:
        for src in sources:
            dst = os.path.join(folder, os.path.relpath(src, root.path))
            if os.path.isdir(src):
                size += sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(src) for f in fs)
            elif os.path.exists(src):
                size += os.path.getsize(src)
            else:
                continue
            _move(src, dst)
            moves.append([src, dst])
    except (OSError, ManageError):
        for src, dst in reversed(moves):       # put back what was moved
            try:
                os.rename(dst, src)
            except OSError:
                log.error("couldn't put %s back from the trash", src)
        raise
    return TrashItem(kind=kind, title=title, subtitle=subtitle, root_id=root.id, folder=folder, moves=moves, size=size)


def _forget_tracks(s, track_ids: list[int]):
    album_ids = set(s.scalars(select(Track.album_id).where(Track.id.in_(track_ids))))
    for chunk in range(0, len(track_ids), 900):
        part = track_ids[chunk:chunk + 900]
        s.execute(delete(Like).where(Like.item_type == "track", Like.item_id.in_(part)))
        s.execute(delete(Track).where(Track.id.in_(part)))
    gone = [a for a in album_ids if a and not s.scalar(select(func.count()).select_from(Track).where(Track.album_id == a))]
    if gone:
        s.execute(delete(Like).where(Like.item_type == "album", Like.item_id.in_(gone)))
        s.execute(delete(Album).where(Album.id.in_(gone)))


def delete_item(kind: str, id_: int) -> dict:
    """Into the trash (files), or gone (playlists, stations, podcasts). {trash_id} or {removed: True}."""
    with db.session() as s:
        row = _row(s, kind, id_)
        if kind in ("playlist", "station"):
            s.delete(row)
            return {"removed": True}
        if kind == "podcast":
            for (path,) in s.execute(select(Episode.local_path).where(Episode.feed_id == id_, Episode.local_path != "")):
                try:
                    os.remove(path)         # Muzix's own download of an episode
                except OSError:
                    pass
            s.delete(row)
            return {"removed": True}
        if kind == "book":
            root = _root_for(s, row.path)
            if root is None or not _writable(row.path):
                raise ManageError("The audiobook folder is read-only for Muzix: hide the book instead")
            item = _to_trash(root, "book", row.title, row.author, [row.path])
            s.delete(row)
        elif kind == "fileplaylist":
            root = _root_for(s, row.path)
            if root is None or not _writable(row.path):
                raise ManageError("That playlist's folder is read-only for Muzix")
            item = _to_trash(root, "playlist", row.name, "Playlist file", [row.path])
            s.delete(row)
        else:
            if kind == "track":
                tracks = list(s.scalars(select(Track).where(Track.path == row.path)))   # every song of a chip file
                title, subtitle = row.title, row.artist
            elif kind == "album":
                tracks = list(s.scalars(select(Track).where(Track.album_id == id_)))
                title, subtitle = row.title, row.artist_name
            else:
                albums = select(Album.id).where(Album.artist_id == id_)
                tracks = list(s.scalars(select(Track).where(or_(Track.artist_id == id_, Track.album_id.in_(albums)))))
                title, subtitle = row.name, "Artist"
            if not tracks:
                raise ManageError("There are no files to delete")
            root = s.get(Root, tracks[0].root_id)
            paths = sorted({t.path for t in tracks})
            if any(not _writable(p) for p in paths):
                raise ManageError("That folder is read-only for Muzix: hide it instead")
            # whole album folders where the folder is the album's own; single files otherwise
            sources, left = [], set(paths)
            if kind != "track":
                for t in tracks:
                    if t.album_id:
                        album_paths = {x.path for x in tracks if x.album_id == t.album_id}
                        folder = album_dir(sorted(album_paths))
                        if folder not in sources and _owns_folder(folder, set(paths), root.path):
                            sources.append(folder)
                            left -= {p for p in left if p.startswith(folder + "/")}
            sources += sorted(left)
            item = _to_trash(root, kind, title, subtitle, sources)
            _forget_tracks(s, [t.id for t in tracks])
            if kind == "artist":
                s.execute(delete(Like).where(Like.item_type == "artist", Like.item_id == id_))
        s.add(item)
        s.flush()
        trash_id = item.id
    _tidy_later()
    return {"trash_id": trash_id}


def trash_items() -> list[dict]:
    with db.session() as s:
        return [{"id": t.id, "kind": t.kind, "title": t.title, "subtitle": t.subtitle, "size": t.size,
                 "files": len(t.moves), "created_at": _utc(t.created_at),
                 "where": os.path.dirname(t.moves[0][0]) if t.moves else ""}
                for t in s.scalars(select(TrashItem).order_by(TrashItem.created_at.desc()))]


def _utc(when) -> str | None:
    """SQLite gives times back without their zone; they're UTC."""
    if when is None:
        return None
    return (when if when.tzinfo else when.replace(tzinfo=timezone.utc)).isoformat()


def restore(trash_id: int) -> dict:
    """Puts the files back where they were and rescans their library folder."""
    with db.session() as s:
        item = s.get(TrashItem, trash_id)
        if item is None:
            raise ManageError("That's no longer in the trash")
        albums = {t.album_id for t in _tracks_in(s, os.path.dirname(item.moves[0][0]))} if item.kind == "cover" else set()
        root_id = _restore(s, item)
    art.changed("album", *albums)
    job = jobs.submit("scan", "Scan after putting back from the trash", root_id=root_id) if root_id else None
    return {"job_id": job}


def _restore(s, item: TrashItem) -> int | None:
    """A cover that was replaced swaps places with the one that replaced it, and goes into its
    album's files again."""
    clash = [src for src, _ in item.moves if os.path.lexists(src)]
    root = s.get(Root, item.root_id) if item.root_id else None
    swap = item.kind == "cover" and len(item.moves) == 1 and clash and os.path.isfile(clash[0]) and root
    if clash and not swap:
        raise ManageError(f"Something new is already at {clash[0]}; nothing was put back")
    if swap:        # the cover that replaced it goes into the trash in its place, with the pictures it put in the files
        now = _pictures_of(_tracks_in(s, os.path.dirname(clash[0])))
        newer = _to_trash(root, "cover", item.title, item.subtitle, clash)
        s.add(newer)
        _save_pictures(now, os.path.join(newer.folder, EMBEDDED))
    for src, dst in item.moves:
        _move(dst, src)
    if item.kind == "cover" and not _put_pictures(os.path.join(item.folder, EMBEDDED)):
        _embed_again(s, item.moves[0][0])       # trashed before Muzix kept the pictures
    _remove_empty(item.folder)
    root_id = item.root_id
    s.delete(item)
    return root_id


EMBEDDED = ".muzix-embedded.json"      # in a trashed cover's trash folder: the pictures its files had


def _tracks_in(s, folder: str) -> list[Track]:
    """The songs of the album in `folder` (and its CD folders)."""
    return [t for t in s.scalars(select(Track).where(Track.path.startswith(folder + "/", autoescape=True)))
            if album_dir([t.path]) == folder]


def _pictures_of(tracks: list[Track]) -> dict:
    """The pictures embedded in the files, before a new cover replaces them:
    {"files": {path: key or None}, "pictures": {key: snapshot}}, each picture kept once."""
    out = {"files": {}, "pictures": {}}
    for t in tracks:
        if not _taggable(t):
            continue
        try:
            snap = tagwrite.pictures(t.path)
        except (tagwrite.TagError, OSError):
            continue
        key = hashlib.sha1(json.dumps(snap, sort_keys=True).encode()).hexdigest()
        out["pictures"].setdefault(key, snap)
        out["files"][t.path] = key
    return out


def _save_pictures(saved: dict, path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(saved, f)


def _put_pictures(path: str) -> bool:
    """The pictures saved in `path` back into the files that are still where they were."""
    try:
        with open(path) as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return False
    for file, key in saved["files"].items():
        if os.path.exists(file):
            try:
                tagwrite.put_pictures(file, saved["pictures"][key])
            except (tagwrite.TagError, OSError) as e:
                log.warning("couldn't put the pictures back into %s: %s", file, e)
    os.remove(path)
    return True


def _embed_again(s, cover: str):
    """A cover put back from the trash goes into its album's files again, as setting it did."""
    folder = os.path.dirname(cover)
    try:
        with open(cover, "rb") as f:
            small = _jpeg(f.read(), 600)
    except (OSError, ManageError):
        return
    tracks = _tracks_in(s, folder)
    for t in tracks:
        if _taggable(t):
            try:
                tagwrite.embed_cover(t.path, small)
            except (tagwrite.TagError, OSError) as e:
                log.warning("couldn't put the cover back into %s: %s", t.path, e)
    for aid in {t.album_id for t in tracks if t.album_id}:
        s.get(Album, aid).art = cover


def empty_trash(trash_id: int | None = None) -> int:
    """Deletes trashed files for good: one item, or everything. Returns how many items went."""
    with db.session() as s:
        items = [s.get(TrashItem, trash_id)] if trash_id else list(s.scalars(select(TrashItem)))
        n = 0
        for item in items:
            if item is None:
                continue
            if item.folder and os.path.basename(os.path.dirname(item.folder)) == TRASH:
                shutil.rmtree(item.folder, ignore_errors=True)
            s.delete(item)
            n += 1
    return n


def _remove_empty(folder: str):
    """The trash folder an item came out of, if nothing else is in it (it only ever held that item)."""
    for d, _, _ in sorted(os.walk(folder, topdown=False), key=lambda x: -len(x[0])):
        try:
            os.rmdir(d)
        except OSError:
            pass


# ---------------------------------------------------------------- reading an item for the edit window

def _taggable(t: Track) -> bool:
    return formats.family(t.format) in ("native", "decode") and tagwrite.writable(t.path)


def details(kind: str, id_: int) -> dict:
    with db.session() as s:
        return {**_details(s, kind, id_), "last_edit": last_edit(s, kind, id_)}


def _details(s, kind: str, id_: int) -> dict:
    row = _row(s, kind, id_)
    if kind == "album":
        tracks = list(s.scalars(select(Track).where(Track.album_id == id_).order_by(Track.disc_no, Track.track_no, Track.path)))
        root = s.get(Root, tracks[0].root_id) if tracks else None
        folder = album_dir(sorted({t.path for t in tracks}))
        return {"kind": kind, "id": id_, "title": row.title, "artist": row.artist_name, "year": row.year,
                "genre": row.genre, "folder": folder, "hidden": row.hidden,
                "art": serial.art_url("album", id_) if row.art else None,
                "files": "music" if root and root.kind == "music" else root.kind if root else "",
                "writable": bool(tracks) and _writable(tracks[0].path),
                "tags": "files" if tracks and all(_taggable(t) for t in tracks) else "muzix",
                "tracks": [{"id": t.id, "title": t.title, "artist": t.artist, "track_no": t.track_no,
                            "disc_no": t.disc_no, "duration": t.duration, "format": t.format} for t in tracks]}
    if kind == "track":
        return {"kind": kind, "id": id_, "title": row.title, "artist": row.artist, "albumartist": row.albumartist,
                "album": row.album, "album_id": row.album_id, "track_no": row.track_no, "disc_no": row.disc_no,
                "year": row.year, "genre": row.genre, "path": row.path, "format": row.format, "hidden": row.hidden,
                "duration": row.duration,
                "art": serial.art_url("album", row.album_id),
                "writable": _writable(row.path), "tags": "files" if _taggable(row) else "muzix"}
    if kind == "artist":
        # what a new name changes: their albums, and their songs on no album of theirs
        theirs = select(Album.id).where(Album.artist_id == id_)
        albums = s.scalar(select(func.count()).select_from(theirs.subquery()))
        n = s.scalar(select(func.count()).select_from(Track).where(
            or_(Track.album_id.in_(theirs), (Track.artist_id == id_) & ~Track.album_id.in_(theirs))))
        # where their albums are filed (Genre / Artist), for saying where a new name moves them
        folders = {}
        for path, root in s.execute(select(Track.path, Root.path).join(Root, Root.id == Track.root_id)
                                    .where(Track.album_id.in_(theirs), Root.kind == "music")):
            folder = os.path.relpath(os.path.dirname(os.path.dirname(path)), root)
            folders[folder] = folders.get(folder, 0) + 1
        return {"kind": kind, "id": id_, "name": row.name, "songs": n, "albums": albums, "hidden": row.hidden,
                "folders": sorted(folders, key=lambda f: -folders[f])[:3] if "." not in folders else [],
                "art": serial.art_url("artist", id_)}
    if kind == "book":
        return {"kind": kind, "id": id_, "title": row.title, "author": row.author, "narrator": row.narrator,
                "series": row.series, "year": row.year, "description": row.description, "hidden": row.hidden,
                "art": serial.art_url("book", id_) if row.art else None}
    if kind == "podcast":
        return {"kind": kind, "id": id_, "title": row.title, "author": row.author, "description": row.description,
                "image": row.image, "hidden": row.hidden}
    if kind == "playlist":
        return {"kind": kind, "id": id_, "name": row.name, "description": row.description, "hidden": row.hidden}
    if kind == "fileplaylist":
        return {"kind": kind, "id": id_, "name": row.name, "path": row.path, "hidden": row.hidden,
                "writable": _writable(row.path)}
    return {"kind": kind, "id": id_, "name": row.name, "favicon": row.favicon, "hidden": row.hidden}


# ---------------------------------------------------------------- filing

ILLEGAL = re.compile(r'[<>:"?*|\\/\x00-\x1f]')


def clean(name: str) -> str:
    """A tag as a file or folder name, the way beets makes them."""
    name = ILLEGAL.sub("_", name.strip())
    name = re.sub(r"^\.", "_", name)
    name = name.rstrip(". ")
    return name[:200] or "_"


UNSORTED = "uncategorized"
KEEP_PLACE = {"duplicates", "other formats"}      # albums in these stay there when edited


@functools.cache
def _genre_rules():
    """The genre rules uploads are filed by. They come with beets (the organize extra); without
    it only a genre named like a folder finds one."""
    try:
        from .organize.beetsplug import musicorg
        return musicorg, musicorg.GenreMapper()
    except (ImportError, OSError):
        return None


def broad_genre(genre: str) -> str | None:
    """The main genre uploads would file a genre under ("Doom Metal": Metal), if any."""
    rules = _genre_rules()
    if not rules:
        return None
    mo, mapper = rules
    scores, ambiguous = Counter(), []
    for tag in mo.split_genre_string(genre):
        weight = 0.5 if mo.hk(mapper.normalize(tag)) in mo.GENERIC else 1.0
        shares, amb = mapper.map(tag)
        for g, share in shares.items():
            scores[g] += weight * share
        if amb:
            ambiguous.append((amb, weight))
    for candidates, weight in ambiguous:      # as for uploads: to whichever already leads
        best = max(candidates, key=lambda g: scores[g])
        if scores[best] > 0:
            scores[best] += weight
    return max(scores, key=scores.get) if scores else None


def genre_folder(root: str, genre: str) -> str | None:
    """The library's folder for albums of this genre: the one named like it, or the one uploads
    would file it in. None when none fits."""
    genre = genre.strip()
    try:
        tops = [f for f in os.listdir(root) if os.path.isdir(os.path.join(root, f))]
    except OSError:
        return None
    folders = {f.casefold(): f for f in tops if f.casefold() not in KEEP_PLACE | {UNSORTED}}
    if not genre:
        return None
    return folders.get(genre.casefold()) or folders.get((broad_genre(genre) or "").casefold())


def _filed_under(root: str, folder: str, genre: str, changed: bool) -> tuple[str, bool]:
    """(the genre folder an edited album is filed in, whether it looked for one and none fits):
    its genre's when the edit changes its genre or it's in Uncategorized, otherwise where it is.
    Duplicates and Other formats keep theirs."""
    top = os.path.relpath(folder, root).split(os.sep)[0]
    if top.casefold() in KEEP_PLACE or not (changed or top.casefold() == UNSORTED):
        return top, False
    to = genre_folder(root, genre)
    return to or top, to is None


def filing(id_: int, genre: str) -> dict:
    """Where saving the album with this genre files it: {"now", "then", "no_fit"} (genre folders)."""
    with db.session() as s:
        alb = _row(s, "album", id_)
        rows = s.execute(select(Track.path, Track.root_id).where(Track.album_id == id_)).all()
        root = s.get(Root, rows[0].root_id) if rows else None
        current = alb.genre
    if root is None or root.kind != "music":
        return {"now": None, "then": None, "no_fit": False}
    folder = album_dir(sorted({r.path for r in rows}))
    then, no_fit = _filed_under(root.path, folder, genre, genre.strip() != current)
    return {"now": os.path.relpath(folder, root.path).split(os.sep)[0], "then": then, "no_fit": no_fit}


def _plan(root: str, folder: str, album: dict, tracks: list[dict], top: str | None = None) -> tuple[str, dict[str, str]]:
    """(the album's new folder, {old path: new path}) under root/<Genre>/<Album artist>/<Artist - Year - Album>:
    the genre folder `top`, or the one it's in."""
    parts = os.path.relpath(folder, root).split(os.sep)
    top = top or parts[0]
    artist = album["artist"] or parts[1]
    year = album["year"]
    name = clean(f"{artist} - {year} - {album['title']}" if year else f"{artist} - {album['title']}")
    target = os.path.join(root, top, clean(artist), name)
    n = 1
    while os.path.normpath(target) != os.path.normpath(folder) and os.path.lexists(target):
        n += 1
        target = os.path.join(root, top, clean(artist), f"{name} [{n}]")
    # track names: "<n>. <Artist> - <Album> - <Title> (<Year>)"; "<disc>-<n>" when numbers repeat across discs
    nums = [t["track_no"] for t in tracks if t["track_no"]]
    multi = len(nums) != len(set(nums))
    moves, taken = {}, set()
    for t in tracks:
        sub = os.path.relpath(os.path.dirname(t["path"]), folder)
        stem = f"{t['artist'] or artist} - {album['title']} - {t['title']}" + (f" ({t['year'] or year})" if (t["year"] or year) else "")
        if t["track_no"]:
            num = f"{t['disc_no']}-{t['track_no']}" if multi and t["disc_no"] else str(t["track_no"])
            stem = f"{num}. {stem}"
        stem = clean(stem)
        ext = os.path.splitext(t["path"])[1]
        name, k = stem + ext, 1
        while name.casefold() in taken:
            k += 1
            name = f"{stem} ({k}){ext}"
        taken.add(name.casefold())
        moves[t["path"]] = os.path.normpath(os.path.join(target, sub, name))
    return target, moves


def _refile(folder: str, target: str, moves: dict[str, str]) -> dict[str, str]:
    """Moves the album folder, then renames its files; undoes what it did if a step fails."""
    done_folder = False
    renamed = []
    try:
        if os.path.normpath(target) != os.path.normpath(folder):
            _move(folder, target)
            done_folder = True
        inside = {old: os.path.join(target, os.path.relpath(old, folder)) for old in moves}
        temp = {}
        for i, old in enumerate(moves):          # two steps, so A→B and B→A swaps can't collide
            cur = inside[old]
            if cur == moves[old]:
                continue
            tmp = os.path.join(os.path.dirname(cur), f".muzix-rename-{i}{os.path.splitext(cur)[1]}")
            os.rename(cur, tmp)
            renamed.append((tmp, cur))
            temp[old] = tmp
        for old, tmp in temp.items():
            if os.path.lexists(moves[old]):
                raise ManageError(f"{moves[old]} is already there")
            os.rename(tmp, moves[old])
            renamed.append((moves[old], tmp))
    except (OSError, ManageError):
        for a, b in reversed(renamed):
            try:
                os.rename(a, b)
            except OSError:
                log.error("couldn't undo the rename of %s", a)
        if done_folder:
            try:
                os.rename(target, folder)
            except OSError:
                log.error("couldn't move %s back", target)
        raise
    return moves


# ---------------------------------------------------------------- editing

TRACK_FIELDS = ("title", "artist", "albumartist", "album", "track_no", "disc_no", "year", "genre")


def _clean_fields(fields: dict) -> dict:
    out = {}
    for k, v in fields.items():
        if k not in TRACK_FIELDS:
            continue
        if k in ("track_no", "disc_no", "year"):
            try:
                v = int(v or 0)
            except (TypeError, ValueError):
                raise ManageError(f"{k.replace('_no', '').title()} has to be a number")
        else:
            v = str(v or "").strip()
        out[k] = v
    return out


def _write(s, t: Track, changes: dict):
    """Into the file's tags, or (no tags to write) into the overrides."""
    if not changes:
        return
    if _taggable(t):
        try:
            tagwrite.write(t.path, changes)
        except (tagwrite.TagError, OSError) as e:
            raise ManageError(f"Couldn't write the tags of {os.path.basename(t.path)}: {e}")
    else:
        o = s.get(TagOverride, (t.path, t.subsong))
        if o is None:
            s.add(TagOverride(path=t.path, subsong=t.subsong, fields=changes))
        else:
            o.fields = {**o.fields, **changes}


def _reread(s, root: Root, ids_paths: list[tuple[int, int, str]], resolver: scanner.Resolver):
    """Reads files again (after an edit or a move) into their rows, albums and artists included."""
    overrides = scanner.load_overrides(s, root.path)
    for tid, subsong, path in ids_paths:
        rows = {r["subsong"]: r for r in scanner.read_file(path, root.kind)}
        row = rows.get(subsong) or (next(iter(rows.values())) if rows else None)
        if row is None:
            continue
        row.update(overrides.get((path, row["subsong"]), {}))
        st = os.stat(path)
        row.update(path=path, size=st.st_size, mtime=st.st_mtime, root_id=root.id)
        if not row["album"]:
            row["album"] = os.path.basename(os.path.dirname(path))
        row["artist_id"] = resolver.artist(s, row["albumartist"] or row["artist"])
        row["album_id"] = resolver.album(s, row, path)
        s.execute(update(Track).where(Track.id == tid).values(**row))


def _rekey(s, alb: Album, first: Track, title: str):
    """The album's key for its new folder and title, so reading its files again finds this album
    (its id, cover, likes and hidden state stay) instead of making a new one."""
    key = scanner.album_key({"kind": first.kind, "subsong": first.subsong, "album": title}, first.path)
    if key != alb.key and s.scalar(select(func.count()).select_from(Album).where(Album.key == key)) == 0:
        alb.key, alb.folder, alb.title = key, os.path.dirname(first.path), title


def _summarize(s, album_ids: set[int]):
    """An album's own fields from its tracks, as finish_scan works them out."""
    for aid in album_ids:
        tracks = list(s.scalars(select(Track).where(Track.album_id == aid)))
        alb = s.get(Album, aid)
        if alb is None:
            continue
        if not tracks:
            s.delete(alb)
            continue
        common = lambda f: max({getattr(t, f) for t in tracks}, key=lambda v: sum(getattr(t, f) == v for t in tracks))
        alb.track_count = len(tracks)
        alb.duration = sum(t.duration for t in tracks)
        alb.year = max(t.year for t in tracks)
        alb.genre = common("genre") or alb.genre
        alb.artist_name = max({t.albumartist or t.artist for t in tracks},
                              key=lambda v: sum((t.albumartist or t.artist) == v for t in tracks))
        alb.artist_id = common("artist_id") or alb.artist_id     # a new album artist: the album goes to them
        alb.title = common("album") or alb.title
        alb.formats = ",".join(sorted({t.format for t in tracks}))
        alb.folder = os.path.dirname(tracks[0].path)


def _unchanged(t: Track) -> bool:
    """Whether the file is still the one Muzix last read (same size and time)."""
    try:
        st = os.stat(t.path)
    except OSError:
        return False
    return st.st_size == t.size and abs(st.st_mtime - t.mtime) < 1


def _check_unchanged(rows: list[Track]):
    stale = [t for t in rows if not _unchanged(t)]
    if stale:
        raise ManageError(f"{os.path.basename(stale[0].path)} isn't as Muzix last read it (changed, or not there); "
                          "scan the library folder first (Admin → Library folders), then edit again")


def _set_paths(s, moves: list[tuple[Track, str]]):
    """Songs to their new paths, through temporary ones: when songs swap names, a path can't be
    two songs' at once, even for a moment."""
    moves = [(t, new) for t, new in moves if t.path != new]
    if not moves:
        return
    for t, _ in moves:
        t.path = f"{t.path}\x00moving-{t.id}"
    s.flush()
    for t, new in moves:
        t.path = new
    s.flush()


def _put_files_back(before: list[dict], refiled: tuple | None):
    """After an edit failed halfway: the files' names and tags as they were, matching the database
    (whose changes are rolled back) again."""
    try:
        if refiled:
            folder, target, moves = refiled
            _refile(target, folder, {new: old for old, new in moves.items()})
        for e in before:
            if "tags" in e and os.path.exists(e["was"]):
                tagwrite.put_back(e["was"], e["tags"])
    except Exception:
        log.exception("couldn't put the files back after a failed edit")


def _and(words: list[str]) -> str:
    return " and ".join([", ".join(words[:-1]), words[-1]] if len(words) > 1 else words)


def _before(s, t: Track, changes: dict) -> dict:
    """A file as it was before an edit: where it was, and the tags (or overrides) behind `changes`."""
    e = {"id": t.id, "subsong": t.subsong, "was": t.path, "fields": sorted(changes)}
    if not changes:
        return e
    if _taggable(t):
        try:
            e["tags"] = tagwrite.snapshot(t.path, changes)
        except (tagwrite.TagError, OSError) as err:
            raise ManageError(f"Couldn't read the tags of {os.path.basename(t.path)}: {err}")
    else:
        o = s.get(TagOverride, (t.path, t.subsong))
        e["override"] = dict(o.fields) if o else None
    return e


def _after(s, before: list[dict], paths: dict[int, str]) -> list[dict]:
    """The files an edit changed or moved, each also with its tags as the edit left them (to tell
    later whether something has changed them since)."""
    out = []
    for e in before:
        e["path"] = paths.get(e["id"], e["was"])
        if e["fields"]:
            if "tags" in e:
                e["tags_after"] = tagwrite.snapshot(e["path"], e["fields"])
            else:
                o = s.get(TagOverride, (e["path"], e["subsong"]))
                e["override_after"] = dict(o.fields) if o else None
        if e["fields"] or e["path"] != e["was"]:
            out.append(e)
    return out


def _remember(s, kind: str, item_id: int, title: str, summary: str, undo: dict) -> int:
    rec = EditRecord(kind=kind, item_id=item_id, title=title, summary=summary, undo=undo)
    s.add(rec)
    s.flush()
    return rec.id


def edit_album(id_: int, fields: dict, tracks: list[dict], remember: bool = True, by_genre: bool = True) -> dict:
    """The album's fields (title, artist, year, genre) and its songs' (title, artist, track_no,
    disc_no): into the files, then the album filed by its new tags (`by_genre`: in the folder of
    a new genre, or of its genre when it's in Uncategorized). With `remember`, the edit is kept in
    the list of edits to undo; otherwise what undoes it comes back as "undo"."""
    album_level = {"album": fields.get("title"), "albumartist": fields.get("artist"),
                   "year": fields.get("year"), "genre": fields.get("genre")}
    album_level = _clean_fields({k: v for k, v in album_level.items() if v is not None})
    per_track = {int(t["id"]): _clean_fields(t) for t in tracks if "id" in t}
    notes = []
    with db.session() as s:
        alb = _row(s, "album", id_)
        title_before, art_before = alb.title, alb.art
        # only what changed: the window sends every field
        current = {"album": alb.title, "albumartist": alb.artist_name, "year": alb.year, "genre": alb.genre}
        album_level = {k: v for k, v in album_level.items() if v != current[k]}
        rows = list(s.scalars(select(Track).where(Track.album_id == id_).order_by(Track.disc_no, Track.track_no)))
        if not rows:
            raise ManageError("The album has no songs")
        root = s.get(Root, rows[0].root_id)
        if any(not _writable(t.path) for t in rows if _taggable(t)):
            raise ManageError("The album's folder is read-only for Muzix")
        _check_unchanged(rows)
        written = kept = 0
        before, todo = [], []
        for t in rows:
            want = {**album_level, **per_track.get(t.id, {})}
            changes = {k: v for k, v in want.items() if getattr(t, k) != v}
            before.append(_before(s, t, changes))       # every file's tags first: then the writing
            todo.append((t, changes))
        refiled = None
        try:
            for t, changes in todo:
                _write(s, t, changes)
                if changes:
                    written += _taggable(t)
                    kept += not _taggable(t)
            s.flush()
            # filing: music folders only, an album in a <Genre>/<Artist>/<Album> folder of its own
            paths = sorted({t.path for t in rows})
            folder = album_dir(paths)
            moved_to = None
            new = {"title": album_level.get("album", alb.title), "artist": album_level.get("albumartist", alb.artist_name),
                   "year": album_level.get("year", alb.year)}
            can_file = root.kind == "music" and all(_taggable(t) for t in rows)
            depth = len(os.path.relpath(folder, root.path).split(os.sep))
            if can_file and depth == 3 and _owns_folder(folder, set(paths), root.path):
                plan_tracks = [{"path": t.path, "title": per_track.get(t.id, {}).get("title", t.title),
                                "artist": per_track.get(t.id, {}).get("artist", t.artist),
                                "track_no": per_track.get(t.id, {}).get("track_no", t.track_no),
                                "disc_no": per_track.get(t.id, {}).get("disc_no", t.disc_no),
                                "year": album_level.get("year", t.year)} for t in rows]
                top = _filed_under(root.path, folder, album_level.get("genre", alb.genre),
                                   "genre" in album_level)[0] if by_genre else None
                target, moves = _plan(root.path, folder, new, plan_tracks, top)
                if os.path.normpath(target) != os.path.normpath(folder) or any(a != b for a, b in moves.items()):
                    _refile(folder, target, moves)
                    refiled = (folder, target, moves)
                    moved_to = target
                    _set_paths(s, [(t, moves[t.path]) for t in rows])
                    if alb.art and alb.art.startswith(folder + "/"):
                        alb.art = target + alb.art[len(folder):]
            elif root.kind == "music" and can_file:
                notes.append("Kept in its folder: it isn't in a Genre/Artist/Album folder of its own")
            s.flush()
            files = _after(s, before, {t.id: t.path for t in rows})
            undo = {"album_id": id_, "album_title": [title_before, new["title"]], "files": files,
                    "folder": [folder, moved_to] if moved_to and os.path.normpath(moved_to) != os.path.normpath(folder) else None,
                    "art": [art_before, alb.art] if alb.art != art_before else None}
            _rekey(s, alb, rows[0], new["title"])
            _reread(s, root, [(t.id, t.subsong, t.path) for t in rows], scanner.Resolver())
            s.flush()
            album_ids = {id_} | set(s.scalars(select(Track.album_id).where(Track.id.in_([t.id for t in rows]))))
            _summarize(s, {a for a in album_ids if a})
            new_id = s.scalar(select(Track.album_id).where(Track.id == rows[0].id))
            labels = {"album": "title", "albumartist": "album artist", "year": "year", "genre": "genre"}
            songs = sum(1 for f in files if set(f.get("fields", [])) - set(album_level))
            shown = 3 if moved_to and moved_to.split(os.sep)[-3] != folder.split(os.sep)[-3] else 2   # with a new genre folder
            summary = "; ".join(x for x in (
                _and([labels[k] for k in album_level]).capitalize(),
                f"{songs} song{'s' if songs != 1 else ''}" if songs else "",
                "filed in " + " / ".join(moved_to.split(os.sep)[-shown:]) if moved_to else "") if x)
            title = new["title"] + (f" (was {title_before})" if new["title"] != title_before else "")
            edit_id = _remember(s, "album", new_id or id_, title, summary, undo) if remember and files else None
        except Exception as err:
            _put_files_back(before, refiled)
            if isinstance(err, ManageError):
                raise
            log.exception("editing album %s failed", id_)
            raise ManageError(f"Saving failed ({type(err).__name__}), so the files were put back as they were") from err
    _tidy_later()
    return {"written": written, "kept": kept, "moved_to": moved_to, "notes": notes, "album_id": new_id,
            "edit_id": edit_id, **({} if remember else {"undo": undo if files else None, "summary": summary})}


def edit_track(id_: int, fields: dict, remember: bool = True) -> dict:
    """One song's fields into its file. It's renamed to match when its album is filed; moving it
    to another album's folder is left to editing that album. `remember` as for edit_album."""
    changes_in = _clean_fields(fields)
    notes = []
    with db.session() as s:
        t = _row(s, "track", id_)
        root = s.get(Root, t.root_id)
        if _taggable(t) and not _writable(t.path):
            raise ManageError("The song's folder is read-only for Muzix")
        _check_unchanged([t])
        changes = {k: v for k, v in changes_in.items() if getattr(t, k) != v}
        before = [_before(s, t, changes)]
        title = changes.get("title", t.title)
        _write(s, t, changes)
        s.flush()
        renamed = None
        same_album = not ({"album", "albumartist"} & set(changes))
        siblings = list(s.scalars(select(Track).where(Track.album_id == t.album_id))) if t.album_id else [t]
        folder = album_dir(sorted({x.path for x in siblings}))
        if root.kind == "music" and _taggable(t) and same_album and folder and \
                len(os.path.relpath(folder, root.path).split(os.sep)) == 3:
            alb = s.get(Album, t.album_id) if t.album_id else None
            album = {"title": t.album, "artist": t.albumartist or t.artist, "year": alb.year if alb else t.year}
            want = {**{k: getattr(t, k) for k in TRACK_FIELDS}, **changes, "path": t.path}
            # numbering looks at the whole album (disc prefixes), but only this file moves
            others = [{"path": x.path, "title": x.title, "artist": x.artist, "track_no": x.track_no,
                       "disc_no": x.disc_no, "year": x.year} for x in siblings if x.id != t.id]
            _, moves = _plan(root.path, folder, album, others + [want])
            new_path = os.path.join(os.path.dirname(t.path), os.path.basename(moves[t.path]))
            if new_path != t.path:
                if os.path.lexists(new_path):
                    notes.append("Not renamed: a file of that name is already there")
                else:
                    os.rename(t.path, new_path)
                    s.execute(update(TagOverride).where(TagOverride.path == t.path).values(path=new_path))
                    t.path = renamed = new_path
        elif changes and not same_album:
            notes.append("Its file stays in the album's folder; edit the album to file it elsewhere")
        s.flush()
        files = _after(s, before, {t.id: t.path})
        old_album = t.album_id
        _reread(s, root, [(t.id, t.subsong, t.path)], scanner.Resolver())
        s.flush()
        new_album = s.scalar(select(Track.album_id).where(Track.id == id_))
        _summarize(s, {a for a in (old_album, new_album) if a})
        labels = {"title": "title", "artist": "artist", "albumartist": "album artist", "album": "album",
                  "track_no": "number", "disc_no": "disc", "year": "year", "genre": "genre"}
        summary = "; ".join(x for x in (_and([labels[k] for k in changes]).capitalize(), "renamed" if renamed else "") if x)
        undo = {"files": files}
        edit_id = _remember(s, "track", id_, title, summary, undo) if remember and files else None
    _tidy_later()
    return {"renamed_to": renamed, "notes": notes, "edit_id": edit_id,
            **({} if remember else {"undo": undo if files else None})}


@jobs.job("rename_artist")
def rename_artist_job(ctx: jobs.JobContext, artist_id: int, name: str, picture: str = ""):
    """An artist's new name into all their songs (as artist or album artist), their albums filed again.
    `picture` (a web address) is set at the end, on whoever has the name then: two artists can become one."""
    with db.session() as s:
        a = _row(s, "artist", artist_id)
        old = a.name
        # the artist keeps their row (picture, tags, hidden), unless the new name is someone already there
        renamed_row = s.scalar(select(func.count()).select_from(Artist).where(Artist.name == name)) == 0
        if renamed_row:
            a.name = name
        albums = list(s.scalars(select(Album.id).where(Album.artist_id == artist_id)))
        loose = list(s.scalars(select(Track).where(Track.artist_id == artist_id, ~Track.album_id.in_(albums))))
    ctx.log(f"{old} → {name}: {len(albums)} albums")
    parts = []      # what undoes each album and song, in the order they were done
    report = {"old": old, "name": name, "albums": 0, "songs": 0, "folders": [], "failed": [], "merged": False, "edit_id": None,
              "artist_id": artist_id, "picture": False}
    try:
        for i, aid in enumerate(albums):
            ctx.check()
            with db.session() as s:
                alb = s.get(Album, aid, execution_options={"include_hidden": True})
                label = alb.title if alb else f"album {aid}"
                rows = list(s.scalars(select(Track).where(Track.album_id == aid)))
                per = [{"id": t.id, **({"artist": name} if t.artist == old else {})} for t in rows]
            ctx.update(i / max(1, len(albums) + len(loose)), f"Album {i + 1} of {len(albums)}: {label}")
            try:
                r = edit_album(aid, {"artist": name}, per, remember=False, by_genre=False)   # they stay in their genre folders
                parts += [r["undo"]] if r["undo"] else []
                report["albums"] += 1
                report["songs"] += len(per)        # all theirs now, rewritten or already so
                if r["moved_to"]:
                    folder = " / ".join(os.path.dirname(r["moved_to"]).split(os.sep)[-2:])
                    report["folders"] += [] if folder in report["folders"] else [folder]
                ctx.log(f"  {label}: {r['written']} files" + (f", now in {r['moved_to']}" if r["moved_to"] else ""))
            except ManageError as e:
                report["failed"].append(f"{label}: {e}")
                ctx.log(f"  {label}: {e}")
        for t in loose:
            try:
                r = edit_track(t.id, {k: name for k in ("artist", "albumartist") if getattr(t, k) == old}, remember=False)
                parts += [r["undo"]] if r["undo"] else []
                report["songs"] += 1
            except ManageError as e:
                report["failed"].append(f"{os.path.basename(t.path)}: {e}")
                ctx.log(f"  {t.path}: {e}")
    finally:        # cancelled halfway: what was renamed can still be undone
        with db.session() as s:
            new = s.scalar(select(Artist).where(Artist.name == name))
            if new is not None and new.id != artist_id:
                report["merged"], report["artist_id"] = True, new.id
                ctx.log(f"merged into the existing artist {name}")
            if parts or renamed_row:
                n = len(parts)
                report["edit_id"] = _remember(s, "artist", artist_id, f"{name} (was {old})",
                                              f"Renamed; {n} album{'s' if n != 1 else ''} and songs",
                                              {"artist_id": artist_id, "name": old, "new": name, "row": renamed_row, "parts": parts})
    report["folders"] = report["folders"][:3]
    if picture:
        try:
            set_cover("artist", report["artist_id"], fetch_image(picture))
            report["picture"] = True
        except ManageError as e:
            report["failed"].append(f"the picture: {e}")
    ctx.update(1, f"{old} is now {name}: {report['songs']} songs" + (f", {len(report['failed'])} couldn't be changed" if report["failed"] else ""))
    return report


def namesake(id_: int, name: str) -> dict | None:
    """Another artist the library already has by this name (the scanner matches names regardless of
    case): renaming to it makes the two one."""
    with db.session() as s:
        other = s.scalar(select(Artist).where(func.lower(Artist.name) == name.strip().lower(), Artist.id != id_)
                         .execution_options(include_hidden=True))
        if other is None:
            return None
        albums = s.scalar(select(func.count()).select_from(Album).where(Album.artist_id == other.id))
        return {"id": other.id, "name": other.name, "albums": albums}


def edit_simple(kind: str, id_: int, fields: dict, picture: str = "") -> dict:
    """Books, podcasts, playlists, playlist files and stations: their own fields in the database
    (books and podcasts keep them over rescans and refreshes). An artist's new name is a job (all
    their files), which sets `picture` too once it's done; without one, the picture is set at once."""
    if kind == "artist":
        name = str(fields.get("name") or "").strip()
        if not name:
            raise ManageError("The artist needs a name")
        with db.session() as s:
            old = _row(s, kind, id_).name
        if name != old:
            return {"job_id": jobs.submit("rename_artist", f"Rename {old} to {name}", artist_id=id_, name=name, picture=picture)}
        if picture:
            set_cover("artist", id_, fetch_image(picture))
        return {"picture": bool(picture)}
    with db.session() as s:
        row = _row(s, kind, id_)
        allowed = {"book": ("title", "author", "narrator", "series", "year", "description"),
                   "podcast": ("title", "author", "description", "image"),
                   "playlist": ("name", "description"), "fileplaylist": ("name",),
                   "station": ("name", "favicon")}[kind]
        changes = {k: (int(v or 0) if k == "year" else str(v or "").strip()) for k, v in fields.items() if k in allowed}
        before = {k: getattr(row, k) for k in changes}
        path_before = getattr(row, "path", None)
        custom_before = dict(row.custom or {}) if kind in ("book", "podcast") else None
        if kind == "fileplaylist" and changes.get("name") and changes["name"] != row.name:
            if not _writable(row.path):
                raise ManageError("That playlist's folder is read-only for Muzix")
            new = os.path.join(os.path.dirname(row.path), clean(changes["name"]) + os.path.splitext(row.path)[1])
            _move(row.path, new)
            row.path = new
        for k, v in changes.items():
            setattr(row, k, v)
        if kind in ("book", "podcast"):
            row.custom = {**(row.custom or {}), **changes}
        changed = {k: v for k, v in changes.items() if before[k] != v}
        moved = path_before is not None and row.path != path_before
        if not changed and not moved:
            return {}
        undo = {"fields": {k: before[k] for k in changed}, "after": changed}
        if moved:
            undo["path"] = [path_before, row.path]
        if custom_before is not None:
            undo["custom"] = custom_before
        title = str(getattr(row, "title", None) or getattr(row, "name", ""))
        return {"edit_id": _remember(s, kind, id_, title, _and(sorted(changed)).capitalize(), undo)}


# ---------------------------------------------------------------- undoing an edit

def edit_list(limit: int = 100) -> list[dict]:
    with db.session() as s:
        return [{"id": e.id, "kind": e.kind, "item_id": e.item_id, "title": e.title, "summary": e.summary,
                 "created_at": _utc(e.created_at), "undone_at": _utc(e.undone_at)}
                for e in s.scalars(select(EditRecord).order_by(EditRecord.id.desc()).limit(limit))]


def last_edit(s, kind: str, id_: int) -> dict | None:
    """The item's latest edit still to undo. Only edits made since it came into the library: a
    database can give a deleted item's id to a new one."""
    row = s.get(MODELS[kind], id_)
    since = getattr(row, "added_at", None) or getattr(row, "created_at", None)
    q = select(EditRecord).where(EditRecord.kind == kind, EditRecord.item_id == id_, EditRecord.undone_at.is_(None))
    if since is not None:
        q = q.where(EditRecord.created_at >= since)
    e = s.scalar(q.order_by(EditRecord.id.desc()).limit(1))
    return {"id": e.id, "summary": e.summary, "created_at": _utc(e.created_at)} if e else None


def _here(e: dict) -> str | None:
    """Where a file of an edit is: where the edit put it, or back where it was (undone halfway)."""
    return e["path"] if os.path.lexists(e["path"]) else e["was"] if os.path.lexists(e["was"]) else None


def _check_files(s, u: dict):
    """Refuses (before anything is touched) when the files aren't as the edit left them."""
    later = "has been changed since; undo the later edit first"
    paths = {e["path"] for e in u["files"]}
    for e in u["files"]:
        name = os.path.basename(e["path"])
        here, t = _here(e), s.get(Track, e["id"])
        if t is not None and here is None and os.path.lexists(t.path):
            raise ManageError(f"{name} {later}")            # renamed or moved by another edit
        if here is None or t is None:
            raise ManageError(f"{name} isn't in the library any more")
        if "tags" in e:
            try:
                now = tagwrite.snapshot(here, e["fields"])
            except (tagwrite.TagError, OSError) as err:
                raise ManageError(f"Couldn't read the tags of {name}: {err}")
            if now not in (e["tags_after"], e["tags"]):
                raise ManageError(f"{name} {later}")
        elif e["fields"]:
            o = s.get(TagOverride, (here, e["subsong"]))
            if (dict(o.fields) if o else None) not in (e.get("override_after"), e["override"]):
                raise ManageError(f"{name} {later}")
        if here == e["path"] and e["was"] != e["path"] and os.path.lexists(e["was"]) and e["was"] not in paths \
                and not (u.get("folder") and os.path.isdir(u["folder"][1])):
            raise ManageError(f"Something new is already at {e['was']}; nothing was changed")
    if u.get("folder"):
        was, now = u["folder"]
        if os.path.isdir(now) and os.path.lexists(was):
            raise ManageError(f"Something new is already at {was}; nothing was changed")


def _undo_files(s, u: dict):
    """Tags (or overrides) back as they were, then the files back where they were."""
    for e in u["files"]:
        here = _here(e)
        if "tags" in e:
            try:
                tagwrite.put_back(here, e["tags"])
            except (tagwrite.TagError, OSError) as err:
                raise ManageError(f"Couldn't put back the tags of {os.path.basename(here)}: {err}")
        elif e["fields"]:
            o = s.get(TagOverride, (here, e["subsong"]))
            if e["override"] is None:
                if o is not None:
                    s.delete(o)
            elif o is None:
                s.add(TagOverride(path=here, subsong=e["subsong"], fields=e["override"]))
            else:
                o.fields = e["override"]
    moves = {e["path"]: e["was"] for e in u["files"] if e["path"] != e["was"]}
    if u.get("folder") and os.path.isdir(u["folder"][1]):
        _refile(u["folder"][1], u["folder"][0], moves)
    else:
        moves = {a: b for a, b in moves.items() if os.path.lexists(a)}
        if moves:
            folder = os.path.commonpath([os.path.dirname(p) for p in moves])
            _refile(folder, folder, moves)
    rows = [s.get(Track, e["id"]) for e in u["files"]]
    _set_paths(s, [(t, e["was"]) for e, t in zip(u["files"], rows)])
    alb = s.get(Album, u["album_id"]) if u.get("album_id") else None
    if alb is not None and u.get("art") and alb.art == u["art"][1]:
        alb.art = u["art"][0]
    if alb is not None and u.get("folder") and alb.art and alb.art.startswith(u["folder"][1] + "/"):
        alb.art = u["folder"][0] + alb.art[len(u["folder"][1]):]       # a cover set since, in the folder
    s.flush()
    root = s.get(Root, rows[0].root_id)
    if alb is not None:
        _rekey(s, alb, rows[0], u["album_title"][0])
    old_albums = {t.album_id for t in rows}
    _reread(s, root, [(t.id, t.subsong, t.path) for t in rows], scanner.Resolver())
    s.flush()
    new_albums = set(s.scalars(select(Track.album_id).where(Track.id.in_([t.id for t in rows]))))
    _summarize(s, {a for a in old_albums | new_albums if a})


def _undo_cover(s, u: dict):
    """The cover picked with an album's edit: the old one back, or (it had none) the new one into the trash."""
    c = u["cover"]
    alb = s.get(Album, u["album_id"])
    if c["trash"]:
        item = s.get(TrashItem, c["trash"])
        if item is not None:
            _restore(s, item)
    elif os.path.isfile(c["path"]):
        root = _root_for(s, c["path"])
        if root is not None:
            s.add(_to_trash(root, "cover", alb.title if alb else "", "Cover picked with an edit that was undone", [c["path"]]))
            if alb is not None:
                alb.art = c["art"]
    if c.get("pictures"):
        _put_pictures(c["pictures"])        # exactly what the files had, none if none
    s.flush()


def _undo_fields(s, kind: str, id_: int, u: dict):
    row = _row(s, kind, id_)
    if any(getattr(row, k) != v for k, v in u["after"].items()):
        raise ManageError("It has been changed since; undo the later edit first")
    if u.get("path"):
        was, now = u["path"]
        if row.path == now:
            _move(now, was)
            row.path = was
    for k, v in u["fields"].items():
        setattr(row, k, v)
    if "custom" in u:
        row.custom = u["custom"]


def undo_edit(edit_id: int) -> dict:
    """Puts back what an edit changed. An artist's rename is undone album by album, each kept as
    it's done, so stopping halfway (a file that can't be written) can be carried on with later."""
    with db.session() as s:
        rec = s.get(EditRecord, edit_id)
        if rec is None:
            raise ManageError("That edit isn't in the list any more")
        if rec.undone_at:
            raise ManageError("That edit has already been undone")
        kind, item_id, u = rec.kind, rec.item_id, dict(rec.undo)
        if kind != "artist":
            if "files" in u:
                _check_files(s, u)
                if u.get("cover"):      # in the folder the edit made, before that moves back
                    _undo_cover(s, u)
                _undo_files(s, u)
            else:
                _undo_fields(s, kind, item_id, u)
            rec.undone_at = datetime.now(timezone.utc)
    if kind == "artist":
        parts = u["parts"]
        with db.session() as s:
            for part in parts:
                if not part.get("undone"):
                    _check_files(s, part)
            a = s.get(Artist, u["artist_id"])
            if u["row"] and a is not None and a.name == u["new"] and \
                    s.scalar(select(func.count()).select_from(Artist).where(Artist.name == u["name"])) == 0:
                a.name = u["name"]
        for i in reversed(range(len(parts))):
            if parts[i].get("undone"):
                continue
            with db.session() as s:
                _undo_files(s, parts[i])
                parts[i] = {**parts[i], "undone": True}
                rec = s.get(EditRecord, edit_id)
                rec.undo = {**u, "parts": list(parts)}
        with db.session() as s:
            s.get(EditRecord, edit_id).undone_at = datetime.now(timezone.utc)
    if u.get("cover") or u.get("art"):
        art.changed("album", u.get("album_id"))
    _tidy_later()
    return {"undone": edit_id, "kind": kind, "item_id": item_id}


# ---------------------------------------------------------------- covers

def fetch_image(url: str) -> bytes:
    if not re.match(r"^https?://", url or ""):
        raise ManageError("That isn't a web address")
    try:
        with httpx.Client(headers={"User-Agent": enrich.UA}, timeout=30, follow_redirects=True) as c, \
                c.stream("GET", url) as r:
            r.raise_for_status()
            data = b""
            for chunk in r.iter_bytes():
                data += chunk
                if len(data) > MAX_IMAGE:
                    raise ManageError("That picture is too big")
    except httpx.HTTPError as e:
        raise ManageError(f"Couldn't get the picture ({e})")
    return data


def _jpeg(data: bytes, size: int) -> bytes:
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    except Exception:
        raise ManageError("That isn't a picture Muzix can read")
    img = img.convert("RGB")
    img.thumbnail((size, size), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90)
    return out.getvalue()


def _own_art(folder: str, id_: int) -> str:
    os.makedirs(env.DATA_DIR / folder, exist_ok=True)
    return str(env.DATA_DIR / folder / f"{id_}.jpg")


def set_cover(kind: str, id_: int, data: bytes, edit_id: int | None = None) -> dict:
    """A new cover: an album's goes into its folder as cover.jpg and into its files (the old cover
    file into the trash); an artist's, book's or a shared folder's into Muzix's own data. With
    `edit_id` (an album picked from a source, saved with its edit) undoing the edit undoes it too."""
    kind, id_, out = _put_cover(kind, id_, data, edit_id)
    art.changed(kind, id_)
    return out


def _put_cover(kind: str, id_: int, data: bytes, edit_id: int | None) -> tuple[str, int, dict]:
    big, small = _jpeg(data, 1200), _jpeg(data, 600)
    notes = []
    with db.session() as s:
        row = _row(s, kind, id_)
        if kind == "track":
            if not row.album_id:
                raise ManageError("The song isn't in an album")
            kind, id_, row = "album", row.album_id, s.get(Album, row.album_id)
        if kind == "album":
            tracks = list(s.scalars(select(Track).where(Track.album_id == id_)))
            paths = sorted({t.path for t in tracks})
            folder = album_dir(paths)
            root = s.get(Root, tracks[0].root_id) if tracks else None
            if root and folder and _writable(folder) and _owns_folder(folder, set(paths), root.path):
                path = os.path.join(folder, "cover.jpg")
                old = scanner.find_cover(folder)
                trashed = None
                had = _pictures_of(tracks)
                if old and os.path.isfile(old):
                    trashed = _to_trash(root, "cover", row.title, f"Cover of {row.title}", [old])
                    s.add(trashed)
                    s.flush()
                    _save_pictures(had, os.path.join(trashed.folder, EMBEDDED))
                rec = s.get(EditRecord, edit_id) if edit_id else None
                if rec is not None and rec.kind == "album" and rec.item_id == id_ and not rec.undone_at:
                    pictures = str(env.DATA_DIR / "edit-pictures" / f"{edit_id}.json")
                    _save_pictures(had, pictures)
                    rec.undo = {**rec.undo, "cover": {"trash": trashed.id if trashed else None, "path": path,
                                                      "art": row.art, "pictures": pictures}}
                with open(path + ".part", "wb") as f:
                    f.write(big)
                os.replace(path + ".part", path)
                embedded = 0
                for t in tracks:
                    if _taggable(t):
                        try:
                            tagwrite.embed_cover(t.path, small)
                            embedded += 1
                        except (tagwrite.TagError, OSError) as e:
                            notes.append(f"{os.path.basename(t.path)}: {e}")
                row.art = path
                return kind, id_, {"art": path, "embedded": embedded, "notes": notes}
            path = _own_art("album-art", id_)       # a folder shared with other albums, or read-only
        elif kind == "artist":
            path = _own_art("artist-art", id_)
        elif kind == "book":
            path = _own_art("book-art", id_)
        else:
            raise ManageError("Pictures for this kind of item come from a web address")
        with open(path, "wb") as f:
            f.write(big)
        if kind == "album":
            row.art = path
        elif kind == "artist":
            row.image = path
        else:
            row.art = path
            row.custom = {**(row.custom or {}), "art": path}
        return kind, id_, {"art": path, "notes": notes}

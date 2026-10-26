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
"""

import io
import logging
import os
import re
import shutil
import threading
import time
from datetime import timezone

import httpx
from PIL import Image, ImageOps
from sqlalchemy import delete, func, or_, select, update

from . import db, enrich, env, formats, jobs, scanner
from .meta import tagwrite
from .models import (Album, Artist, Book, Episode, Feed, FilePlaylist, Like, Playlist, Root, Station, TagOverride,
                     Track, TrashItem)

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
                            "art": f"/api/art/album/{a.id}" if a.art else None})
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
        clash = [src for src, _ in item.moves if os.path.lexists(src)]
        if clash:
            raise ManageError(f"Something new is already at {clash[0]}; nothing was put back")
        for src, dst in item.moves:
            _move(dst, src)
        _remove_empty(item.folder)
        root_id = item.root_id
        s.delete(item)
    job = jobs.submit("scan", "Scan after putting back from the trash", root_id=root_id) if root_id else None
    return {"job_id": job}


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
        row = _row(s, kind, id_)
        if kind == "album":
            tracks = list(s.scalars(select(Track).where(Track.album_id == id_).order_by(Track.disc_no, Track.track_no, Track.path)))
            root = s.get(Root, tracks[0].root_id) if tracks else None
            folder = album_dir(sorted({t.path for t in tracks}))
            return {"kind": kind, "id": id_, "title": row.title, "artist": row.artist_name, "year": row.year,
                    "genre": row.genre, "folder": folder, "hidden": row.hidden,
                    "art": f"/api/art/album/{id_}" if row.art else None,
                    "files": "music" if root and root.kind == "music" else root.kind if root else "",
                    "writable": bool(tracks) and _writable(tracks[0].path),
                    "tags": "files" if tracks and all(_taggable(t) for t in tracks) else "muzix",
                    "tracks": [{"id": t.id, "title": t.title, "artist": t.artist, "track_no": t.track_no,
                                "disc_no": t.disc_no, "duration": t.duration, "format": t.format} for t in tracks]}
        if kind == "track":
            return {"kind": kind, "id": id_, "title": row.title, "artist": row.artist, "albumartist": row.albumartist,
                    "album": row.album, "album_id": row.album_id, "track_no": row.track_no, "disc_no": row.disc_no,
                    "year": row.year, "genre": row.genre, "path": row.path, "format": row.format, "hidden": row.hidden,
                    "art": f"/api/art/album/{row.album_id}" if row.album_id else None,
                    "writable": _writable(row.path), "tags": "files" if _taggable(row) else "muzix"}
        if kind == "artist":
            n = s.scalar(select(func.count()).select_from(Track).where(Track.artist_id == id_))
            return {"kind": kind, "id": id_, "name": row.name, "songs": n, "hidden": row.hidden,
                    "art": f"/api/art/artist/{id_}"}
        if kind == "book":
            return {"kind": kind, "id": id_, "title": row.title, "author": row.author, "narrator": row.narrator,
                    "series": row.series, "year": row.year, "description": row.description, "hidden": row.hidden,
                    "art": f"/api/art/book/{id_}" if row.art else None}
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


def _plan(root: str, folder: str, album: dict, tracks: list[dict]) -> tuple[str, dict[str, str]]:
    """(the album's new folder, {old path: new path}) under root/<Genre>/<Album artist>/<Artist - Year - Album>."""
    parts = os.path.relpath(folder, root).split(os.sep)
    top = parts[0]
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
        alb.title = common("album") or alb.title
        alb.formats = ",".join(sorted({t.format for t in tracks}))
        alb.folder = os.path.dirname(tracks[0].path)


def edit_album(id_: int, fields: dict, tracks: list[dict]) -> dict:
    """The album's fields (title, artist, year, genre) and its songs' (title, artist, track_no,
    disc_no): into the files, then the album filed by its new tags."""
    album_level = {"album": fields.get("title"), "albumartist": fields.get("artist"),
                   "year": fields.get("year"), "genre": fields.get("genre")}
    album_level = _clean_fields({k: v for k, v in album_level.items() if v is not None})
    per_track = {int(t["id"]): _clean_fields(t) for t in tracks if "id" in t}
    notes = []
    with db.session() as s:
        alb = _row(s, "album", id_)
        # only what changed: the window sends every field
        current = {"album": alb.title, "albumartist": alb.artist_name, "year": alb.year, "genre": alb.genre}
        album_level = {k: v for k, v in album_level.items() if v != current[k]}
        rows = list(s.scalars(select(Track).where(Track.album_id == id_).order_by(Track.disc_no, Track.track_no)))
        if not rows:
            raise ManageError("The album has no songs")
        root = s.get(Root, rows[0].root_id)
        if any(not _writable(t.path) for t in rows if _taggable(t)):
            raise ManageError("The album's folder is read-only for Muzix")
        written = kept = 0
        for t in rows:
            want = {**album_level, **per_track.get(t.id, {})}
            changes = {k: v for k, v in want.items() if getattr(t, k) != v}
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
            target, moves = _plan(root.path, folder, new, plan_tracks)
            if os.path.normpath(target) != os.path.normpath(folder) or any(a != b for a, b in moves.items()):
                _refile(folder, target, moves)
                moved_to = target
                for t in rows:
                    t.path = moves[t.path]
                if alb.art and alb.art.startswith(folder + "/"):
                    alb.art = target + alb.art[len(folder):]
        elif root.kind == "music" and can_file:
            notes.append("Kept in its folder: it isn't in a Genre/Artist/Album folder of its own")
        s.flush()
        _rekey(s, alb, rows[0], new["title"])
        _reread(s, root, [(t.id, t.subsong, t.path) for t in rows], scanner.Resolver())
        s.flush()
        album_ids = {id_} | set(s.scalars(select(Track.album_id).where(Track.id.in_([t.id for t in rows]))))
        _summarize(s, {a for a in album_ids if a})
        new_id = s.scalar(select(Track.album_id).where(Track.id == rows[0].id))
    _tidy_later()
    return {"written": written, "kept": kept, "moved_to": moved_to, "notes": notes, "album_id": new_id}


def edit_track(id_: int, fields: dict) -> dict:
    """One song's fields into its file. It's renamed to match when its album is filed; moving it
    to another album's folder is left to editing that album."""
    changes_in = _clean_fields(fields)
    notes = []
    with db.session() as s:
        t = _row(s, "track", id_)
        root = s.get(Root, t.root_id)
        if _taggable(t) and not _writable(t.path):
            raise ManageError("The song's folder is read-only for Muzix")
        changes = {k: v for k, v in changes_in.items() if getattr(t, k) != v}
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
        old_album = t.album_id
        _reread(s, root, [(t.id, t.subsong, t.path)], scanner.Resolver())
        s.flush()
        new_album = s.scalar(select(Track.album_id).where(Track.id == id_))
        _summarize(s, {a for a in (old_album, new_album) if a})
    _tidy_later()
    return {"renamed_to": renamed, "notes": notes}


@jobs.job("rename_artist")
def rename_artist_job(ctx: jobs.JobContext, artist_id: int, name: str):
    """An artist's new name into all their songs (as artist or album artist), their albums filed again."""
    with db.session() as s:
        a = _row(s, "artist", artist_id)
        old = a.name
        # the artist keeps their row (picture, tags, hidden), unless the new name is someone already there
        if s.scalar(select(func.count()).select_from(Artist).where(Artist.name == name)) == 0:
            a.name = name
        albums = list(s.scalars(select(Album.id).where(Album.artist_id == artist_id)))
        loose = list(s.scalars(select(Track).where(Track.artist_id == artist_id, ~Track.album_id.in_(albums))))
    ctx.log(f"{old} → {name}: {len(albums)} albums")
    for i, aid in enumerate(albums):
        ctx.check()
        with db.session() as s:
            rows = list(s.scalars(select(Track).where(Track.album_id == aid)))
            per = [{"id": t.id, **({"artist": name} if t.artist == old else {})} for t in rows]
        try:
            r = edit_album(aid, {"artist": name}, per)
            ctx.log(f"  album {aid}: {r['written']} files" + (f", now in {r['moved_to']}" if r["moved_to"] else ""))
        except ManageError as e:
            ctx.log(f"  album {aid}: {e}")
        ctx.update((i + 1) / max(1, len(albums) + len(loose)))
    for t in loose:
        try:
            edit_track(t.id, {k: name for k in ("artist", "albumartist") if getattr(t, k) == old})
        except ManageError as e:
            ctx.log(f"  {t.path}: {e}")
    with db.session() as s:
        new = s.scalar(select(Artist).where(Artist.name == name))
        if new is not None and new.id != artist_id:
            ctx.log(f"merged into the existing artist {name}")


def edit_simple(kind: str, id_: int, fields: dict) -> dict:
    """Books, podcasts, playlists, playlist files and stations: their own fields in the database
    (books and podcasts keep them over rescans and refreshes)."""
    with db.session() as s:
        row = _row(s, kind, id_)
        allowed = {"book": ("title", "author", "narrator", "series", "year", "description"),
                   "podcast": ("title", "author", "description", "image"),
                   "playlist": ("name", "description"), "fileplaylist": ("name",),
                   "station": ("name", "favicon"), "artist": ("name",)}[kind]
        changes = {k: (int(v or 0) if k == "year" else str(v or "").strip()) for k, v in fields.items() if k in allowed}
        if kind == "artist":
            name = changes.get("name", "")
            if not name:
                raise ManageError("The artist needs a name")
            if name == row.name:
                return {}
            return {"job_id": jobs.submit("rename_artist", f"Rename {row.name} to {name}", artist_id=id_, name=name)}
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
    return {}


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


def set_cover(kind: str, id_: int, data: bytes) -> dict:
    """A new cover: an album's goes into its folder as cover.jpg and into its files (the old cover
    file into the trash); an artist's, book's or a shared folder's into Muzix's own data."""
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
                if old and os.path.isfile(old):
                    s.add(_to_trash(root, "cover", row.title, f"Cover of {row.title}", [old]))
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
                return {"art": path, "embedded": embedded, "notes": notes}
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
        return {"art": path, "notes": notes}

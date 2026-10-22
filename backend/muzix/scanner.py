"""Library scanner for music and VGM roots.

Unchanged files (same size and mtime) are not re-read, so rescans are quick.
Chip files with several tunes become one track per subsong; each such file
is its own album (the game). Everything else is grouped by album tag within
its folder.
"""

import itertools
import logging
import os
import re
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import delete, func, select, text, update

from . import db, formats, jobs, settings
from .meta import chip, tags
from .models import Album, Artist, Root, Track

log = logging.getLogger("muzix.scan")
COVER_NAMES = ("cover", "folder", "front", "album", "albumart", "art", "artwork")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
BATCH = 200
# reading tags over NFS/SMB is latency-bound, so many readers help
THREADS = int(os.environ.get("MUZIX_SCAN_THREADS", "24"))


def norm(s: str) -> str:
    return " ".join((s or "").casefold().split())


# ---------------------------------------------------------------- walking

def walk(root: Root):
    excludes = [os.path.join(root.path, e.strip("/")) for e in (root.excludes or [])]
    stack = [root.path]
    while stack:
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError as e:
            log.warning("cannot read %s: %s", d, e)
            continue
        for e in entries:
            if e.name.startswith("."):
                continue
            if e.is_dir(follow_symlinks=True):
                if not any(e.path == x or e.path.startswith(x + "/") for x in excludes):
                    stack.append(e.path)
            elif formats.is_audio(e.path):
                try:
                    st = e.stat()
                except OSError:
                    continue
                yield e.path, st.st_size, st.st_mtime


# ---------------------------------------------------------------- reading one file

def read_file(path: str, root_kind: str) -> list[dict]:
    """Track rows (as dicts) for one file."""
    ext = formats.ext_of(path)
    fam = formats.family(ext)
    folder = os.path.basename(os.path.dirname(path))
    stem = os.path.splitext(os.path.basename(path))[0]
    if fam in ("native", "decode"):
        try:
            t = tags.read(path)
        except Exception as e:
            log.info("unreadable %s: %s", path, e)
            return []
        kind = "vgm" if root_kind == "vgm" else "music"
        return [dict(
            subsong=-1, kind=kind, format=ext, codec=t.codec, title=t.title or stem,
            artist=t.artist, albumartist=t.albumartist, album=t.album,
            track_no=t.track_no, disc_no=t.disc_no, year=t.year, genre=t.genre,
            duration=t.duration, bitrate=t.bitrate, sample_rate=t.sample_rate,
            bit_depth=t.bit_depth, channels=t.channels, embedded_art=t.embedded_art,
            mbid=t.mbid, extra={k: v for k, v in dict(
                album_mbid=t.album_mbid, artist_mbid=t.artist_mbid,
                albumartist_mbid=t.albumartist_mbid, compilation=t.compilation,
                chapters=t.chapters, **t.extra).items() if v},
        )]
    try:
        info = chip.read(path, ext)
    except Exception as e:
        log.info("unreadable %s: %s", path, e)
        info = chip.ChipInfo(system=formats.system_for(ext), subsongs=[chip.Subsong(0)])
    artist = info.artist or composer_from_path(path)
    multi = len(info.subsongs) > 1
    album = info.album or (info.title if multi else "") or folder
    rows = []
    for n, s in enumerate(info.subsongs, 1):
        title = s.title or (f"{info.title or stem} #{n}" if multi else info.title or stem)
        rows.append(dict(
            subsong=s.index if multi else -1,
            kind="vgm", format=ext, codec=fam, title=title, artist=artist, albumartist=artist,
            album=album, track_no=n if multi else 0, disc_no=0, year=info.year, genre="VGM",
            duration=s.duration or info.duration or 0, bitrate=0, sample_rate=44100,
            bit_depth=16, channels=2, embedded_art=False, mbid="",
            extra={k: v for k, v in dict(system=info.system, copyright=info.copyright,
                                         **info.extra, **s.timing()).items() if v},
        ))
    return rows


FOLDER_ALBUM = re.compile(r"^(?P<artist>.+?) - (?:(?P<year>(?:19|20)\d\d) - )?(?P<album>.+)$")


def album_from_folder(folder: str, artist: str) -> str:
    """"Artist - 1984 - Album" folders (this library's own naming) → "Album"."""
    name = os.path.basename(folder)
    m = FOLDER_ALBUM.match(name)
    if m and artist and norm(m.group("artist")) == norm(artist):
        return m.group("album")
    return name


def composer_from_path(path: str) -> str:
    """Module archives keep composers in folders: AUTHORS.A-F/4MAT/song.mod"""
    parts = path.split("/")
    if len(parts) >= 3 and norm(parts[-3]).startswith(("author", "artist", "composer", "group", "musician")):
        return parts[-2]
    return ""


# ---------------------------------------------------------------- album & art helpers

def find_cover(folder: str) -> str:
    try:
        names = os.listdir(folder)
    except OSError:
        return ""
    images = [n for n in names if n.lower().endswith(IMAGE_EXT)]
    for want in COVER_NAMES:
        for n in images:
            if os.path.splitext(n)[0].lower() == want:
                return os.path.join(folder, n)
    for want in COVER_NAMES:
        for n in images:
            if os.path.splitext(n)[0].lower().startswith(want):
                return os.path.join(folder, n)
    return os.path.join(folder, images[0]) if len(images) == 1 else ""


def album_key(row: dict, path: str) -> str:
    folder = os.path.dirname(path)
    if row["kind"] == "vgm" and row["subsong"] >= 0:
        return f"file\x1f{path}"
    if os.path.basename(folder).lower().startswith(("cd", "disc", "disk")) and len(os.path.basename(folder)) < 8:
        folder = os.path.dirname(folder)   # multi-disc albums share one album
    return f"{folder}\x1f{norm(row['album'])}"


# ---------------------------------------------------------------- the job

@jobs.job("scan")
def scan_job(ctx: jobs.JobContext, root_id: int | None = None, full: bool = False):
    with db.session() as s:
        q = select(Root).where(Root.enabled.is_(True), Root.kind.in_(("music", "vgm")))
        if root_id:
            q = q.where(Root.id == root_id)
        roots = [(r.id, r.path, r.kind, list(r.excludes or [])) for r in s.scalars(q)]
    totals = {"added": 0, "updated": 0, "removed": 0, "files": 0}
    for i, (rid, path, kind, excludes) in enumerate(roots):
        ctx.log(f"scanning {path} ({kind})")
        r = Root(id=rid, path=path, kind=kind, excludes=excludes)
        res = scan_root(ctx, r, full, base=i / max(1, len(roots)), span=1 / max(1, len(roots)))
        for k in totals:
            totals[k] += res[k]
    finish_scan(ctx)
    ctx.log(f"done: {totals}")
    if (totals["added"] or totals["updated"]) and settings.get("artist_tags") != "off":
        jobs.submit("artist_tags", "Fetch artist genres")
    if root_id is None:
        jobs.submit("scan_books", "Scan audiobooks")
    return totals


def scan_root(ctx, root: Root, full: bool, base=0.0, span=1.0) -> dict:
    gen = int(time.time())
    if not os.path.isdir(root.path):
        ctx.log(f"  {root.path} is not mounted / not a folder, skipped")
        return {"added": 0, "updated": 0, "removed": 0, "files": 0}
    with db.session() as s:
        known = {(p, sub): (tid, size, mtime) for tid, p, sub, size, mtime in s.execute(
            select(Track.id, Track.path, Track.subsong, Track.size, Track.mtime)
            .where(Track.root_id == root.id))}
    by_path: dict[str, list] = {}
    for (p, sub), v in known.items():
        by_path.setdefault(p, []).append((sub, *v))

    files = list(walk(root))
    ctx.log(f"  {len(files)} audio files")
    todo, unchanged = [], []
    for path, size, mtime in files:
        old = by_path.get(path)
        if old and not full and all(o[2] == size and abs(o[3] - mtime) < 1 for o in old):
            unchanged.extend(o[1] for o in old)
        else:
            todo.append((path, size, mtime))
    with db.session() as s:
        for chunk in range(0, len(unchanged), 900):
            s.execute(update(Track).where(Track.id.in_(unchanged[chunk:chunk + 900])).values(seen_scan=gen))
    ctx.log(f"  {len(todo)} new or changed")

    stats = {"added": 0, "updated": 0, "removed": 0, "files": len(files)}
    resolver = Resolver()
    folder_albums: dict[str, str] = {}

    def fill_album(s, row, path):
        """Tracks without an album tag join their folder's album."""
        folder = os.path.dirname(path)
        if folder not in folder_albums:
            # a range on the path index ("0" sorts right after "/"), unlike LIKE
            best = s.scalar(select(Track.album).where(Track.path > folder + "/", Track.path < folder + "0",
                                                      Track.album != "").group_by(Track.album)
                            .order_by(func.count().desc()).limit(1))
            if not best:
                return album_from_folder(folder, row["albumartist"] or row["artist"])
            folder_albums[folder] = best
        return folder_albums[folder]

    def read_all():
        """Read files in order, keeping the readers busy while batches are stored."""
        window = deque()
        with ThreadPoolExecutor(THREADS) as pool:
            try:
                for f in todo:
                    window.append((f, pool.submit(read_file, f[0], root.kind)))
                    if len(window) >= THREADS * 8:
                        f, fut = window.popleft()
                        yield f, fut.result()
                while window:
                    f, fut = window.popleft()
                    yield f, fut.result()
            finally:
                for _, fut in window:
                    fut.cancel()

    reader = read_all()
    try:
        for start in range(0, len(todo), BATCH):
            ctx.check()
            results = list(itertools.islice(reader, BATCH))
            # tagged files first, so untagged ones can join their folder's album
            results.sort(key=lambda r: not all(row["album"] for row in r[1]))
            with db.session() as s:
                for (path, size, mtime), rows in results:
                    old = {o[0]: o[1] for o in by_path.get(path, [])}
                    for row in rows:
                        row.update(path=path, size=size, mtime=mtime, root_id=root.id, seen_scan=gen)
                        if not row["album"]:
                            row["album"] = fill_album(s, row, path)
                        row["artist_id"] = resolver.artist(s, row["albumartist"] or row["artist"])
                        row["album_id"] = resolver.album(s, row, path)
                        tid = old.get(row["subsong"])
                        if tid:
                            s.execute(update(Track).where(Track.id == tid).values(**row))
                            stats["updated"] += 1
                        else:
                            s.add(Track(**row))
                            stats["added"] += 1
            done = min(start + BATCH, len(todo))
            ctx.update(base + span * done / max(1, len(todo)), f"{root.path}: {done}/{len(todo)} read")
    finally:
        reader.close()

    with db.session() as s:
        gone = s.execute(delete(Track).where(Track.root_id == root.id, Track.seen_scan != gen))
        stats["removed"] = gone.rowcount or 0
        s.execute(update(Root).where(Root.id == root.id).values(last_scan=func.now()))
    ctx.log(f"  +{stats['added']} ~{stats['updated']} -{stats['removed']}")
    return stats


class Resolver:
    """Find-or-create artists and albums, cached for the duration of a scan."""

    def __init__(self):
        self.artists: dict[str, int] = {}
        self.albums: dict[str, int] = {}

    def artist(self, s, name: str) -> int | None:
        name = (name or "").strip()
        if not name:
            return None
        key = norm(name)
        if key in self.artists:
            return self.artists[key]
        aid = s.scalar(select(Artist.id).where(func.lower(Artist.name) == name.lower()))
        if aid is None:
            a = Artist(name=name)
            s.add(a)
            s.flush()
            aid = a.id
        self.artists[key] = aid
        return aid

    def album(self, s, row: dict, path: str) -> int:
        key = album_key(row, path)
        if key in self.albums:
            return self.albums[key]
        alb = s.scalar(select(Album).where(Album.key == key))
        folder = os.path.dirname(path)
        if alb is None:
            alb = Album(key=key, kind=row["kind"], title=row["album"] or os.path.basename(folder),
                        folder=folder, artist_name=row["albumartist"] or row["artist"],
                        artist_id=row["artist_id"], year=row["year"], genre=row["genre"],
                        mbid=row.get("extra", {}).get("album_mbid", ""))
            s.add(alb)
            s.flush()
        self.albums[key] = alb.id
        return alb.id


def finish_scan(ctx):
    """Recompute album summaries, drop empty albums/artists, rebuild search."""
    ctx.log("updating albums and search index")
    with db.session() as s:
        s.execute(text("""
            UPDATE albums SET
              track_count = (SELECT count(*) FROM tracks t WHERE t.album_id = albums.id),
              duration = (SELECT coalesce(sum(duration), 0) FROM tracks t WHERE t.album_id = albums.id),
              year = coalesce((SELECT max(year) FROM tracks t WHERE t.album_id = albums.id), 0),
              formats = coalesce((SELECT group_concat(DISTINCT format) FROM tracks t WHERE t.album_id = albums.id), '')
        """))
        s.execute(text("DELETE FROM albums WHERE track_count = 0"))
        # album genre/artist: the most common value among its tracks
        s.execute(text("""
            UPDATE albums SET genre = coalesce((
              SELECT genre FROM tracks t WHERE t.album_id = albums.id AND genre != ''
              GROUP BY genre ORDER BY count(*) DESC LIMIT 1), genre)
        """))
        s.execute(text("""
            UPDATE albums SET artist_name = coalesce((
              SELECT coalesce(nullif(albumartist, ''), artist) FROM tracks t WHERE t.album_id = albums.id
              GROUP BY 1 ORDER BY count(*) DESC LIMIT 1), artist_name)
        """))
        s.execute(text("""
            DELETE FROM artists WHERE id NOT IN (SELECT artist_id FROM tracks WHERE artist_id IS NOT NULL)
              AND id NOT IN (SELECT artist_id FROM albums WHERE artist_id IS NOT NULL)
        """))
        s.execute(text("""
            UPDATE artists SET genre = coalesce((
              SELECT genre FROM albums a WHERE a.artist_id = artists.id AND a.genre != ''
              GROUP BY genre ORDER BY count(*) DESC LIMIT 1), '')
        """))
        # covers
        rows = s.execute(select(Album.id, Album.folder, Album.art)).all()
    updates = []
    for aid, folder, art in rows:
        if art and not art.startswith("embedded:") and os.path.exists(art):
            continue
        cover = find_cover(folder)
        if not cover:
            with db.session() as s:
                tid = s.scalar(select(Track.id).where(Track.album_id == aid, Track.embedded_art.is_(True)).limit(1))
            cover = f"embedded:{tid}" if tid else ""
        if cover != art:
            updates.append((aid, cover))
    with db.session() as s:
        for aid, cover in updates:
            s.execute(update(Album).where(Album.id == aid).values(art=cover))
    rebuild_search()


def rebuild_search():
    with db.session() as s:
        s.execute(text("DELETE FROM search_fts"))
        s.execute(text("""INSERT INTO search_fts(kind, ref, title, subtitle)
                          SELECT 'artist', id, name, genre FROM artists"""))
        s.execute(text("""INSERT INTO search_fts(kind, ref, title, subtitle)
                          SELECT 'album', id, title, artist_name || ' ' || coalesce(year, '') FROM albums"""))
        s.execute(text("""INSERT INTO search_fts(kind, ref, title, subtitle)
                          SELECT 'track', id, title, artist || ' ' || album FROM tracks"""))

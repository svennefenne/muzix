"""The shared folders' songs, read the way the server reads its library (muzix.scanner) and kept in
an index (index.db in the user's data folder), so a song keeps its id between runs: what someone
liked or put in a playlist on a server stays where it is.

The catalog is what a server mirrors (muzix.mirror): artists, albums and songs in its export
format, page by page. Only songs under the shared folders are in it, and only they are ever
read for a server (path_of)."""

import json
import logging
import os
import sqlite3
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from .shared import formats, scanner

log = logging.getLogger(__name__)

FIELDS = {
    "artists": ("id", "name", "sort_name", "mbid", "tags", "image"),
    "albums": ("id", "kind", "title", "artist", "artist_name", "year", "genre", "art", "mbid", "added_at"),
    "tracks": ("id", "album_id", "artist_ref", "kind", "subsong", "format", "codec", "title", "artist",
               "albumartist", "album", "track_no", "disc_no", "year", "genre", "duration", "bitrate",
               "sample_rate", "bit_depth", "channels", "size", "embedded_art", "mbid", "extra", "added_at"),
    "books": ("id", "title", "author", "narrator", "series", "year", "description", "art", "duration",
              "chapters", "added_at", "parts"),
    "playlists": ("id", "name", "entries", "tracks"),
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT NOT NULL, subsong INTEGER NOT NULL, size INTEGER, mtime REAL,
  kind TEXT, row TEXT, added_at TEXT, seen INTEGER, UNIQUE(path, subsong));
CREATE TABLE IF NOT EXISTS albums (id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS artists (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL COLLATE NOCASE);
"""


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0).isoformat()


def _inside(path: str, folder: str) -> bool:
    path, folder = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(folder))
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def walk(folder: str):
    """(path, size, mtime) of the songs under a folder (hidden folders and files left out)."""
    stack = [folder]
    while stack:
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError as e:
            log.warning("can't read %s: %s", d, e)
            continue
        for e in entries:
            if e.name.startswith("."):
                continue
            try:
                if e.is_dir(follow_symlinks=True):
                    stack.append(e.path)
                elif formats.is_audio(e.path):
                    st = e.stat()
                    yield e.path, st.st_size, st.st_mtime
            except OSError:
                continue


class Catalog:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.executescript(SCHEMA)
        self._db.commit()
        self.parts: dict[str, list[list]] = {p: [] for p in FIELDS}
        self.files: dict[int, str] = {}         # song id → its file
        self.covers: dict[int, tuple[str, str]] = {}    # album id → ("file" | "embedded", path)
        self.folders: list[tuple[str, str]] = []
        self._build()

    # ------------------------------------------------------------ reading the folders

    def scan(self, folders: list[tuple[str, str]], progress=None) -> bool:
        """Read what's new or changed under the shared folders ((path, kind)); whether the catalog changed."""
        with self._lock:
            self.folders = [(os.path.abspath(p), k) for p, k in folders]
            # this read's mark on every file it finds (two reads in one millisecond still differ)
            last = self._db.execute("SELECT max(seen) FROM files").fetchone()[0] or 0
            gen = max(last + 1, int(datetime.now().timestamp() * 1000))
            known = {(p, sub): (fid, size, mtime) for fid, p, sub, size, mtime in
                     self._db.execute("SELECT id, path, subsong, size, mtime FROM files")}
            by_path: dict[str, list] = {}
            for (p, sub), v in known.items():
                by_path.setdefault(p, []).append(v)
            todo, unchanged = [], []
            for folder, kind in self.folders:
                if not os.path.isdir(folder):
                    continue
                for path, size, mtime in walk(folder):
                    old = by_path.get(path)
                    if old and all(o[1] == size and abs(o[2] - mtime) < 1 for o in old):
                        unchanged += [o[0] for o in old]
                    else:
                        todo.append((path, size, mtime, kind))
            changed = bool(todo)
            for i in range(0, len(unchanged), 900):
                chunk = unchanged[i:i + 900]
                self._db.execute(f"UPDATE files SET seen = ? WHERE id IN ({','.join('?' * len(chunk))})", [gen, *chunk])
            with ThreadPoolExecutor(8) as pool:
                rows_of = pool.map(lambda f: scanner.read_file(f[0], f[3]), todo)
                for n, ((path, size, mtime, kind), rows) in enumerate(zip(todo, rows_of), 1):
                    for row in rows:
                        self._db.execute(
                            "INSERT INTO files (path, subsong, size, mtime, kind, row, added_at, seen) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(path, subsong) DO UPDATE SET "
                            "size = excluded.size, mtime = excluded.mtime, kind = excluded.kind, row = excluded.row, "
                            "seen = excluded.seen",
                            (path, row["subsong"], size, mtime, kind, _dump(row), _now(), gen))
                    if progress and n % 50 == 0:
                        progress(n, len(todo))
            gone = self._db.execute("DELETE FROM files WHERE seen IS NOT ? ", (gen,)).rowcount
            self._db.commit()
            changed = changed or gone > 0
            if changed:
                self._build()
            return changed

    def moved(self, moves: dict[str, str]):
        """Files Fix Metadata renamed: the same songs (same ids) at their new paths."""
        with self._lock:
            for old, new in moves.items():
                self._db.execute("UPDATE OR IGNORE files SET path = ? WHERE path = ?", (new, old))
            self._db.commit()

    # ------------------------------------------------------------ the catalog

    def _id(self, table: str, column: str, value: str) -> int:
        row = self._db.execute(f"SELECT id FROM {table} WHERE {column} = ?", (value,)).fetchone()
        if row:
            return row[0]
        return self._db.execute(f"INSERT INTO {table} ({column}) VALUES (?)", (value,)).lastrowid

    def _build(self):
        """The catalog in the export format, from the index (songs grouped into albums as the server does)."""
        songs = []
        for fid, path, kind, raw, size, added in self._db.execute(
                "SELECT id, path, kind, row, size, added_at FROM files ORDER BY id"):
            if self.folders and not any(_inside(path, f) for f, _ in self.folders):
                continue
            songs.append((fid, path, kind, _load(raw), size, added))
        # songs without an album tag join their folder's album, as on the server
        by_folder: dict[str, Counter] = {}
        for _, path, _, row, _, _ in songs:
            if row["album"]:
                by_folder.setdefault(os.path.dirname(path), Counter())[row["album"]] += 1
        albums: dict[str, dict] = {}
        tracks, files = [], {}
        for fid, path, kind, row, size, added in songs:
            if not row["album"]:
                folder = os.path.dirname(path)
                common = by_folder.get(folder)
                row["album"] = common.most_common(1)[0][0] if common else \
                    scanner.album_from_folder(folder, row["albumartist"] or row["artist"])
            key = scanner.album_key(row, path)
            a = albums.setdefault(key, {"key": key, "kind": row["kind"], "folder": os.path.dirname(path), "songs": []})
            a["songs"].append((fid, path, row, added))
            files[fid] = path
            tracks.append((fid, key, path, row, size, added))
        album_ids = {key: self._id("albums", "key", key) for key in albums}

        def most(values):
            values = [v for v in values if v]
            return Counter(values).most_common(1)[0][0] if values else ""

        artists: dict[str, int] = {}

        def artist(name: str) -> str:
            if name and name.casefold() not in artists:
                artists[name.casefold()] = (self._id("artists", "name", name), name)
            return name

        album_rows, covers = [], {}
        for key, a in albums.items():
            rows = [s[2] for s in a["songs"]]
            name = artist(most(r["albumartist"] or r["artist"] for r in rows))
            cover, version = scanner.find_cover(a["folder"]), 0
            if cover:
                covers[album_ids[key]] = ("file", cover)
                version = int(os.path.getmtime(cover)) or 1
            else:
                pictured = next((s for s in a["songs"] if s[2].get("embedded_art")), None)
                if pictured:
                    covers[album_ids[key]] = ("embedded", pictured[1])
                    version = int(os.path.getmtime(pictured[1])) or 1
            album_rows.append([album_ids[key], a["kind"], most(r["album"] for r in rows) or os.path.basename(a["folder"]),
                               name, name, max((r["year"] or 0) for r in rows), most(r["genre"] for r in rows),
                               version, most((r.get("extra") or {}).get("album_mbid", "") for r in rows),
                               min(s[3] for s in a["songs"])])
        track_rows = []
        for fid, key, path, row, size, added in tracks:
            ref = artist(row["albumartist"] or row["artist"])
            track_rows.append([fid, album_ids[key], ref, row["kind"], row["subsong"], row["format"], row["codec"],
                               row["title"], row["artist"], row["albumartist"], row["album"], row["track_no"],
                               row["disc_no"], row["year"], row["genre"], row["duration"], row["bitrate"],
                               row["sample_rate"], row["bit_depth"], row["channels"], size, bool(row["embedded_art"]),
                               row["mbid"], row.get("extra") or {}, added])
        artist_rows = sorted([aid, name, "", "", [], 0] for aid, name in artists.values())
        self._db.commit()
        self.parts = {"artists": artist_rows, "albums": sorted(album_rows), "tracks": track_rows,
                      "books": [], "playlists": []}
        self.files, self.covers = files, covers

    def page(self, part: str, after: int = 0, limit: int = 1000) -> dict:
        """A page of the catalog, as a server asks for it (muzix.mirror.export's format)."""
        if part not in FIELDS:
            raise KeyError(part)
        limit = max(1, min(limit, 5000))
        with self._lock:
            rows = [r for r in self.parts[part] if r[0] > after][:limit]
        return {"fields": FIELDS[part], "rows": rows, "next": rows[-1][0] if len(rows) == limit else None}

    def counts(self) -> dict[str, int]:
        with self._lock:
            return {"albums": len(self.parts["albums"]), "tracks": len(self.parts["tracks"])}

    def path_of(self, track_id: int) -> str | None:
        """A song's file, if it's one this computer shares."""
        with self._lock:
            path = self.files.get(track_id)
            folders = list(self.folders)
        if path and any(_inside(path, f) for f, _ in folders) and os.path.isfile(path):
            return path
        return None

    def cover(self, album_id: int) -> bytes | None:
        with self._lock:
            found = self.covers.get(album_id)
        if not found:
            return None
        how, path = found
        try:
            if how == "file":
                with open(path, "rb") as f:
                    return f.read()
            import mediafile
            return mediafile.MediaFile(path).art
        except Exception as e:
            log.info("no cover from %s: %s", path, e)
            return None

    def close(self):
        with self._lock:
            self._db.close()


def _dump(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, default=str)


def _load(raw: str) -> dict:
    return json.loads(raw)

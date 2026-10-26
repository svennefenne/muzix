"""A search index of the online archives that publish a list of everything they hold: HVSC (its
song-length list names every file), Modland (allmods.zip) and ASMA (its Demozoo list, with years).

A list is fetched when someone first searches or shuffles an archive, and again once it's a week
old; the index is a SQLite full-text table in the online cache, apart from the library's
database, and is rebuilt in the background while searches carry on without it.
"""

import json
import logging
import os
import random
import re
import sqlite3
import threading
import time
import zipfile
from urllib.parse import unquote

from . import formats

log = logging.getLogger("muzix.online.index")
MAX_AGE = 7 * 86400
SCHEMA = 2                        # bumped when the table changes; an old index is dropped
LISTS = {
    "hvsc": "https://hvsc.brona.dk/HVSC/C64Music/DOCUMENTS/Songlengths.md5",
    "modland": "https://modland.com/allmods.zip",
    "asma": "https://asma.atari.org/asma/Docs/Demozoo-Database.json",
}

_lock = threading.Lock()
_building: set[str] = set()


def _db_path():
    from .online import cache_dir
    return cache_dir() / "index.db"


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_db_path()), exist_ok=True)
    con = sqlite3.connect(_db_path(), timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    if con.execute("PRAGMA user_version").fetchone()[0] != SCHEMA:
        con.execute("DROP TABLE IF EXISTS lists")
        con.execute("DROP TABLE IF EXISTS entries")
        con.execute(f"PRAGMA user_version = {SCHEMA}")
    con.execute("CREATE TABLE IF NOT EXISTS lists (source TEXT PRIMARY KEY, built REAL, entries INTEGER)")
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS entries USING fts5("
                "source UNINDEXED, path UNINDEXED, title, artist, year, folder, "
                "tokenize='unicode61 remove_diacritics 2')")
    return con


# ---------------------------------------------------------------- the lists

def _nice(name: str) -> str:
    return name.replace("_", " ").strip()


def _title(name: str) -> str:
    """"song.mod" → song; Amiga style "mdat.unicorn" → unicorn."""
    pre, _, rest = name.partition(".")
    if rest and formats.ext_of(name) == pre.lower() and pre.lower() in formats.PREFIXES:
        return rest
    return os.path.splitext(name)[0]


def hvsc_name(folder: str) -> str:
    """HVSC names musicians Last_First: Hubbard_Rob is Rob Hubbard."""
    parts = folder.split("_")
    return " ".join([*parts[1:], parts[0]]) if len(parts) == 2 else _nice(folder)


def hvsc_rows(text: str):
    """"; /MUSICIANS/H/Hubbard_Rob/Commando.sid" lines → rows. HVSC names musicians Last_First."""
    for line in text.splitlines():
        if not line.startswith("; /"):
            continue
        path = line[3:].strip()
        names = path.split("/")
        title = _nice(os.path.splitext(names[-1])[0])
        artist = hvsc_name(names[2]) if names[0] == "MUSICIANS" and len(names) >= 4 else ""
        yield path, title, artist, "", _nice(" ".join(names[:-1]).lower())


def modland_rows(text: str):
    """"size<TAB>Format/Composer/file" lines → rows, for the formats Muzix plays."""
    from .online import MODLAND_PLAYABLE, kind_of
    playable = set(MODLAND_PLAYABLE) - {"HVSC"}      # HVSC is an archive of its own here
    for line in text.splitlines():
        size, _, path = line.partition("\t")
        names = path.split("/")
        if len(names) < 2 or names[0] not in playable or not kind_of(names[-1]):
            continue
        artist = names[1] if len(names) >= 3 and names[1].strip("_- ").lower() != "unknown" else ""
        yield path, _title(names[-1]), artist, "", " ".join(names[:-1]).lower()


def asma_rows(text: str):
    """ASMA's Demozoo export → rows, with release years."""
    base = "https://asma.atari.org/asma/"
    for p in json.loads(text).get("productions", []):
        link = next((d["url"] for d in p.get("download_links") or [] if d.get("url", "").startswith(base)), "")
        if not link:
            continue
        path = unquote(link[len(base):])
        names = path.split("/")
        artist = ", ".join(a.get("name", "") for a in p.get("author_nicks") or [] if a.get("name"))
        year = (p.get("release_date") or "")[:4]
        yield path, p.get("title") or os.path.splitext(names[-1])[0], artist, \
            year if year.isdigit() else "", _nice(" ".join(names[:-1]).lower())


def _fetch_list(source: str) -> str:
    """The archive's list as text, downloaded again when it's a week old."""
    from .online import OnlineError, _get, cache_dir, fetch_aside, source as source_of
    if source == "hvsc":                       # the same list that gives SID tunes their lengths
        return open(fetch_aside(source_of("hvsc"), "DOCUMENTS/Songlengths.md5", MAX_AGE), encoding="latin-1").read()
    url = LISTS[source]
    out = cache_dir() / "_lists" / os.path.basename(url)
    if not (out.exists() and time.time() - out.stat().st_mtime < MAX_AGE):
        r = _get(url)
        r.raise_for_status()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.with_suffix(".part").write_bytes(r.content)
        os.replace(out.with_suffix(".part"), out)
    if url.endswith(".zip"):
        with zipfile.ZipFile(out) as z:
            name = next((n for n in z.namelist() if n.endswith(".txt")), None)
            if not name:
                raise OnlineError("Modland's list is empty")
            return z.read(name).decode("latin-1")
    return out.read_bytes().decode("utf-8", "replace")


PARSERS = {"hvsc": hvsc_rows, "modland": modland_rows, "asma": asma_rows}


def build(source: str):
    """Fetches the archive's list and replaces its part of the index."""
    started = time.time()
    rows = list(PARSERS[source](_fetch_list(source)))
    con = _connect()
    try:
        with con:
            con.execute("DELETE FROM entries WHERE source = ?", (source,))
            con.executemany("INSERT INTO entries (source, path, title, artist, year, folder) VALUES (?, ?, ?, ?, ?, ?)",
                            ((source, *row) for row in rows))
            con.execute("INSERT OR REPLACE INTO lists VALUES (?, ?, ?)", (source, time.time(), len(rows)))
    finally:
        con.close()
    log.info("indexed %s: %d entries in %.1fs", source, len(rows), time.time() - started)


def _built(source: str) -> float | None:
    con = _connect()
    try:
        row = con.execute("SELECT built FROM lists WHERE source = ?", (source,)).fetchone()
    finally:
        con.close()
    return row[0] if row else None


def _start(source: str) -> threading.Thread | None:
    with _lock:
        if source in _building:
            return None
        _building.add(source)

    def run():
        try:
            build(source)
        except Exception as e:
            log.warning("indexing %s failed: %s", source, e)
        finally:
            with _lock:
                _building.discard(source)
    t = threading.Thread(target=run, daemon=True, name=f"index-{source}")
    t.start()
    return t


def ready(source: str, wait: bool = False) -> bool:
    """Whether the archive's index can be used. A missing or week-old one is (re)built in the
    background, the old one serving meanwhile; `wait` waits for a first build."""
    built = _built(source)
    if built is None or time.time() - built > MAX_AGE:
        _start(source)
        if wait and built is None:
            for _ in range(240):
                with _lock:
                    if source not in _building:
                        break
                time.sleep(0.5)
            built = _built(source)
    return built is not None


def building() -> list[str]:
    with _lock:
        return sorted(_building)


# ---------------------------------------------------------------- searching and shuffling

def match_expr(words: list[str]) -> str:
    """An FTS5 query: every word, as the start of a word somewhere in the entry."""
    return " AND ".join('"' + w.replace('"', '""') + '"*' for w in words)


def search(source: str, words: list[str], limit: int = 60) -> tuple[list[dict], int]:
    """(entries, how many match in all)."""
    con = _connect()
    try:
        expr = match_expr(words)
        total = con.execute("SELECT count(*) FROM entries WHERE entries MATCH ? AND source = ?",
                            (expr, source)).fetchone()[0]
        rows = con.execute("SELECT path, title, artist, year FROM entries WHERE entries MATCH ? AND source = ? "
                           "ORDER BY rank LIMIT ?", (expr, source, limit)).fetchall()
    except sqlite3.OperationalError as e:
        log.info("search %s %r: %s", source, words, e)
        return [], 0
    finally:
        con.close()
    return [_entry(*r) for r in rows], total


def folders(source: str, words: list[str], limit: int = 12) -> list[dict]:
    """Folders whose own names hold every word (a musician, a composer)."""
    con = _connect()
    try:
        rows = con.execute("SELECT path FROM entries WHERE entries MATCH ? AND source = ? LIMIT 3000",
                           ("folder : (" + match_expr(words) + ")", source)).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()
    seen = {}
    for (path,) in rows:
        parent = path.rpartition("/")[0]
        name = parent.rpartition("/")[2]
        low = re.sub(r"[_\W]+", " ", name.lower())
        if parent and parent not in seen and all(any(t.startswith(w) for t in low.split()) for w in words):
            seen[parent] = {"name": hvsc_name(name) if source == "hvsc" and parent.startswith("MUSICIANS/") else _nice(name),
                            "path": parent}
    return list(seen.values())[:limit]


def sample(source: str, prefix: str, n: int) -> list[dict]:
    """`n` random entries, from under `prefix` when there's one."""
    con = _connect()
    try:
        if prefix:
            rows = con.execute("SELECT path, title, artist, year FROM entries WHERE source = ? "
                               "AND substr(path, 1, ?) = ? ORDER BY random() LIMIT ?",
                               (source, len(prefix) + 1, prefix + "/", n)).fetchall()
        else:
            last = con.execute("SELECT max(rowid), min(rowid) FROM entries WHERE source = ?", (source,)).fetchone()
            if not last or last[0] is None:
                return []
            hi, lo = last
            picks = sorted(set(random.randint(lo, hi) for _ in range(n * 3)))
            rows = con.execute(f"SELECT path, title, artist, year FROM entries WHERE source = ? AND rowid IN "
                               f"({','.join('?' * len(picks))})", (source, *picks)).fetchall()
            random.shuffle(rows)
            rows = rows[:n]
    finally:
        con.close()
    return [_entry(*r) for r in rows]


def _entry(path: str, title: str, artist: str, year: str) -> dict:
    return {"name": path.rpartition("/")[2], "path": path, "title": title, "artist": artist,
            "year": int(year) if year else 0}

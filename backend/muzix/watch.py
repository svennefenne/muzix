"""The watch folder (Admin → Upload): albums put in a folder, on this server or on a computer linked through
Muzix Desktop (tunnel.py, when that computer allows it), are filed into the library by themselves, as
uploads are (organize/importer.py): a main genre, cover art, Genre/Artist/Artist - Year - Album.

Each album is first looked up on MusicBrainz, and a release counts when its songs are as many and as long as
the album's (match()); when none does, on Bandcamp, whose track list and cover then go into the files; when
neither has it, it's filed as its own tags say and listed as unmatched for the admin to look at.

The folder is looked at every minute; an album (a folder in it, or a single file) is taken once it hasn't
changed for two minutes. Its music goes into the library: from the server's folder itself, and from a
computer's as a copy, after which the computer's files go to _Done. What's left (covers, .cue, .nfo, .log)
goes to _Done/<album>; an album the library seems to have already goes to _Duplicates/<album>, for the
admin to look at and file anyway if they like; one that couldn't be filed goes to _Failed/<album>. Nothing
is deleted. Folders whose names start with "_" or "." are the watch folder's own, and left alone.
"""

import logging
import os
import re
import secrets
import shutil
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import httpx
from sqlalchemy import select

from . import db, env, formats, jobs, providers, settings, tunnel
from .meta import tags, tagwrite
from .models import Job, Peer
from .organize import duplicates, importer

log = logging.getLogger(__name__)

POLL = 60               # seconds between looks at the folder
SETTLE = 120            # seconds an album must stay as it is before it's taken
HELD = ("_Done", "_Duplicates", "_Failed")
MUSIC = ("native", "decode")


# ---------------------------------------------------------------- where the folder is

class Place:
    """The watch folder: list what's in it, bring an album here, move one aside."""

    key = ""

    def entries(self) -> dict[str, list[tuple[str, int, float]]]:
        """Each album: (path in it, size, modified) of its files."""
        raise NotImplementedError

    def fetch(self, name: str, held: str, into: Path) -> Path:
        """The album's folder here, to file it from."""
        raise NotImplementedError

    def move(self, name: str, held: str, to: str):
        """The album (in the folder, or in `held`) into one of HELD."""
        raise NotImplementedError

    def held(self) -> dict[str, list[str]]:
        """The albums in _Duplicates and _Failed."""
        raise NotImplementedError


def _unique(folder: Path, name: str) -> Path:
    """`name` in `folder`, or "name (2)" and on when it's taken: a move never overwrites."""
    stem, ext = os.path.splitext(name)
    if not 1 < len(ext) <= 6 or " " in ext:
        stem, ext = name, ""
    dest, n = folder / name, 2
    while dest.exists():
        dest, n = folder / f"{stem} ({n}){ext}", n + 1
    return dest


class ServerPlace(Place):
    def __init__(self, path: str):
        self.root = Path(path)
        self.key = f"server:{path}"

    def entries(self):
        out = {}
        for e in os.scandir(self.root):
            if e.name.startswith(("_", ".")):
                continue
            if e.is_file():
                st = e.stat()
                out[e.name] = [(e.name, st.st_size, st.st_mtime)]
            elif e.is_dir():
                files = []
                for r, dirs, fs in os.walk(e.path):
                    dirs[:] = [d for d in dirs if not d.startswith(".")]
                    for f in fs:
                        p = os.path.join(r, f)
                        try:
                            st = os.stat(p)
                        except OSError:
                            continue
                        files.append((os.path.relpath(p, self.root), st.st_size, st.st_mtime))
                out[e.name] = files
        return out

    def _at(self, name: str, held: str) -> Path:
        path = (self.root / held / name) if held else (self.root / name)
        if self.root.resolve() not in path.resolve().parents:
            raise ValueError("not in the watch folder")
        return path

    def fetch(self, name, held, into):
        return self._at(name, held)         # filed from where it is: the same share as the library

    def move(self, name, held, to):
        src = self._at(name, held)
        if not src.exists():
            return
        (self.root / to).mkdir(exist_ok=True)
        shutil.move(str(src), str(_unique(self.root / to, name)))

    def held(self):
        return {h: sorted(e.name for e in os.scandir(self.root / h) if not e.name.startswith("."))
                if (self.root / h).is_dir() else [] for h in HELD[1:]}


class ComputerPlace(Place):
    """A folder on a computer, through its connection (tunnel.py); Muzix Desktop allows it only for the folder
    the admin picked, on a server it lets pick one (desktop/muzix_desktop/sharing.py)."""

    def __init__(self, peer_id: int, path: str):
        self.peer_id, self.path = peer_id, path
        self.key = f"computer:{peer_id}:{path}"

    def _ask(self, op: str, timeout: float = 60, **args):
        return tunnel.get(self.peer_id).ask(op, timeout=timeout, path=self.path, **args)

    def entries(self, held: str = ""):
        got = self._ask("watch_list", held=held)
        return {e["name"]: [(f[0], int(f[1]), float(f[2])) for f in e["files"]] for e in got}

    def fetch(self, name, held, into):
        files = self.entries(held).get(name)
        if files is None:
            raise RuntimeError("it isn't in the watch folder any more")
        into.mkdir(parents=True, exist_ok=True)
        for rel, _size, _ in files:
            dest = (into / rel).resolve()
            if into.resolve() not in dest.parents:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as out:
                for chunk in tunnel.get(self.peer_id).chunks("watch_file", timeout=120, path=self.path, held=held, rel=rel):
                    out.write(chunk)
        return into / name

    def move(self, name, held, to):
        self._ask("watch_move", name=name, held=held, to=to)

    def held(self):
        return {h: [e["name"] for e in self._ask("watch_list", held=h)] for h in HELD[1:]}


def place() -> Place | None:
    """The watch folder as the admin set it, or None (none set, or its computer isn't connected)."""
    path = settings.get("watch_folder")
    if not path:
        return None
    computer = settings.get("watch_computer")
    if computer:
        with db.session() as s:
            peer = s.scalar(select(Peer).where(Peer.server_id == computer, Peer.kind == "computer"))
        if peer is None or not tunnel.connected(peer.id):
            return None
        return ComputerPlace(peer.id, path)
    return ServerPlace(path) if os.path.isdir(path) else None


# ---------------------------------------------------------------- matching

def _album(files: list[Path]) -> list[dict]:
    """The album's songs in order, with what their tags say and how long they are."""
    out = []
    for p in files:
        try:
            t = tags.read(str(p))
        except Exception:       # a file mutagen can't read: by its name, of unknown length
            t = None
        out.append({"path": p, "disc": (t and t.disc_no) or 1, "no": (t and t.track_no) or 0,
                    "title": (t and t.title) or p.stem, "artist": (t and t.artist) or "", "albumartist": (t and t.albumartist) or "",
                    "album": (t and t.album) or "", "year": (t and t.year) or 0, "length": (t and t.duration) or 0})
    return sorted(out, key=lambda s: (s["disc"], s["no"], str(s["path"])))


def _named(songs: list[dict], folder: str) -> tuple[str, str]:
    """(artist, album) as the tags have them most, or as the folder is named ("Artist - Year - Album")."""
    artist = Counter(s["albumartist"] or s["artist"] for s in songs if s["albumartist"] or s["artist"]).most_common(1)
    album = Counter(s["album"] for s in songs if s["album"]).most_common(1)
    if artist and album:
        return artist[0][0], album[0][0]
    parts = [p.strip() for p in re.split(r"\s+-\s+", folder) if p.strip()]
    parts = [p for p in parts if not re.fullmatch(r"\(?\d{4}\)?", p)]
    if len(parts) >= 2:
        return (artist[0][0] if artist else parts[0]), (album[0][0] if album else parts[-1])
    return (artist[0][0] if artist else ""), (album[0][0] if album else folder)


def fits(songs: list[dict], tracks: list[dict]) -> bool:
    """Whether a release is this album: as many songs, nearly all of them as long (within three seconds, or a
    percent of a long one), none far off."""
    if not songs or len(songs) != len(tracks):
        return False
    known = [(s["length"], t.get("length") or 0) for s, t in zip(songs, tracks) if s["length"] and t.get("length")]
    if len(known) < 0.8 * len(songs):
        return False
    close = sum(abs(a - b) <= max(3.0, a * 0.01) for a, b in known)
    return close >= 0.9 * len(known) and all(abs(a - b) <= 15 for a, b in known)


def match(songs: list[dict], folder: str, ctx=None) -> tuple[str, str, dict | None]:
    """("musicbrainz", release id, its details), ("bandcamp", id, its details) or ("none", "", None)."""
    artist, album = _named(songs, folder)
    if not album:
        return "none", "", None
    for source, search in (("musicbrainz", providers._musicbrainz), ("bandcamp", providers._bandcamp)):
        try:
            found = search("album", artist, album, "")
        except (providers.SourceError, httpx.HTTPError, ValueError, KeyError) as e:
            ctx and ctx.log(f"{source}: {e}")
            continue
        # those as long as the album first (MusicBrainz says how many songs a release has)
        found.sort(key=lambda r: r.get("tracks") not in (None, 0, len(songs)))
        for r in found[:4]:
            try:
                d = providers.details(source, "album", r["id"])
            except (providers.SourceError, httpx.HTTPError, ValueError, KeyError):
                continue
            if fits(songs, d["tracks"]):
                ctx and ctx.log(f"{source}: {d['artist']} - {d['title']} has the same songs")
                return source, d.get("mbid") or r["id"], d
        ctx and ctx.log(f"{source}: nothing with these songs ({artist} - {album})")
    return "none", "", None


def _apply(songs: list[dict], d: dict, folder: Path):
    """A release's names into the album's files (Bandcamp's: MusicBrainz's beets writes itself), and its cover
    beside them for beets to take."""
    for s, t in zip(songs, d["tracks"]):
        if tagwrite.writable(str(s["path"])):
            tagwrite.write(str(s["path"]), {"title": t["title"], "artist": t.get("artist") or d["artist"],
                                            "albumartist": d["artist"], "album": d["title"], "track_no": t["no"],
                                            "disc_no": t.get("disc") or 1, "year": d.get("year") or s["year"] or ""})
    if d.get("cover") and not any(p.name.lower().startswith(("cover.", "folder.", "front.")) for p in folder.iterdir()):
        try:
            with httpx.Client(timeout=20, follow_redirects=True) as c:
                r = c.get(d["cover"])
                r.raise_for_status()
            (folder / "cover.jpg").write_bytes(r.content)
        except httpx.HTTPError:
            pass        # beets finds a cover itself then


# ---------------------------------------------------------------- filing an album

def _batch() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)


@jobs.job("import_watched")
def import_watched(ctx: jobs.JobContext, name: str, key: str, held: str = ""):
    """One album from the watch folder (`held`: from _Duplicates or _Failed, filed anyway)."""
    where = place()
    if where is None or where.key != key:
        raise RuntimeError("the watch folder changed or can't be reached")
    out: dict = {"name": name}
    batch = _batch()
    work = env.UPLOAD_DIR / batch
    try:
        if not held:
            files = where.entries().get(name)
            if files is None:
                return {**out, "gone": True}
            music = [(rel, size) for rel, size, _ in files if formats.family(rel) in MUSIC]
            if music:
                with db.session() as s:
                    found = duplicates.check(music, s)["found"]
                if found:
                    where.move(name, "", "_Duplicates")
                    ctx.log(f"{len(found)} of its songs seem to be in the library already: set aside in _Duplicates")
                    return {**out, "duplicate": True, "found": found[:20]}
        folder = where.fetch(name, held, work)
        if folder.is_file():        # a song by itself: in a folder of its own, as beets files albums
            (work / folder.stem).mkdir(parents=True, exist_ok=True)
            folder = Path(shutil.move(str(folder), str(work / folder.stem / folder.name))).parent
        paths = [Path(r) / f for r, _, fs in os.walk(folder) for f in fs]
        music_paths = [p for p in paths if formats.family(p.name) in MUSIC]
        chips = [p for p in paths if formats.family(p.name) not in (None, *MUSIC)]
        if not music_paths and not chips:
            raise RuntimeError("there's no music in it")
        if chips:
            out["vgm_folder"] = _file_chips(ctx, chips, folder, name)
        if music_paths:
            songs = _album(music_paths)
            source, ref, d = match(songs, folder.name, ctx)
            out["match"] = source
            if source == "bandcamp":
                _apply(songs, d, folder)
            out.update(importer.file_music(ctx, folder, batch, autotag=False if source == "bandcamp" else None,
                                           search_id=ref if source == "musicbrainz" else ""))
        # what's left of it (from a computer, all of it: the library has a copy); the folders the music was in,
        # emptied, go
        _prune(folder)
        if isinstance(where, ComputerPlace) or folder.exists():
            where.move(name, held, "_Done")
        jobs.submit("scan", "Scan the watch folder's albums")
        return out
    except Exception:
        try:
            where.move(name, held, "_Failed")
        except Exception:
            log.exception("watch folder: couldn't set %s aside", name)
        raise
    finally:
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)       # a computer's album as it came: filed, or in its _Failed


def _file_chips(ctx, chips: list[Path], folder: Path, name: str) -> str:
    """Chiptunes and tracker modules, as uploads have them: into the VGM upload folder's Uploads, as they are."""
    dest_root = importer.upload_root("vgm") or importer.upload_root("music")
    if not dest_root:
        raise RuntimeError("add a VGM or music folder on the admin page first")
    for p in chips:
        dest = Path(dest_root) / "Uploads" / name / p.relative_to(folder)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copy2(p, dest)
            os.chmod(dest, 0o644)
        os.remove(p)
    ctx.log(f"copied {len(chips)} chiptune and tracker files to {dest_root}/Uploads")
    return str(Path(dest_root) / "Uploads")


def _prune(folder: Path):
    """The folders under `folder` (and it) that nothing is left in."""
    if not folder.is_dir():
        return
    for r, _dirs, _files in os.walk(folder, topdown=False):
        try:
            if not os.listdir(r):
                os.rmdir(r)
        except OSError:
            pass


# ---------------------------------------------------------------- looking every minute

_seen: dict[str, tuple[tuple, float]] = {}     # album → (how it looked, since when)
_state: dict = {"checked": 0.0, "error": "", "waiting": []}


def _busy() -> set[str]:
    with db.session() as s:
        return {(j.params or {}).get("name", "") for j in s.scalars(
            select(Job).where(Job.type == "import_watched", Job.status.in_(("queued", "running"))))}


def check():
    """One look: albums that stayed as they were for SETTLE are taken."""
    where = place()
    if where is None:
        _seen.clear()
        _state.update(error="" if not settings.get("watch_folder") else "the folder can't be reached", waiting=[])
        return
    try:
        found = where.entries()
    except Exception as e:      # a computer gone meanwhile, a share away: next time
        _state.update(error=str(e) or e.__class__.__name__, checked=time.time())
        return
    now, busy, waiting = time.time(), _busy(), []
    for name in list(_seen):
        if name not in found:
            del _seen[name]
    for name, files in found.items():
        if name in busy or not files:
            continue
        look = (len(files), sum(f[1] for f in files), max(f[2] for f in files))
        before = _seen.get(name)
        if before is None or before[0] != look:
            _seen[name] = (look, now)
        if now - _seen[name][1] >= SETTLE:
            jobs.submit("import_watched", f"Watch folder: {name}", name=name, key=where.key)
            _seen.pop(name, None)
        else:
            waiting.append(name)
    _state.update(checked=now, error="", waiting=sorted(waiting))


def state() -> dict:
    return dict(_state)


def start():
    def loop():
        time.sleep(30)
        while True:
            try:
                check()
            except Exception:
                log.exception("watch folder")
            time.sleep(POLL)
    threading.Thread(target=loop, name="watch-folder", daemon=True).start()

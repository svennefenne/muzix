"""The watch folder (Admin → Upload): albums put in a folder, on this server or on a computer linked through
Muzix Desktop (tunnel.py, when that computer allows it), are filed into the library by themselves, as
uploads are (organize/importer.py): a main genre, cover art, Genre/Artist/Artist - Year - Album.

Each album is first looked up on MusicBrainz, and a release counts when its songs are as many and as long as
the album's (match()); when none does, on Bandcamp, whose track list and cover then go into the files; when
neither has it, it's filed as its own tags say and listed as unmatched for the admin to look at.

The folder is looked at every minute; an album (a folder in it, or a single file) is taken once it hasn't
changed for two minutes, or at once with Transfer now (check(now=True): what doesn't change in a few
seconds). Its music goes into the library: from the server's folder itself, and from a computer's as a copy,
each file checked whole as it comes; once the library has every one of its songs, the computer's album is
deleted there (2026-11-12, the admin's choice: the library has it), else it goes to _Done. On the server,
what's left (covers, .cue, .nfo, .log) goes to _Done/<album>.

An album at least half of whose songs the library seems to have already goes to _Duplicates/<album>; with
fewer it's filed as any album. From _Duplicates the admin sees why (the songs and what they're like in the
library) and files it anyway: into the library's Duplicates/<artist>/<album> (2) beside its other copies, as
an album of its own, or in place of the library's copy, which goes to Duplicates instead; or throws it away
(into the computer's trash; on the server, deleted). One that couldn't be filed goes to _Failed/<album>.
Folders whose names start with "_" or "." are the watch folder's own, and left alone.
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
from .models import Job, Peer, Root
from .organize import duplicates, importer

log = logging.getLogger(__name__)

POLL = 60               # seconds between looks at the folder
DISC = re.compile(r"^(cd|dis[ck])[\s._-]*\d{1,2}$", re.I)    # an album's disc, in a folder of its own
SETTLE = 120            # seconds an album must stay as it is before it's taken
HELD = ("_Done", "_Duplicates", "_Failed")
DUPES = "Duplicates"    # the library's own folder for its other copies (organize/beetsplug/musicorg.py), not scanned
MUSIC = ("native", "decode")


# ---------------------------------------------------------------- where the folder is

class Place:
    """The watch folder: list what's in it, bring an album here, move one aside, delete one."""

    key = ""

    def entries(self, held: str = "") -> dict[str, list[tuple[str, int, float]]]:
        """Each album (in the folder, or in `held`): (path in it, size, modified) of its files."""
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

    def remove(self, name: str, held: str):
        """The album deleted: filed whole, the library has every song of it."""
        raise NotImplementedError

    def trash(self, name: str, held: str) -> str:
        """An album set aside, thrown away by the admin: "trash" (the computer's) or "deleted" (on this server,
        which has no trash)."""
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

    def entries(self, held=""):
        base = self.root / held if held else self.root
        out = {}
        if not base.is_dir():
            return out
        for e in os.scandir(base):
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
                        files.append((os.path.relpath(p, base), st.st_size, st.st_mtime))
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

    def remove(self, name, held):
        if "/" in name or name in ("", ".", ".."):
            raise ValueError("not an album in the watch folder")
        path = self._at(name, held)
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()

    def trash(self, name, held):
        self.remove(name, held)
        return "deleted"


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

    def _file(self, rel: str, held: str):
        return tunnel.get(self.peer_id).chunks("watch_file", timeout=120, path=self.path, held=held, rel=rel)

    def fetch(self, name, held, into):
        """The album copied here, each file checked whole (as long as the computer said it is): one that comes
        short fails the album, which then stays on the computer."""
        files = self.entries(held).get(name)
        if files is None:
            raise RuntimeError("it isn't in the watch folder any more")
        into.mkdir(parents=True, exist_ok=True)
        for rel, size, _ in files:
            dest = (into / rel).resolve()
            if into.resolve() not in dest.parents:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as out:
                for chunk in self._file(rel, held):
                    out.write(chunk)
            if dest.stat().st_size != size:
                raise RuntimeError(f"{rel} came short from the computer ({dest.stat().st_size} of {size} bytes)")
        return into / name

    def move(self, name, held, to):
        self._ask("watch_move", name=name, held=held, to=to)

    def held(self):
        return {h: [e["name"] for e in self._ask("watch_list", held=h)] for h in HELD[1:]}

    def remove(self, name, held):
        self._ask("watch_delete", name=name, held=held)

    def trash(self, name, held):
        self._ask("watch_trash", name=name, held=held)
        return "trash"


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


HOW = ("duplicates", "album", "replace")     # an album from _Duplicates filed: into Duplicates, as any, in place of


def _album_folder(path: str) -> str:
    """The album folder a song is in (the one above a disc's folder)."""
    folder = os.path.dirname(path)
    return os.path.dirname(folder) if DISC.match(os.path.basename(folder)) else folder


def replaced(found: list[dict]) -> list[str]:
    """The library's albums a copy put in the watch folder would replace: each folder of the library songs it
    was found like, when at least half of that folder's songs were."""
    count = Counter(_album_folder(f["match"]["path"]) for f in found if (f.get("match") or {}).get("path"))
    out = []
    for folder, n in count.items():
        songs = sum(1 for _r, _d, fs in os.walk(folder) for f in fs if formats.family(f) in MUSIC)
        if songs and 2 * n >= songs:
            out.append(folder)
    return sorted(out)


def _aside(folder: str) -> str:
    """A library album into the library's Duplicates/<artist>/<album> (2) and on (as the musicorg plugin names
    them), which the library doesn't scan: its place is for the copy replacing it."""
    with db.session() as s:
        roots = [r.path for r in s.scalars(select(Root).where(Root.kind == "music"))]
    root = next((r for r in roots if folder.startswith(r.rstrip("/") + "/")), None)
    parts = os.path.relpath(folder, root).split(os.sep) if root else []
    if root is None or len(parts) < 2 or parts[0] == DUPES:
        raise RuntimeError(f"{folder} isn't an album in the library")
    dest, n = os.path.join(root, DUPES, parts[-2], parts[-1]), 2
    while os.path.lexists(dest):
        dest, n = os.path.join(root, DUPES, parts[-2], f"{parts[-1]} ({n})"), n + 1
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.move(folder, dest)
    return dest


@jobs.job("import_watched")
def import_watched(ctx: jobs.JobContext, name: str, key: str, held: str = "", how: str = ""):
    """One album from the watch folder (`held`: from _Duplicates or _Failed, filed anyway; from _Duplicates
    `how`: into the library's Duplicates folder (the default), as an album of its own, or in place of the
    library's copy)."""
    where = place()
    if where is None or where.key != key:
        raise RuntimeError("the watch folder changed or can't be reached")
    if how and (held != "_Duplicates" or how not in HOW):
        raise ValueError(f"not a way to file it: {how}")
    out: dict = {"name": name}
    duplicate = held == "_Duplicates" and how in ("", "duplicates")     # beside the library's copy, in Duplicates
    batch = _batch()
    work = env.UPLOAD_DIR / batch
    moved: list[tuple[str, str]] = []       # the library's copies put aside for this one (how="replace")
    try:
        if not held:
            files = where.entries().get(name)
            if files is None:
                return {**out, "gone": True}
            music = [(rel, size) for rel, size, _ in files if formats.family(rel) in MUSIC]
            if music:
                with db.session() as s:
                    found = duplicates.check(music, s)["found"]
                if found and 2 * len(found) >= len(music):
                    where.move(name, "", "_Duplicates")
                    ctx.log(f"{len(found)} of its {len(music)} songs seem to be in the library already: set aside in _Duplicates")
                    return {**out, "duplicate": True, "songs": len(music), "found": found[:40]}
                if found:
                    ctx.log(f"{len(found)} of its {len(music)} songs seem to be in the library already, fewer than half: "
                            "filed as any album")
        if how == "replace":
            files = where.entries(held).get(name) or []
            music = [(rel, size) for rel, size, _ in files if formats.family(rel) in MUSIC]
            with db.session() as s:
                old = replaced(duplicates.check(music, s)["found"])
            for f in old:       # first, so the new one takes their place
                moved.append((f, _aside(f)))
                ctx.log(f"the library's {f} put aside in {moved[-1][1]}")
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
            albums = _albums_in(folder, music_paths)
            if len(albums) == 1:
                songs = _album(albums[0][1])
                source, ref, d = match(songs, albums[0][0].name, ctx)
                if source == "bandcamp":
                    _apply(songs, d, albums[0][0])
                out.update(importer.file_music(ctx, folder, batch, autotag=False if source == "bandcamp" else None,
                                               search_id=ref if source == "musicbrainz" else "", duplicate=duplicate))
                bandcamp = {(d["artist"].lower(), d["title"].lower())} if source == "bandcamp" else set()
            else:
                # several albums (an artist's, say): each looked up by itself; beets then matches each one with
                # MusicBrainz in one go, and keeps Bandcamp's names for those only Bandcamp has
                ctx.log(f"{len(albums)} albums in it")
                bandcamp = set()
                for where_, paths in albums:
                    songs = _album(paths)
                    source, _ref, d = match(songs, where_.name, ctx)
                    if source == "bandcamp":
                        _apply(songs, d, where_)
                        bandcamp.add((d["artist"].lower(), d["title"].lower()))
                out.update(importer.file_music(ctx, folder, batch, duplicate=duplicate))
            # each album as it was filed: matched with MusicBrainz (beets says which release), Bandcamp, or neither
            for a in out.get("albums") or []:
                a["match"] = "musicbrainz" if a.get("mbid") else \
                    "bandcamp" if (a["artist"].lower(), a["album"].lower()) in bandcamp else "none"
            got = {a["match"] for a in out.get("albums") or []}
            out["match"] = got.pop() if len(got) == 1 else "mixed" if got else "none"
        if moved:
            out["replaced"] = [{"from": a, "to": b} for a, b in moved]
        # from a computer: once the library has every one of its songs, the album is deleted there (else it's
        # kept in _Done); on the server, what's left of it, the folders the music was in emptied
        songs = sum(int(a.get("songs") or 0) for a in out.get("albums") or [])
        if isinstance(where, ComputerPlace):
            if songs == len(music_paths):
                try:
                    where.remove(name, held)
                    out["removed"] = True
                    ctx.log(f"all {songs} of its songs are in the library: deleted from the computer's watch folder")
                except Exception as e:      # a Muzix Desktop before 0.4.22, say
                    ctx.log(f"couldn't delete it on the computer ({e}): kept in _Done")
                    where.move(name, held, "_Done")
            else:
                ctx.log(f"{songs} of its {len(music_paths)} songs were filed: kept in _Done on the computer")
                where.move(name, held, "_Done")
        else:
            _prune(folder)
            if folder.exists():
                where.move(name, held, "_Done")
        jobs.submit("scan", "Scan the watch folder's albums")
        return out
    except Exception:
        for was, now in reversed(moved):        # the library's copies back where they were
            try:
                if not os.path.lexists(was):
                    shutil.move(now, was)
            except Exception:
                log.exception("watch folder: couldn't put %s back", was)
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


def _albums_in(folder: Path, music: list[Path]) -> list[tuple[Path, list[Path]]]:
    """The albums in what was put in the watch folder, each with its songs: a folder with music in it is one,
    a disc's folder (CD1, Disc 2) is part of the one above it."""
    out: dict[Path, list[Path]] = {}
    for p in music:
        album = p.parent
        if album != folder and DISC.match(album.name):
            album = album.parent
        out.setdefault(album, []).append(p)
    return sorted(out.items(), key=lambda a: str(a[0]))


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
_checking = threading.Lock()                    # the minute's look and Transfer now's, one at a time
NOW_LOOK = 3.0      # seconds between Transfer now's two looks: an album that changes between them is still coming in


def _busy() -> set[str]:
    with db.session() as s:
        return {(j.params or {}).get("name", "") for j in s.scalars(
            select(Job).where(Job.type == "import_watched", Job.status.in_(("queued", "running"))))}


def _look(files) -> tuple:
    return len(files), sum(f[1] for f in files), max(f[2] for f in files)


def check(now: bool = False) -> dict:
    """One look: albums that stayed as they were for SETTLE are taken. `now` (Transfer now): at once, each album
    that stays as it is between two looks NOW_LOOK apart (one still being copied in waits). Says which were taken
    and which wait."""
    with _checking:
        where = place()
        if where is None:
            _seen.clear()
            _state.update(error="" if not settings.get("watch_folder") else "the folder can't be reached", waiting=[])
            if now:
                raise RuntimeError(_state["error"] or "no watch folder is set")
            return {"taken": [], "waiting": []}
        try:
            found = where.entries()
            if now:
                time.sleep(NOW_LOOK)
                again = where.entries()
        except Exception as e:      # a computer gone meanwhile, a share away: next time
            _state.update(error=str(e) or e.__class__.__name__, checked=time.time())
            if now:
                raise
            return {"taken": [], "waiting": []}
        t, busy, waiting, taken = time.time(), _busy(), [], []
        for name in list(_seen):
            if name not in found:
                del _seen[name]
        for name, files in found.items():
            if name in busy or not files:
                continue
            look = _look(files)
            before = _seen.get(name)
            if before is None or before[0] != look:
                _seen[name] = (look, t)
            if (bool(again.get(name)) and _look(again[name]) == look) if now else t - _seen[name][1] >= SETTLE:
                jobs.submit("import_watched", f"Watch folder: {name}", name=name, key=where.key)
                _seen.pop(name, None)
                taken.append(name)
            else:
                waiting.append(name)
        _state.update(checked=t, error="", waiting=sorted(waiting))
        return {"taken": sorted(taken), "waiting": sorted(waiting)}


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

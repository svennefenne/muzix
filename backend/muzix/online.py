"""Online music archives, browsed and played without adding anything to the library.

The archives are plain web folders (the "Index of" pages web servers make), so one reader
covers them all. A folder is fetched when someone opens it and kept for a few hours; a file
is downloaded when it's opened or played, into a cache of its own that the cache pruning job
keeps under ONLINE_CACHE_LIMIT. Nothing is fetched in the background: the archives are run by
volunteers, and some ask robots to stay away.

Game rips (the Joshw sets) come as one .7z per game with an .m3u that names and times each
song, NEZplug style; those names and times are used when they're there.
"""

import logging
import os
import posixpath
import re
import shutil
import threading
import time
import zipfile
from dataclasses import dataclass, field
from html import unescape
from urllib.parse import quote, unquote, urlencode

import httpx

from . import __version__, env, formats, render, vgmrips, zxart
from .lengths import play_plan

log = logging.getLogger("muzix.online")
UA = f"Muzix/{__version__} (+https://github.com/svennefenne/muzix)"
ONLINE_CACHE_LIMIT = 5 * 1024 ** 3
MAX_DOWNLOAD = 100 * 1024 ** 2
MAX_UNPACKED = 300 * 1024 ** 2
LISTING_TTL = 6 * 3600
ARCHIVES = (".zip", ".7z")


@dataclass(frozen=True)
class Source:
    id: str
    name: str                        # the archive's own name
    label: str                       # what's in it
    about: str
    base: str
    system: str = ""                 # for the system's colours, and tunes that don't say
    top: tuple[str, ...] = ()        # the folders worth showing at the top, when the rest won't play
    starts: tuple[tuple[str, str], ...] = ()   # (label, path) shortcuts into the archive


# Modland sorts by tracker; these are the ones Muzix plays (libopenmpt, libgme, sidplayfp, zxtune123, UADE)
MODLAND_PLAYABLE = (
    "Composer 669", "Composer 670 (CDFM)", "Digibooster", "Digibooster Pro", "Digital Sound Interface Kit",
    "Digital Symphony", "Digital Tracker DTM", "Digital Tracker MOD", "Digitrakker", "Disorder Tracker 2",
    "DSMI Compact", "Epic Megagames MASI", "Extreme Tracker", "Farandole Composer", "Fasttracker",
    "Fasttracker 2", "FamiTracker", "General DigiMusic", "Graoumf Tracker", "Graoumf Tracker 2",
    "Gameboy Sound System", "HES", "HVSC", "Imago Orpheus", "Impulsetracker", "KSS", "Mad Tracker 2",
    "Megadrive GYM", "MO3", "Multitracker", "Nintendo SPC", "Nintendo Sound Format", "OctaMED MMD0",
    "OctaMED MMD1", "OctaMED MMD2", "OctaMED MMD3", "Oktalyzer", "OpenMPT MPTM", "Polytracker",
    "Protracker", "Pumatracker", "Real Tracker", "Screamtracker 2", "Screamtracker 3",
    "Slight Atari Player", "Soundtracker", "Soundtracker 2.6", "Startrekker AM", "Startrekker FLT8",
    "Symphonie", "Ultratracker", "Unis 669", "Velvet Studio", "Video Game Music", "X-Tracker", "YM",
    "AY Emul", "AHX", "HivelyTracker", "Future Composer 1.3", "Future Composer 1.4", "Game Music Creator",
    "Images Music System", "Chiptracker", "Quadra Composer", "Face The Music", "Composer 667", "TCB Tracker",
    "Funktracker", "Liquid Tracker", "V2", "SoundFX",
    # UADE's (and a few more libopenmpt plays), each checked by playing one of its songs
    "AM Composer", "AProSys", "Actionamics", "Activision Pro", "Anders Oland", "Arpeggiator", "Art And Magic",
    "Art Of Noise", "Astroidea XMF", "Asylum", "Audio Sculpture", "BP SoundMon 2", "BP SoundMon 3",
    "Beathoven Synthesizer", "Ben Daglish", "Ben Daglish SID", "Core Design", "Darius Zendeh", "Dave Lowe",
    "Dave Lowe New", "David Hanney", "David Whittaker", "Delitracker Custom", "Delta Music", "Delta Music 2",
    "Desire", "Digital Mugician", "Digital Mugician 2", "Digital Sonix And Chrome",
    "Digital Sound And Music Interface", "Digital Sound Interface Kit RIFF", "Dirk Bialluch",
    "Dynamic Studio Professional", "Dynamic Synthesizer", "EarAche", "Electronic Music System",
    "Electronic Music System v6", "FM Tracker", "Follin Player II", "Forgotten Worlds", "Fred Gray", "FredMon",
    "Future Composer BSI", "Future Player", "GlueMon", "Hippel", "Hippel 7V", "Hippel COSO",
    "His Master's Noise", "Howie Davies", "InStereo!", "InStereo! 2.0", "Infogrames", "JamCracker",
    "Janko Mrsic-Flogel", "Jason Brooke", "Jason Page", "Jason Page Old", "Jeroen Tel", "Leggless Music Editor",
    "Lionheart", "MCMD", "Magnetic Fields Packer", "Maniacs Of Noise", "Mark Cooksey", "Mark Cooksey Old",
    "Mark II", "Medley", "MultiMedia Sound", "Music Assembler", "MusicMaker V8", "NovoTrade Packer",
    "OctaMED MMDC", "Octalyser", "Paul Shields", "Paul Summers", "Peter Verswyvelen", "Pretracker",
    "Professional Sound Artists", "Protracker IFF", "RealSID", "Richard Joseph", "Rob Hubbard",
    "Rob Hubbard ST", "Sam Coupe COP", "Sean Connolly", "SidMon 1", "SidMon 2", "Silmarils", "Sonic Arranger",
    "Sound Images", "Sound Master II v1", "Sound Master II v3", "SoundPlayer", "Soundtracker Pro II",
    "Special FX", "Special FX ST", "Spectrum", "Speedy A1 System", "Steve Barrett", "SunTronic", "SynTracker",
    "Synthesis", "TFM Music Maker", "TFMX", "TFMX ST", "The Musical Enlightenment", "Thomas Hermann",
    "Tomy Tracker", "Unique Development", "Voodoo Supreme Synthesizer", "Wally Beben", "YMST",
)

SOURCES = [
    Source("hvsc", "HVSC", "Commodore 64",
           "The High Voltage SID Collection: every C64 tune anyone has found, over 60,000, by musician.",
           "https://hvsc.brona.dk/HVSC/C64Music/", "Commodore 64", top=("MUSICIANS", "GAMES", "DEMOS"),
           starts=(("Musicians", "MUSICIANS"), ("Games", "GAMES"), ("Demos", "DEMOS"))),
    Source("modland", "Modland", "Tracker modules",
           "The biggest module archive: Amiga and PC tracker music, by tracker, then by composer.",
           "https://modland.com/pub/modules/", "Amiga / PC tracker", top=MODLAND_PLAYABLE,
           starts=(("Protracker", "Protracker"), ("Fasttracker 2", "Fasttracker 2"),
                   ("Impulsetracker", "Impulsetracker"), ("Screamtracker 3", "Screamtracker 3"))),
    Source("asma", "ASMA", "Atari 8-bit",
           "The Atari SAP Music Archive: POKEY chip music by composer, game and group.",
           "https://asma.atari.org/asma/", "Atari 8-bit", top=("Composers", "Games", "Groups", "Misc", "Unknown"),
           starts=(("Composers", "Composers"), ("Games", "Games"), ("Groups", "Groups"))),
    Source("nsf", "Joshw", "NES & Famicom",
           "Complete NES and Famicom soundtracks, a set per game, every song named and timed.",
           "https://nsf.joshw.info/", "NES / Famicom"),
    Source("gbs", "Joshw", "Game Boy",
           "Game Boy and Game Boy Color soundtracks, a set per game.",
           "https://gbs.joshw.info/", "Game Boy"),
    Source("spc", "Joshw", "Super Nintendo",
           "Super Nintendo soundtracks, a set per game.",
           "https://spc.joshw.info/", "Super Nintendo"),
    Source("hes", "Joshw", "PC Engine",
           "PC Engine and TurboGrafx-16 soundtracks, a set per game.",
           "https://hes.joshw.info/", "PC Engine"),
    Source("kss", "Joshw", "MSX & Sega 8-bit",
           "MSX, Master System and Game Gear soundtracks, a set per game.",
           "https://kss.joshw.info/", "MSX", top=("MSX", "Master System", "Game Gear")),
    Source("zxart", "ZXArt", "ZX Spectrum",
           "Nearly 30,000 ZX Spectrum tunes from games and the demoscene: the top list, by author or by party.",
           "https://zxart.ee/", "ZX Spectrum",
           starts=(("Top tunes", "top"), ("Authors", "authors"), ("Parties", "parties"))),
    Source("vgmrips", "VGMRips", "Arcade & computers",
           "Game soundtracks logged from the real sound chips: arcade boards, consoles and Japanese computers, a pack per game.",
           "https://vgmrips.net/", "",
           starts=(("Systems", "systems"), ("Composers", "composers"), ("Chips", "chips"))),
    Source("sceneorg", "scene.org", "Demoscene",
           "Music from demo parties and scene artists: tracker modules and recordings, mostly zipped.",
           "https://archive.scene.org/pub/music/", "",
           starts=(("Artists", "artists"), ("Groups", "groups"), ("Disks", "disks"))),
]
BY_ID = {s.id: s for s in SOURCES}


class OnlineError(Exception):
    """Something to tell the listener: the archive didn't answer, or sent something odd."""


# ---------------------------------------------------------------- paths

def source(sid: str) -> Source:
    if sid not in BY_ID:
        raise OnlineError("No such archive")
    return BY_ID[sid]


def parts(path: str) -> list[str]:
    """A path inside an archive, as checked folder and file names."""
    out = [p for p in (path or "").strip("/").split("/") if p]
    if any(p in (".", "..") or "\\" in p or "\0" in p for p in out):
        raise OnlineError("Not a path in this archive")
    return out


def remote_url(src: Source, names: list[str], folder: bool) -> str:
    url = src.base + "/".join(quote(n, safe="()!'~,;:@&=+$") for n in names)
    return url + "/" if folder and names else url


def cache_dir():
    return env.CACHE_DIR / "online"


def local_path(src: Source, names: list[str]) -> str:
    return str(cache_dir() / src.id / os.path.join(*names)) if names else str(cache_dir() / src.id)


def kind_of(name: str) -> str | None:
    """"tune" for a file Muzix plays, "archive" for a zip or 7z that may hold some."""
    low = name.lower()
    if low.endswith(ARCHIVES):
        return "archive"
    return "tune" if formats.family(low) else None


# ---------------------------------------------------------------- listings

_listings: dict[str, tuple[float, dict]] = {}
_listing_lock = threading.Lock()
SIZE = re.compile(r"^(\d+(?:\.\d+)?)\s*([KMG]?)(?:i?B)?$", re.I)


def _http() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": UA}, timeout=25, follow_redirects=True)


def _get(url: str) -> httpx.Response:
    """GET, trying once more when the connection drops halfway (big listings sometimes do)."""
    with _http() as client:
        try:
            return client.get(url)
        except httpx.TransportError:
            time.sleep(1)
            return client.get(url)


def parse_index(html: str) -> list[tuple[str, bool, int]]:
    """(name, is a folder, size in bytes or 0) for each entry of an "Index of" page."""
    out, seen = [], set()
    anchors = list(re.finditer(r'<a\s[^>]*?href="([^"]+)"[^>]*>', html, re.I))
    for i, m in enumerate(anchors):
        href = unescape(m.group(1))
        if href.startswith(("?", "/", "#", "../", "./")) or re.match(r"(?i)^[a-z][a-z0-9+.-]*:", href):
            continue
        folder = href.endswith("/")
        name = unquote(href.rstrip("/"))
        if not name or "/" in name or name in seen or name in (".", ".."):
            continue
        seen.add(name)
        size = 0
        if not folder:
            # the size sits in the text after the link, before the next one
            tail = html[m.end(): anchors[i + 1].start() if i + 1 < len(anchors) else m.end() + 400]
            for tok in reversed(re.sub(r"<[^>]+>", " ", tail.split("\n", 1)[0]).replace("&nbsp;", " ").split()):
                s = SIZE.match(tok)
                if s and not re.match(r"^\d{4}$", tok):
                    size = int(float(s.group(1)) * {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}[s.group(2).upper()])
                    break
        out.append((name, folder, size))
    return out


def _cached(url: str, build):
    """`build()`'s result for a page, kept for LISTING_TTL; an old copy when the archive is down."""
    with _listing_lock:
        hit = _listings.get(url)
    if hit and time.time() - hit[0] < LISTING_TTL:
        return hit[1]
    try:
        data = build()
    except OnlineError:
        if hit:
            return hit[1]
        raise
    with _listing_lock:
        if len(_listings) > 2000:
            for k in sorted(_listings, key=lambda k: _listings[k][0])[:500]:
                del _listings[k]
        _listings[url] = (time.time(), data)
    return data


def _page(src: Source, url: str) -> str:
    try:
        r = _get(url)
        if r.status_code == 404:
            raise OnlineError("That folder isn't in the archive any more")
        r.raise_for_status()
        return r.text
    except httpx.HTTPError as e:
        log.info("listing %s failed: %s", url, e)
        raise OnlineError(f"{src.name} isn't answering right now")


def listing(src: Source, path: str, page: int = 0) -> dict:
    """The folder at `path`: sub-folders, then the files Muzix can open. Archives that list a
    folder a page at a time (VGMRips) say whether there's `more` after `page`."""
    names = parts(path)
    if src.id == "zxart":
        return _zxart_listing(src, names)
    if src.id == "vgmrips":
        return _vgmrips_listing(src, names, max(0, page))
    url = remote_url(src, names, True)
    entries = _cached(url, lambda: parse_index(_page(src, url)))
    dirs = [{"name": n, "path": _join(names, n)} for n, folder, _ in entries if folder
            and (names or not src.top or n in src.top)]
    files = [{"name": n, "path": _join(names, n), "size": size} for n, folder, size in entries if not folder]
    return _folder(src, names, dirs, files, [{"name": n, "path": "/".join(names[:i + 1])} for i, n in enumerate(names)])


def _join(names: list[str], name: str) -> str:
    return "/".join([*names, name])


def _folder(src: Source, names: list[str], dirs: list[dict], files: list[dict], crumbs: list[dict],
            keep_order: bool = False, more: bool = False, total: int | None = None) -> dict:
    playable, other = [], 0
    for f in files:
        k = kind_of(f["name"])
        if k:
            playable.append({**f, "kind": k, "size": f.get("size", 0),
                             "format": "" if k == "archive" else formats.ext_of(f["name"]),
                             "chip": formats.family(f["name"]) in formats.RENDERED})
        else:
            other += 1
    return {
        "source": src.id, "path": "/".join(names), "name": crumbs[-1]["name"] if crumbs else src.label,
        "system": src.system, "crumbs": crumbs,
        "dirs": dirs if keep_order else sorted(dirs, key=lambda d: d["name"].casefold()),
        "files": playable if keep_order else sorted(playable, key=lambda f: f.get("title", f["name"]).casefold()),
        "other": other, "more": more, "total": total,
    }


def _vgmrips_listing(src: Source, names: list[str], page: int) -> dict:
    """VGMRips' groups, most packs first as the site has them, and their packs a page at a time."""
    if not names:
        return _folder(src, names, [{"name": n, "path": p} for p, n in vgmrips.ROOT], [], [], keep_order=True)
    url = vgmrips.page_url(names, page)
    if url is None:
        raise OnlineError("That folder isn't in the archive")
    here = "/".join(names)
    if len(names) > 1 and here not in vgmrips.folder_names:
        _vgmrips_listing(src, [names[0]], 0)                 # for the breadcrumbs
    crumbs = [{"name": vgmrips.folder_names[names[0]], "path": names[0]}]
    if len(names) > 1:
        crumbs.append({"name": vgmrips.folder_names.get(here, names[-1]), "path": here})
    if len(names) == 1:
        dirs = _cached(url, lambda: vgmrips.parse_groups(_page(src, url), names[0]))
        return _folder(src, names, dirs, [], crumbs, keep_order=True)
    files, total, more = _cached(url, lambda: vgmrips.parse_packs(_page(src, url)))
    return _folder(src, names, [], files, crumbs, keep_order=True, more=more, total=total)


def _zxart_listing(src: Source, names: list[str]) -> dict:
    if not names:
        return _folder(src, names, [{"name": n, "path": p} for p, n in zxart.ROOT], [], [])
    url = zxart.api_url(names)
    if url is None:
        raise OnlineError("That folder isn't in the archive")
    if names[0] != "authors" or len(names) > 1:
        _zxart_listing(src, ["authors"])                     # tunes name their authors by id
    if len(names) > 1 and "/".join(names) not in zxart.folder_names:
        _zxart_listing(src, [names[0]])                      # for the breadcrumbs
    dirs, files = _cached(url, lambda: zxart.parse(_page(src, url), zxart.authors))
    crumbs = [{"name": zxart.folder_names.get("/".join(names[:i + 1]), n), "path": "/".join(names[:i + 1])}
              for i, n in enumerate(names)]
    return _folder(src, names, dirs, files, crumbs, keep_order=names == ["top"])


# ---------------------------------------------------------------- downloads

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def fetch(src: Source, path: str, companion: bool = False) -> str:
    """The file at `path`, downloaded once into the cache (a `companion` is a song's sample file)."""
    names = parts(path)
    if not names or not (companion or kind_of(names[-1])):
        raise OnlineError("Muzix can't play that file")
    out = local_path(src, names)
    if os.path.exists(out):
        os.utime(out)                  # recently used: kept longest when the cache is pruned
        return out
    with _lock(out):
        if os.path.exists(out):
            return out
        os.makedirs(os.path.dirname(out), exist_ok=True)
        part = out + ".part"
        try:
            url = zxart.file_url(names) if src.id == "zxart" else remote_url(src, names, False)
            if url is None:
                raise OnlineError("That file isn't in the archive")
            with _http() as client, client.stream("GET", url) as r:
                if r.status_code == 404:
                    raise OnlineError("That file isn't in the archive any more")
                r.raise_for_status()
                if int(r.headers.get("content-length") or 0) > MAX_DOWNLOAD:
                    raise OnlineError("That file is too big to play from here")
                got = 0
                with open(part, "wb") as f:
                    for chunk in r.iter_bytes(256 * 1024):
                        got += len(chunk)
                        if got > MAX_DOWNLOAD:
                            raise OnlineError("That file is too big to play from here")
                        f.write(chunk)
            os.replace(part, out)
        except httpx.HTTPError as e:
            log.info("download %s/%s failed: %s", src.id, path, e)
            raise OnlineError(f"{src.name} isn't answering right now")
        finally:
            if os.path.exists(part):
                os.remove(part)
    return out


def _safe_member(name: str) -> str | None:
    """An archive member's path, or None for one that would land outside its folder."""
    name = name.replace("\\", "/")
    norm = posixpath.normpath(name)
    if name.startswith("/") or norm.startswith("../") or norm in ("..", ".") or re.match(r"^[A-Za-z]:", name):
        return None
    return norm


def _wanted(name: str) -> bool:
    low = name.lower()
    return kind_of(low) == "tune" or low.endswith(".m3u")


def unpack(archive: str) -> str:
    """The playable files of a zip or 7z, unpacked next to it (once)."""
    dest = archive + ".d"
    if os.path.isdir(dest):
        return dest
    with _lock(dest):
        if os.path.isdir(dest):
            return dest
        tmp = dest + ".part"
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        try:
            if archive.lower().endswith(".zip"):
                _unzip(archive, tmp)
            else:
                _un7z(archive, tmp)
            os.replace(tmp, dest)
        except (OSError, zipfile.BadZipFile, ValueError) as e:
            log.info("unpacking %s failed: %s", archive, e)
            raise OnlineError("That archive won't open")
        except Exception as e:      # py7zr raises its own kinds for damaged or odd archives
            log.info("unpacking %s failed: %r", archive, e)
            raise OnlineError("That archive won't open")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return dest


def _unzip(archive: str, into: str):
    with zipfile.ZipFile(archive) as z:
        members = [(i, _safe_member(i.filename)) for i in z.infolist() if not i.is_dir()]
        members = [(i, n) for i, n in members if n and _wanted(n)]
        if sum(i.file_size for i, _ in members) > MAX_UNPACKED:
            raise ValueError("too big unpacked")
        for info, name in members:
            target = os.path.join(into, name)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)


def _un7z(archive: str, into: str):
    import py7zr
    with py7zr.SevenZipFile(archive, "r") as z:
        infos = [i for i in z.list() if not i.is_directory]
        names = [i.filename for i in infos if _safe_member(i.filename) and _wanted(i.filename)]
        if sum(i.uncompressed for i in infos if i.filename in names) > MAX_UNPACKED:
            raise ValueError("too big unpacked")
        if names:
            z.extract(path=into, targets=names)


# ---------------------------------------------------------------- tunes

@dataclass
class Opened:
    title: str
    rows: list[dict] = field(default_factory=list)   # track rows, as scanner.read_file makes them


_opened: dict[str, Opened] = {}


def open_file(src: Source, path: str) -> Opened:
    """The tunes in a file or archive, downloading it if need be."""
    local = fetch(src, path)
    if src.id == "modland" and formats.family(path) == "uade":
        parent = path.rpartition("/")[0]
        for name in companions(src, path):
            try:
                fetch(src, f"{parent}/{name}", companion=True)
            except OnlineError:
                pass                  # UADE says so if the song can't do without it
    if local in _opened:              # a downloaded file never changes
        return _opened[local]
    from . import scanner
    if src.id == "hvsc":
        _songlengths(src)
    name = os.path.basename(local)
    rows = []
    if kind_of(name) == "archive":
        folder = unpack(local)
        found = []
        for r, _, fs in os.walk(folder):
            found += [os.path.join(r, f) for f in fs if kind_of(f) == "tune"]
        found.sort(key=lambda p: p.casefold())
        for f in found:
            member = os.path.relpath(f, folder).replace(os.sep, "/")
            for row in _with_playlist(f, scanner.read_file(f, "vgm")):
                rows.append({**row, "member": member, "local": f})
    else:
        rows = [{**row, "member": "", "local": local} for row in scanner.read_file(local, "vgm")]
    title = re.sub(r"\.(zip|7z)$", "", name, flags=re.I)
    for row in rows:
        _label(src, path, row, title)
    opened = Opened(title, rows)
    if len(_opened) > 500:
        _opened.clear()
    _opened[local] = opened
    return opened


def _label(src: Source, path: str, row: dict, title: str):
    """Fills what file names and the archive's layout say when the file itself doesn't."""
    if src.id == "zxart":
        zxart.label(parts(path), row)
    elif src.id == "vgmrips":
        vgmrips.label(path, row)
    extra = row.get("extra") or {}
    if (row.get("album") or "").endswith(".d"):       # named after the folder it was unpacked into
        row["album"] = title
    if "_" in row["title"] and " " not in row["title"]:   # a file name: 5_Title_Tunes
        row["title"] = row["title"].replace("_", " ")
    if src.system and not extra.get("system"):
        row["extra"] = {**extra, "system": src.system}
    if formats.family(row["format"]) not in formats.RENDERED:
        row["kind"] = "music"
    # Joshw names its sets "Game (year)(developer)(publisher)[system]"
    album = row.get("album") or ""
    m = re.match(r"^(.+?)\s*\((\d{4})[^)]*\)", album) or re.match(r"^(.+?)\s*\((\d{4})", os.path.basename(path))
    if m and src.id in ("nsf", "gbs", "spc", "hes", "kss"):
        row["album"] = re.sub(r"\s*\[[^\]]*\]$", "", m.group(1)).strip()   # without "[Japanese title]"
        row["year"] = row.get("year") or int(m.group(2))
    if not row.get("artist"):
        names = parts(path)
        if src.id == "modland" and len(names) >= 3 and names[1].strip("_- ").lower() != "unknown":
            row["artist"] = row["albumartist"] = names[1]          # Modland: format/composer/file
        elif src.id in ("asma", "sceneorg") and len(names) >= 3 and names[0].lower() in ("composers", "artists"):
            row["artist"] = row["albumartist"] = names[1].replace("_", " ")


def companions(src: Source, path: str) -> list[str]:
    """The files an Amiga song needs beside it, which share its name give or take a prefix or an
    extension: TFMX's smpl.x for mdat.x, Jason Page's smp.x for jpn.x, Infogrames' x.ins for xa.dum."""
    parent, _, name = path.rpartition("/")
    url = remote_url(src, parts(parent), True)
    try:
        entries = _cached(url, lambda: parse_index(_page(src, url)))
    except OnlineError:
        return []
    core = song_core(name)
    return [n for n, folder, size in entries
            if not folder and n != name and not kind_of(n) and size < 20 * 1024 ** 2
            and (song_core(n) == core or (n.lower().endswith(".ins") and core.startswith(song_core(n))))][:4]


def song_core(name: str) -> str:
    """"mdat.unicorn" and "smpl.unicorn" → "unicorn"; "bob4a.dum" → "bob4a"."""
    low = name.lower()
    pre, _, rest = low.partition(".")
    if rest and (pre in formats.PREFIXES or pre in ("smpl", "smp", "sam", "ins")):
        return rest
    return low.rsplit(".", 1)[0]


def _with_playlist(path: str, rows: list[dict]) -> list[dict]:
    """A game rip's songs as its .m3u lists them: named, timed, without the sound effects."""
    if formats.family(path) != "gme":
        return rows
    stem = os.path.splitext(path)[0]
    m3u = next((p for p in (stem + ".m3u", stem + ".M3U") if os.path.exists(p)), None)
    if not m3u:
        folder, me = os.path.dirname(path), os.path.basename(path).casefold()
        m3us = [f for f in os.listdir(folder) if f.lower().endswith(".m3u")]
        mine = [f for f in m3us if me in open(os.path.join(folder, f), "rb").read().decode("latin-1").casefold()]
        m3u = os.path.join(folder, mine[0]) if len(mine) == 1 else None
    if not m3u:
        return rows
    me = os.path.basename(path).casefold()
    entries = [e[1:] for e in read_nezplug(m3u, formats.ext_of(path)) if os.path.basename(e[0]).casefold() == me]
    if not entries:
        return rows
    by_index = {max(r["subsong"], 0): r for r in rows}
    out = []
    for n, (index, title, length, fade) in enumerate(entries, 1):
        base = by_index.get(index)
        if base is None:
            continue
        extra = {k: v for k, v in (base.get("extra") or {}).items() if k not in ("length", "natural", "intro", "loop")}
        if length:
            extra["length"] = length
        if fade is not None:
            extra["fade"] = fade
        out.append({**base, "subsong": index, "title": title or base["title"], "track_no": n,
                    "duration": length or base["duration"], "extra": extra})
    return out or rows


def _time(s: str) -> float | None:
    s = s.strip()
    if not s or s == "-":
        return None
    try:
        secs = 0.0
        for p in s.split(":"):
            secs = secs * 60 + float(p)
        return secs
    except ValueError:
        return None


def read_nezplug(m3u: str, ext: str) -> list[tuple[str, int, str, float | None, float | None]]:
    """(file, track index for libgme, title, play time, fade) per line of a NEZplug .m3u:
    "file.nsf::NSF,3,Title,1:23,-,10". Decimal numbers count from 1 (from 0 for KSS),
    $hex numbers from 0, as libgme reads them."""
    raw = open(m3u, "rb").read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp932", "replace")     # Japanese rips are often Shift-JIS
    out = []
    for line in text.splitlines():
        if line.startswith("#") or "::" not in line:
            continue
        fields = [f.replace("\\,", ",") for f in re.split(r"(?<!\\),", line.split("::", 1)[1])]
        if len(fields) < 2:
            continue
        num = fields[1].strip()
        try:
            index = int(num[1:], 16) if num.startswith("$") else int(num) - (0 if ext == "kss" else 1)
        except ValueError:
            continue
        if index < 0:
            continue
        title = fields[2].strip() if len(fields) > 2 else ""
        length = _time(fields[3]) if len(fields) > 3 else None
        fade = _time(fields[5]) if len(fields) > 5 else None
        out.append((line.split("::", 1)[0].strip().replace("\\", "/"), index, title, length, fade))
    return out


def _songlengths(src: Source):
    """HVSC's own list of how long each tune plays, fetched with the first tune."""
    from .meta import chip
    try:
        path = fetch_aside(src, "DOCUMENTS/Songlengths.md5", max_age=30 * 86400)
    except OnlineError:
        return
    chip.load_songlengths(path)


def fetch_aside(src: Source, path: str, max_age: float) -> str:
    """A support file (not a tune), downloaded again when older than `max_age`."""
    names = parts(path)
    out = local_path(src, names)
    if os.path.exists(out) and time.time() - os.path.getmtime(out) < max_age:
        return out
    with _lock(out):
        if os.path.exists(out) and time.time() - os.path.getmtime(out) < max_age:
            return out
        os.makedirs(os.path.dirname(out), exist_ok=True)
        try:
            r = _get(remote_url(src, names, False))
            r.raise_for_status()
        except httpx.HTTPError as e:
            if os.path.exists(out):
                return out
            raise OnlineError(str(e))
        with open(out + ".part", "wb") as f:
            f.write(r.content)
        os.replace(out + ".part", out)
    return out


def find(src: Source, path: str, member: str, sub: int) -> dict:
    """The row for one tune: the file's first when `sub` is -1 and the file has several."""
    rows = [r for r in open_file(src, path).rows if r["member"] == member]
    if not rows:
        raise OnlineError("That tune isn't in the file")
    return next((r for r in rows if r["subsong"] == sub), rows[0])


def display_duration(row: dict) -> float:
    fam = formats.family(row["format"])
    if fam not in formats.RENDERED:
        return row["duration"] or 0
    total, _ = play_plan(fam, row.get("extra"), row["duration"])
    return total or row["duration"] or 0


def serial(src: Source, path: str, row: dict) -> dict:
    q = {"source": src.id, "path": path, "sub": row["subsong"]}
    if row["member"]:
        q["member"] = row["member"]
    extra = row.get("extra") or {}
    return {
        "key": f"online:{src.id}:{path}|{row['member']}|{row['subsong']}",
        "title": row["title"], "artist": row.get("artist") or "", "album": row.get("album") or "",
        "duration": display_duration(row), "format": row["format"], "kind": row["kind"],
        "system": extra.get("system", ""), "year": row.get("year") or 0,
        "stream": "/api/online/stream?" + urlencode(q),
        "cast_native": not render.needs_transcode(row["format"], row.get("codec") or "",
                                                  row.get("sample_rate") or 0, "cast"),
    }


# ---------------------------------------------------------------- the cache

def prune(limit: int = ONLINE_CACHE_LIMIT) -> tuple[int, int]:
    """Drops the least recently played downloads once the cache passes `limit`; (kept, removed)."""
    items = []
    cache = cache_dir()
    if not os.path.isdir(cache):
        return 0, 0
    for sid in os.listdir(cache):
        for r, ds, fs in os.walk(cache / sid):
            # an archive and its unpacked files go together; .part folders are being unpacked
            ds[:] = [d for d in ds if not d.endswith((".d", ".d.part"))]
            for f in fs:
                p = os.path.join(r, f)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                if f.endswith(".part"):
                    if time.time() - st.st_mtime > 3600:
                        os.remove(p)
                    continue
                size = st.st_size + _tree_size(p + ".d")
                items.append((st.st_mtime, size, p))
    total = sum(s for _, s, _ in items)
    removed = 0
    for _, size, p in sorted(items):
        if total <= limit:
            break
        if p.endswith("Songlengths.md5"):
            continue
        os.remove(p)
        shutil.rmtree(p + ".d", ignore_errors=True)
        _opened.pop(p, None)
        total -= size
        removed += 1
    return len(items) - removed, removed


def _tree_size(d: str) -> int:
    if not os.path.isdir(d):
        return 0
    return sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(d) for f in fs)

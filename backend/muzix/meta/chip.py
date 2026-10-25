"""Header parsers for chip-music and tracker formats.

Each reader returns a ChipInfo: song-level metadata plus one entry per
subsong (NSF/GBS/SID/... files hold many tunes; each becomes a track).
Durations are None when the format doesn't say (the player then uses the
configured default length).
"""

import csv
import gzip
import hashlib
import os
import re
import struct
import subprocess
import tempfile
from dataclasses import dataclass, field

from .. import env, formats


@dataclass
class Subsong:
    index: int
    title: str = ""
    duration: float | None = None   # best single-pass estimate, for display
    fade: float | None = None       # the file's own fade-out
    intro: float | None = None      # seconds up to the loop point
    loop: float | None = None       # seconds of the looping part
    length: float | None = None     # fixed play time given by the file / database
    natural: float | None = None    # ends by itself after this long (no loop)

    def timing(self) -> dict:
        return {k: v for k, v in dict(intro=self.intro, loop=self.loop, length=self.length,
                                      natural=self.natural, fade=self.fade).items() if v}


@dataclass
class ChipInfo:
    title: str = ""
    artist: str = ""
    album: str = ""          # game / collection
    year: int = 0
    copyright: str = ""
    system: str = ""
    duration: float | None = None
    subsongs: list[Subsong] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


def _cstr(b: bytes) -> str:
    b = b.split(b"\0", 1)[0]
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return b.decode(enc).strip()
        except UnicodeDecodeError:
            pass
    return ""


def _clean(s: str) -> str:
    s = s.strip()
    return "" if s in ("<?>", "?", "-", "Unknown", "unknown", "<???>") else s


def _year(s: str) -> int:
    m = re.search(r"(19|20)\d\d", s or "")
    return int(m.group(0)) if m else 0


# ---------------------------------------------------------------- NES / Game Boy

def read_nsf(data: bytes) -> ChipInfo:
    if data[:5] != b"NESM\x1a":
        raise ValueError("not an NSF")
    songs, start = data[6], data[7]
    info = ChipInfo(title=_clean(_cstr(data[0x0E:0x2E])), artist=_clean(_cstr(data[0x2E:0x4E])),
                    copyright=_clean(_cstr(data[0x4E:0x6E])), system="NES / Famicom")
    info.album = info.title
    info.year = _year(info.copyright)
    info.subsongs = [Subsong(i) for i in range(songs)]
    info.extra["start_song"] = max(0, start - 1)
    return info


def read_nsfe(data: bytes) -> ChipInfo:
    if data[:4] != b"NSFE":
        raise ValueError("not an NSFe")
    info = ChipInfo(system="NES / Famicom")
    pos, songs, labels, times, fades, playlist = 4, 0, [], [], [], None
    while pos + 8 <= len(data):
        size, cid = struct.unpack_from("<I4s", data, pos)
        body = data[pos + 8:pos + 8 + size]
        pos += 8 + size
        if cid == b"INFO" and len(body) >= 9:
            songs = body[8] if len(body) > 8 else 1
        elif cid == b"auth":
            parts = [_clean(p.decode("utf-8", "replace")) for p in body.split(b"\0")]
            parts += [""] * 4
            info.album, info.artist, info.copyright = parts[0], parts[1], parts[2]
            info.extra["ripper"] = parts[3]
        elif cid == b"tlbl":
            labels = [p.decode("utf-8", "replace") for p in body.split(b"\0")]
        elif cid == b"time":
            times = [t for (t,) in struct.iter_unpack("<i", body[:len(body) // 4 * 4])]
        elif cid == b"fade":
            fades = [t for (t,) in struct.iter_unpack("<i", body[:len(body) // 4 * 4])]
        elif cid == b"plst":
            playlist = list(body)
        elif cid == b"NEND":
            break
    info.title = info.album
    info.year = _year(info.copyright)
    order = playlist if playlist else list(range(songs))
    for i in order:
        t = times[i] if i < len(times) and times[i] >= 0 else None
        f = fades[i] if i < len(fades) and fades[i] >= 0 else None
        sec = t / 1000 if t else None
        info.subsongs.append(Subsong(i, labels[i] if i < len(labels) else "", sec,
                                     f / 1000 if f is not None else None, length=sec))
    return info


def read_gbs(data: bytes) -> ChipInfo:
    if data[:3] != b"GBS":
        raise ValueError("not a GBS")
    songs = data[4]
    info = ChipInfo(title=_clean(_cstr(data[0x10:0x30])), artist=_clean(_cstr(data[0x30:0x50])),
                    copyright=_clean(_cstr(data[0x50:0x70])), system="Game Boy")
    info.album = info.title
    info.year = _year(info.copyright)
    info.subsongs = [Subsong(i) for i in range(songs)]
    return info


# ---------------------------------------------------------------- SNES

def read_spc(data: bytes) -> ChipInfo:
    if not data.startswith(b"SNES-SPC700 Sound File Data"):
        raise ValueError("not an SPC")
    info = ChipInfo(system="Super Nintendo")
    if data[0x23] == 26:  # ID666 present
        info.title = _clean(_cstr(data[0x2E:0x4E]))
        info.album = _clean(_cstr(data[0x4E:0x6E]))
        info.extra["dumper"] = _clean(_cstr(data[0x6E:0x7E]))
        info.extra["comment"] = _clean(_cstr(data[0x7E:0x9E]))
        secs_txt = data[0xA9:0xAC]
        text_format = all(c in b"0123456789\0 " for c in secs_txt) and \
            all(c in b"0123456789/\0 -" for c in data[0x9E:0xA9])
        if text_format:
            secs = int(secs_txt.strip(b"\0 ") or 0)
            fade = int(data[0xAC:0xB1].strip(b"\0 ") or 0) / 1000
            info.artist = _clean(_cstr(data[0xB1:0xD1]))
            info.year = _year(_cstr(data[0x9E:0xA9]))
        else:
            secs = int.from_bytes(data[0xA9:0xAC], "little")
            fade = int.from_bytes(data[0xAC:0xB0], "little") / 1000
            info.artist = _clean(_cstr(data[0xB0:0xD0]))
        duration = float(secs) if 0 < secs < 3600 else None
        info.subsongs = [Subsong(0, info.title, duration, fade if fade < 60 else None, length=duration)]
    _spc_xid6(data, info)
    if not info.subsongs:
        info.subsongs = [Subsong(0, info.title)]
    return info


def _spc_xid6(data: bytes, info: ChipInfo):
    pos = 0x10200
    if data[pos:pos + 4] != b"xid6":
        return
    end = pos + 8 + int.from_bytes(data[pos + 4:pos + 8], "little")
    pos += 8
    while pos + 4 <= min(end, len(data)):
        sid, typ, ln = data[pos], data[pos + 1], int.from_bytes(data[pos + 2:pos + 4], "little")
        if typ == 0:   # value stored in the length field
            body, pos = b"", pos + 4
        else:
            body = data[pos + 4:pos + 4 + ln]
            pos += 4 + ((ln + 3) & ~3)
        if sid == 0x01:
            info.title = _cstr(body) or info.title
        elif sid == 0x02:
            info.album = _cstr(body) or info.album
        elif sid == 0x03:
            info.artist = _cstr(body) or info.artist
        elif sid == 0x10:
            info.extra["ost"] = _cstr(body)
        elif sid == 0x14 and typ == 0:
            info.year = ln
    if info.subsongs:
        info.subsongs[0].title = info.title


# ---------------------------------------------------------------- C64

_songlengths: dict[str, list[float]] = {}
_songlengths_path = ""


def load_songlengths(path: str):
    """HVSC Songlengths.md5: "<md5>=m:ss.mmm m:ss ..." per file."""
    global _songlengths, _songlengths_path
    if not path or path == _songlengths_path:
        return
    table = {}
    try:
        with open(path, encoding="latin-1") as f:
            for line in f:
                if "=" not in line or line.startswith((";", "[")):
                    continue
                md5, times = line.strip().split("=", 1)
                out = []
                for t in times.split():
                    t = re.sub(r"\(.*?\)", "", t)
                    m, _, s = t.partition(":")
                    try:
                        out.append(int(m) * 60 + float(s))
                    except ValueError:
                        out.append(0)
                table[md5.lower()] = out
    except OSError:
        return
    _songlengths, _songlengths_path = table, path


def read_sid(data: bytes) -> ChipInfo:
    if data[:4] not in (b"PSID", b"RSID"):
        raise ValueError("not a SID")
    songs, start = struct.unpack_from(">HH", data, 0x0E)
    info = ChipInfo(title=_clean(_cstr(data[0x16:0x36])), artist=_clean(_cstr(data[0x36:0x56])),
                    copyright=_clean(_cstr(data[0x56:0x76])), system="Commodore 64")
    info.album = info.title
    info.year = _year(info.copyright)
    lengths = _songlengths.get(hashlib.md5(data).hexdigest(), [])
    info.subsongs = []
    for i in range(max(1, songs)):
        sec = (lengths[i] or None) if i < len(lengths) else None
        info.subsongs.append(Subsong(i, duration=sec, length=sec))
    info.extra["start_song"] = max(0, start - 1)
    version = struct.unpack_from(">H", data, 4)[0]
    if version >= 2 and len(data) > 0x78:
        flags = struct.unpack_from(">H", data, 0x76)[0]
        info.extra["clock"] = {1: "PAL", 2: "NTSC", 3: "PAL/NTSC"}.get((flags >> 2) & 3, "")
        info.extra["sid_model"] = {1: "6581", 2: "8580", 3: "6581/8580"}.get((flags >> 4) & 3, "")
    return info


# ---------------------------------------------------------------- VGM (Sega etc.)

def read_vgm(data: bytes) -> ChipInfo:
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    if data[:4] != b"Vgm ":
        raise ValueError("not a VGM")
    gd3_rel, total, _loop_off, loop_samples = struct.unpack_from("<IIII", data, 0x14)
    info = ChipInfo()
    duration = total / 44100 if total else None
    intro = loop = natural = None
    if duration and loop_samples:
        loop = loop_samples / 44100
        intro = max(0.0, duration - loop)
    else:
        natural = duration
    if gd3_rel:
        g = 0x14 + gd3_rel
        if data[g:g + 4] == b"Gd3 ":
            length = struct.unpack_from("<I", data, g + 8)[0]
            fields = data[g + 12:g + 12 + length].decode("utf-16-le", "replace").split("\0")
            fields += [""] * 11
            info.title = fields[0] or fields[1]
            info.album = fields[2] or fields[3]
            info.system = fields[4] or fields[5]
            info.artist = fields[6] or fields[7]
            info.year = _year(fields[8])
            info.extra.update(vgm_by=fields[9], notes=fields[10].strip())
    info.system = info.system or "Sega / arcade"
    info.subsongs = [Subsong(0, info.title, duration, intro=intro, loop=loop, natural=natural)]
    return info


# ---------------------------------------------------------------- Atari ST

def read_ym(data: bytes, path: str | None = None) -> ChipInfo:
    info = ChipInfo(system="Atari ST")
    if data[2:7] == b"-lh5-" and path:
        return _ym_tool(path, info)
    if data[:4] in (b"YM5!", b"YM6!") and data[4:12] == b"LeOnArD!":
        frames, _attrs, drums = struct.unpack_from(">IIH", data, 12)
        _clock, rate, loop_frame, extra = struct.unpack_from(">IHIH", data, 22)
        pos = 34 + extra
        for _ in range(drums):
            size = struct.unpack_from(">I", data, pos)[0]
            pos += 4 + size
        strings = data[pos:pos + 768].split(b"\0")
        strings += [b""] * 3
        info.title, info.artist = _clean(_cstr(strings[0])), _clean(_cstr(strings[1]))
        info.extra["comment"] = _clean(_cstr(strings[2]))
        info.duration = frames / rate if rate else None
        sub = Subsong(0, info.title, info.duration)
        if info.duration and loop_frame < frames:
            sub.intro, sub.loop = loop_frame / rate, (frames - loop_frame) / rate
        info.subsongs = [sub]
        return info
    elif path:
        return _ym_tool(path, info)
    info.subsongs = [Subsong(0, info.title, info.duration)]
    return info


def _ym_tool(path: str, info: ChipInfo) -> ChipInfo:
    """Compressed YM files: ask ymtool (StSound) for the metadata."""
    try:
        out = subprocess.run(["ymtool", "info", path], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        out = ""
    fields = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    info.title = _clean(fields.get("title", ""))
    info.artist = _clean(fields.get("author", ""))
    info.extra["comment"] = _clean(fields.get("comment", ""))
    ms = fields.get("duration_ms", "")
    info.duration = int(ms) / 1000 if ms.isdigit() and int(ms) > 0 else None
    sub = Subsong(0, info.title, info.duration)
    loop_ms = fields.get("loop_ms", "")
    if info.duration and loop_ms.isdigit():
        sub.intro, sub.loop = int(loop_ms) / 1000, info.duration - int(loop_ms) / 1000
    info.subsongs = [sub]
    return info


# ---------------------------------------------------------------- FamiTracker

def read_ftm(data: bytes) -> ChipInfo:
    if not data.startswith(b"FamiTracker Module"):
        raise ValueError("not a FamiTracker module")
    info = ChipInfo(system="NES / Famicom")
    pos, tracks = 22, 1
    while pos + 24 <= len(data):
        name = data[pos:pos + 16].rstrip(b"\0")
        if name == b"END":
            break
        version, size = struct.unpack_from("<II", data, pos + 16)
        body = data[pos + 24:pos + 24 + size]
        pos += 24 + size
        if name == b"INFO" and len(body) >= 96:
            info.title = _clean(_cstr(body[0:32]))
            info.artist = _clean(_cstr(body[32:64]))
            info.copyright = _clean(_cstr(body[64:96]))
        elif name == b"HEADER" and version >= 3 and body:
            tracks = body[0] + 1
            names = body[1:].split(b"\0")[:tracks]
            info.subsongs = [Subsong(i, _cstr(n)) for i, n in enumerate(names)]
    info.album = info.title
    info.year = _year(info.copyright)
    if not info.subsongs:
        info.subsongs = [Subsong(i) for i in range(tracks)]
    return info


# ---------------------------------------------------------------- MIDI

def read_midi(path: str) -> ChipInfo:
    import mido

    info = ChipInfo(system="MIDI")
    mid = mido.MidiFile(path, clip=True)
    for msg in mid.tracks[0] if mid.tracks else []:
        if msg.type == "track_name" and not info.title:
            info.title = msg.name.strip()
        elif msg.type == "copyright":
            info.copyright = msg.text.strip()
    try:
        info.duration = mid.length
    except (ValueError, ZeroDivisionError):
        info.duration = None
    info.year = _year(info.copyright)
    info.subsongs = [Subsong(0, info.title, info.duration, natural=info.duration)]
    return info


# ---------------------------------------------------------------- tracker modules

def read_module_title(data: bytes, ext: str) -> str:
    """Song title straight from the header; durations come from ffprobe later."""
    try:
        if data[:4] == b"IMPM":
            return _cstr(data[4:30])
        if data[:17] == b"Extended Module: ":
            return _cstr(data[17:37])
        if data[0x2C:0x30] == b"SCRM":
            return _cstr(data[:28])
        if data[:3] == b"MTM":
            return _cstr(data[4:24])
        if data[:4] == b"MT20":
            return _cstr(data[42:106])
        if ext in ("mod", "m15", "stk", "nst") and len(data) > 1084:
            return _cstr(data[:20])
    except IndexError:
        pass
    return ""


READERS = {
    "nsf": read_nsf, "nsfe": read_nsfe, "gbs": read_gbs, "spc": read_spc,
    "sid": read_sid, "psid": read_sid, "rsid": read_sid, "vgm": read_vgm, "vgz": read_vgm,
    "ftm": read_ftm,
}


def read(path: str, ext: str) -> ChipInfo:
    fam = formats.family(ext)
    if fam == "midi":
        return read_midi(path)
    if fam == "zxtune":
        return read_zxtune(path, ext)
    with open(path, "rb") as f:
        data = f.read(64 * 1024 * 1024)
    if ext == "ym":
        return read_ym(data, path)
    if ext in READERS:
        info = READERS[ext](data)
    else:
        info = ChipInfo(system=formats.system_for(ext))
    if fam == "module":
        return _module(path, data, ext, info)
    if fam == "gme":
        _gme_times(path, info)
    if not info.subsongs:
        info.subsongs = [Subsong(0, info.title)]
    return info


# ---------------------------------------------------------------- ZX Spectrum and more (zxtune123)

ZX_NAME = re.compile(r"^(?P<artist>.+?) - (?P<title>.+?)(?: \((?P<year>(?:19|20)\d\d)\))?(?: \([^)]*\))*$")


class NotATune(ValueError):
    """zxtune123 doesn't recognise the file (a .ts video, say), or can't play it."""


def read_zxtune(path: str, ext: str) -> ChipInfo:
    """Title, author and tracker from zxtune123's index; the length of one pass from a quick render."""
    from .. import render
    with tempfile.TemporaryDirectory(dir=env.CACHE_DIR) as tmp:
        src = render.zx_input(path, tmp)
        index = os.path.join(tmp, "index.csv")
        render._run(["zxtune123", "--silent", "--index", f"filename={index},csv=[Type]|[Title]|[Author]|[Program]|[Date]", src])
        try:
            with open(index, encoding="utf-8", errors="replace", newline="") as f:
                rows = list(csv.reader(f, delimiter="|"))[1:]   # the first line repeats the template
        except OSError:
            rows = []
        if not rows:
            raise NotATune(path)
        kind, title, author, program, date = (rows[0] + [""] * 5)[:5]
        seconds = render.zx_length(path, tmp)
    if seconds < 0.5:
        raise NotATune(path)          # recognised but silent: some Liquid Tracker songs
    title, author, year = _clean(title), _clean(author), _year(date)
    # tunes often say nothing about themselves; archives name them "Author - Title (1996)"
    m = ZX_NAME.match(os.path.splitext(os.path.basename(path))[0])
    if m and not (title and author):
        title, author = title or m["title"], author or m["artist"]
        year = year or int(m["year"] or 0)
    return ChipInfo(title=title, artist=author, year=year, system=formats.system_for(ext) or "ZX Spectrum",
                    duration=seconds, subsongs=[Subsong(-1, title, duration=seconds, natural=seconds)],
                    extra={k: v for k, v in dict(tracker=_clean(program) or kind).items() if v})


MIN_EXTRA_SUBSONG = 60   # modules often hide short fragments as "subsongs"


def _module(path: str, data: bytes, ext: str, info: ChipInfo) -> ChipInfo:
    from . import openmpt
    info.title = read_module_title(data, ext)
    if openmpt.available():
        try:
            m = openmpt.info(path)
            info.title = m.title or info.title
            info.artist = m.artist
            info.extra["tracker"] = m.tracker
            if m.message:
                info.extra["message"] = m.message[:2000]
            subs = [Subsong(i, natural=d, duration=d) for i, d in enumerate(m.durations)
                    if i == 0 or d >= MIN_EXTRA_SUBSONG]
            if len(subs) == 1:
                subs[0].index = -1
            info.subsongs = subs
            return info
        except RuntimeError:
            pass
    info.subsongs = [Subsong(-1, info.title)]
    return info


def _gme_times(path: str, info: ChipInfo):
    """libgme knows loop points for some formats (and reads them from .m3u files)."""
    from . import gme
    if not gme.available():
        return
    try:
        times = gme.track_times(path)
    except RuntimeError:
        return
    if not info.subsongs:
        info.subsongs = [Subsong(i) for i in range(len(times))]
    for sub in info.subsongs:
        if not 0 <= sub.index < len(times):
            continue
        t = times[sub.index]
        sub.title = sub.title or t.title
        if t.loop and not sub.loop:
            sub.intro, sub.loop = t.intro or 0, t.loop
        if t.length and not (sub.length or sub.natural or sub.loop):
            sub.length = t.length
        if t.fade is not None and sub.fade is None:
            sub.fade = t.fade
        sub.duration = sub.duration or t.length
    info.album = info.album or times[0].game if times else info.album
    info.artist = info.artist or (times[0].author if times else "")
    info.system = info.system or (times[0].system if times else "")

"""Lyrics for a song: an .lrc file beside it (named like the song), lyrics in its own tags, or
LRCLIB (lrclib.net), a free, open database of time-synced lyrics. Synced lyrics come as lines
with times, so the player can follow along; plain ones as lines without. What LRCLIB says is
kept (not finding any too, for a while), so a song is looked up once."""

import logging
import os
import re
import shutil
from datetime import datetime, timedelta, timezone

import httpx
import mutagen
from mutagen.id3 import ID3

from . import art, enrich, settings
from .models import Album, LyricsCache, Track

log = logging.getLogger(__name__)
LRCLIB = "https://lrclib.net/api"
RETRY_MISSING = timedelta(days=14)     # LRCLIB grows: ask again about songs it didn't know

STAMP = re.compile(r"\[(\d+):(\d{1,2}(?:[.:]\d{1,3})?)\]")
OFFSET = re.compile(r"^\[offset:\s*([+-]?\d+)\s*\]$", re.I)
META = re.compile(r"^\[[a-z#]+:.*\]$", re.I)          # [ar:Artist], [ti:Title], [length:...]
WORD = re.compile(r"<\d+:\d{1,2}(?:[.:]\d{1,3})?>")     # enhanced LRC: a time per word


def parse(text: str) -> tuple[bool, list[dict]]:
    """(synced, lines): LRC text as lines with times, sorted; text without times as plain lines."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    offset, timed = 0.0, []
    for raw in text.split("\n"):
        raw = raw.strip()
        if m := OFFSET.match(raw):
            offset = int(m.group(1)) / 1000       # positive: the words come sooner
            continue
        stamps = []
        while m := STAMP.match(raw):
            stamps.append(int(m.group(1)) * 60 + float(m.group(2).replace(":", ".")))
            raw = raw[m.end():].strip()
        words = WORD.sub("", raw).strip()
        timed += [{"t": round(max(0.0, t - offset), 2), "text": words} for t in stamps]
    if timed:
        timed.sort(key=lambda line: line["t"])
        return True, timed
    plain = [line.strip() for line in text.split("\n") if not META.match(line.strip())]
    while plain and not plain[-1]:
        plain.pop()
    return False, [{"t": None, "text": line} for line in plain]


def sidecar(audio: str) -> str | None:
    """The .lrc file beside a song, named like it ("1. Song.mp3" -> "1. Song.lrc", any case)."""
    folder, name = os.path.split(audio)
    stem = os.path.splitext(name)[0].casefold()
    try:
        names = os.listdir(folder or ".")
    except OSError:
        return None
    for n in names:
        base, ext = os.path.splitext(n)
        if ext.casefold() == ".lrc" and base.casefold() == stem:
            return os.path.join(folder, n)
    return None


def read_text(path: str) -> str:
    """An .lrc file's text: UTF-8 or UTF-16 by their marks, else UTF-8, else Windows' Latin-1."""
    with open(path, "rb") as f:
        raw = f.read(1024 * 1024)
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", "replace")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", "replace")


def from_tags(path: str) -> str:
    """Lyrics written into the file's tags: ID3 (SYLT with times, else USLT), Vorbis/FLAC
    LYRICS, MP4 ©lyr, APE Lyrics. Many taggers store LRC text there, times and all."""
    try:
        f = mutagen.File(path)
    except Exception:
        return ""
    tags = getattr(f, "tags", None)
    if not tags:
        return ""
    if isinstance(tags, ID3):
        for frame in tags.getall("SYLT"):
            if frame.format == 2 and frame.text:          # times in milliseconds
                return "\n".join(f"[{ms // 60000:02d}:{ms % 60000 / 1000:05.2f}]{words.strip()}"
                                 for words, ms in frame.text)
        for frame in tags.getall("USLT"):
            if str(frame.text).strip():
                return str(frame.text)
        return ""
    for key in ("SYNCEDLYRICS", "LYRICS", "UNSYNCEDLYRICS", "©lyr", "Lyrics"):
        try:
            v = tags.get(key) if hasattr(tags, "get") else None
        except (KeyError, ValueError):
            v = None
        if v:
            v = v[0] if isinstance(v, list) else v
            if str(v).strip():
                return str(v)
    return ""


def _pick(results: list[dict], duration: float) -> dict | None:
    """The search result for this recording: about as long as the song, synced lyrics first."""
    fit = [r for r in results if r.get("syncedLyrics") or r.get("plainLyrics") or r.get("instrumental")]
    if duration:
        fit = [r for r in fit if abs((r.get("duration") or 0) - duration) <= 3]
    fit.sort(key=lambda r: (not r.get("syncedLyrics"), abs((r.get("duration") or 0) - duration)))
    return fit[0] if fit else None


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": enrich.UA}, timeout=8, follow_redirects=True)


def lrclib(artist: str, title: str, album: str, duration: float) -> dict | None:
    """LRCLIB's lyrics for a recording ({syncedLyrics, plainLyrics, instrumental}), or None.
    Raises httpx.HTTPError when LRCLIB can't be reached (so nothing gets kept)."""
    with _client() as c:
        q = {"artist_name": artist, "track_name": title}
        exact = {**q, "album_name": album, **({"duration": round(duration)} if duration else {})}
        r = c.get(f"{LRCLIB}/get", params=exact)
        if r.status_code == 200:
            return r.json()
        if r.status_code != 404:
            r.raise_for_status()
        r = c.get(f"{LRCLIB}/search", params=q)       # another album, a compilation, a remaster
        r.raise_for_status()
        return _pick(r.json(), duration)


def _answer(source: str, text: str, instrumental: bool = False, colors: list[str] | None = None) -> dict:
    synced, lines = parse(text)
    return {"source": source if lines or instrumental else None, "synced": synced, "lines": lines,
            "instrumental": instrumental and not lines, "colors": colors or []}


def for_track(s, t: Track) -> dict:
    """What the player shows for a song (see the module's docstring for where it comes from)."""
    colors = []
    alb = s.get(Album, t.album_id) if t.album_id else None
    if alb is not None and alb.art and not alb.art.startswith("embedded:"):
        colors = art.dominant_colors(alb.art)
    if t.subsong < 0:                       # chip files hold many songs and no lyrics
        if (lrc := sidecar(t.path)):
            try:
                return _answer("file", read_text(lrc), colors=colors)
            except OSError:
                log.warning("couldn't read %s", lrc)
        if t.kind == "music" and (text := from_tags(t.path)):
            return _answer("tags", text, colors=colors)
    if t.kind != "music" or not (t.artist or t.albumartist) or not t.title:
        return _answer("", "", colors=colors)
    kept = s.get(LyricsCache, t.id)
    now = datetime.now(timezone.utc)
    if kept is not None and (kept.found or now - kept.checked_at.replace(tzinfo=timezone.utc) < RETRY_MISSING):
        return _answer("lrclib", kept.synced or kept.plain, kept.instrumental, colors)
    if not settings.get("lyrics_online"):
        return _answer("", "", colors=colors)
    try:
        hit = lrclib(t.artist or t.albumartist, t.title, t.album, t.duration)
    except (httpx.HTTPError, ValueError) as e:
        log.info("LRCLIB: %s", e)
        return _answer("", "", colors=colors)
    hit = hit or {}
    row = LyricsCache(track_id=t.id, synced=hit.get("syncedLyrics") or "", plain=hit.get("plainLyrics") or "",
                      instrumental=bool(hit.get("instrumental")), found=bool(hit), checked_at=now)
    s.merge(row)
    return _answer("lrclib", row.synced or row.plain, row.instrumental, colors)


def _key(s: str) -> str:
    return re.sub(r"\W+", "", (s or "").casefold())


def _title_tag(path: str) -> str:
    try:
        head = read_text(path)[:4000]
    except OSError:
        return ""
    m = re.search(r"^\[ti:(.*)\]\s*$", head, re.I | re.M)
    return m.group(1).strip() if m else ""


def _take(lrc: str, new: str) -> bool:
    dest = os.path.splitext(new)[0] + ".lrc"
    if os.path.lexists(dest):
        log.warning("%s is already there; %s stays", dest, lrc)
        return False
    shutil.move(lrc, dest)
    return True


def carry(moves: dict[str, str], titles: dict[str, str] | None = None) -> int:
    """Songs that moved (old path -> new path) take their .lrc files along, renamed to match:
    the one named like the song, else (with `titles`, old path -> song title) one in the same
    folder whose name ends in the song's title or whose [ti:] tag is it, when only one song fits.
    Never over an existing file. How many went."""
    n, missing = 0, {}
    for old, new in moves.items():
        if old == new:
            continue
        if lrc := sidecar(old):
            n += _take(lrc, new)
        elif titles and _key(titles.get(old, "")):
            missing[old] = new
    for folder in sorted({os.path.dirname(old) for old in missing}):
        try:
            names = sorted(x for x in os.listdir(folder) if x.casefold().endswith(".lrc"))
        except OSError:
            continue
        for name in names:
            lrc = os.path.join(folder, name)
            stem, ti = _key(os.path.splitext(name)[0]), _key(_title_tag(lrc))
            fits = [old for old in missing if os.path.dirname(old) == folder
                    and (stem.endswith(_key(titles[old])) or ti == _key(titles[old]))]
            if len(fits) == 1:
                n += _take(lrc, missing.pop(fits[0]))
    return n

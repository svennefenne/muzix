"""Playlist files in the library folders (.m3u, .m3u8, .pls, .xspf, .wpl).

Album rippers leave a playlist in every album folder listing just that folder's songs; those
add nothing to the album and are skipped. The rest are kept as library-wide playlists. Their
entries are matched to tracks by path (absolute, relative to the playlist, or by the end of
the path, as playlists made on another computer start somewhere else), and failing that by
artist and title, from #EXTINF lines or the file name: playlists often outlive a reorganised
library, where every file has a new name.
"""

import html
import logging
import os
import re
from urllib.parse import unquote, urlparse

from sqlalchemy import delete, select

from . import db
from .models import FilePlaylist, FilePlaylistItem, Track

log = logging.getLogger("muzix.playlists")
EXTS = (".m3u", ".m3u8", ".pls", ".xspf", ".wpl")


def is_playlist(path: str) -> bool:
    return path.lower().endswith(EXTS)


def norm(s: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", (s or "").casefold()).split())


# ---------------------------------------------------------------- reading

class Entry:
    def __init__(self, ref: str, artist: str = "", title: str = "", duration: float = 0):
        self.ref, self.artist, self.title, self.duration = ref, artist, title, duration


def _text(path: str) -> str:
    raw = open(path, "rb").read()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", "replace")   # older .m3u files are Windows-1252


def read(path: str) -> list[Entry]:
    text = _text(path)
    low = path.lower()
    if low.endswith(".pls"):
        files = dict(re.findall(r"(?im)^File(\d+)=(.+?)\s*$", text))
        titles = dict(re.findall(r"(?im)^Title(\d+)=(.+?)\s*$", text))
        return [Entry(files[n], *_split(titles.get(n, ""))) for n in sorted(files, key=int)]
    if low.endswith(".xspf"):
        out = []
        for track in re.findall(r"(?s)<track>(.*?)</track>", text):
            loc = re.search(r"<location>(.*?)</location>", track)
            if loc:
                get = lambda tag: html.unescape((re.search(rf"<{tag}>(.*?)</{tag}>", track) or [None, ""])[1])
                out.append(Entry(html.unescape(loc.group(1)), get("creator"), get("title")))
        return out
    if low.endswith(".wpl"):
        return [Entry(html.unescape(src)) for src in re.findall(r'<media\s+src="([^"]+)"', text)]
    out, info = [], None
    for line in text.splitlines():
        line = line.strip()
        if line.upper().startswith("#EXTINF:"):
            secs, _, label = line[8:].partition(",")
            try:
                dur = float(secs)
            except ValueError:
                dur = 0
            info = (*_split(label), max(dur, 0))
        elif line and not line.startswith("#"):
            out.append(Entry(line, *(info or ("", "", 0))))
            info = None
    return out


def _split(label: str) -> tuple[str, str]:
    """"Artist - Title" as written in #EXTINF lines and .pls titles."""
    artist, sep, title = label.partition(" - ")
    return (artist.strip(), title.strip()) if sep else ("", label.strip())


def _local(ref: str) -> str | None:
    """The entry as a forward-slash path, or None for a web address."""
    if re.match(r"(?i)^file://", ref):
        ref = unquote(urlparse(ref).path)
        if re.match(r"^/[A-Za-z]:/", ref):
            ref = ref[1:]
    elif re.match(r"(?i)^[a-z][a-z0-9+.-]+://", ref):
        return None
    return ref.replace("\\", "/")


def own_folder_only(path: str, entries: list[Entry]) -> bool:
    """An album playlist: every entry is a song in the playlist's own folder."""
    folder = os.path.dirname(path)
    for e in entries:
        ref = _local(e.ref)
        if ref is None:
            return False
        if ref.startswith("/") or re.match(r"^[A-Za-z]:/", ref):
            if os.path.dirname(ref) != folder:
                return False
        elif "/" in ref:
            return False
    return True


# ---------------------------------------------------------------- matching

class Matcher:
    """Finds the library track an entry means."""

    def __init__(self, s):
        self.by_path: dict[str, int] = {}
        self.by_tail2: dict[str, list[int]] = {}
        self.by_name: dict[str, list[int]] = {}
        self.by_title: dict[str, list[tuple[int, str, str, float]]] = {}
        for tid, path, title, artist, albumartist, dur in s.execute(
                select(Track.id, Track.path, Track.title, Track.artist, Track.albumartist, Track.duration)
                .where(Track.subsong < 1)):
            self.by_path[path] = tid
            parts = path.casefold().split("/")
            self.by_tail2.setdefault("/".join(parts[-2:]), []).append(tid)
            self.by_name.setdefault(parts[-1], []).append(tid)
            if title:
                self.by_title.setdefault(norm(title), []).append((tid, norm(artist), norm(albumartist), dur))

    def find(self, playlist: str, e: Entry) -> int | None:
        ref = _local(e.ref)
        if ref is None:
            return None
        if ref.startswith("/") and ref in self.by_path:
            return self.by_path[ref]
        if not ref.startswith("/") and not re.match(r"^[A-Za-z]:/", ref):
            here = os.path.normpath(os.path.join(os.path.dirname(playlist), ref))
            if here in self.by_path:
                return self.by_path[here]
        parts = [p for p in ref.casefold().split("/") if p]
        if not parts:
            return None
        for hits in (self.by_tail2.get("/".join(parts[-2:])), self.by_name.get(parts[-1])):
            if hits and len(hits) == 1:
                return hits[0]
        if e.title:
            hit = self._by_words(e.title, [e.artist], e.duration)
            if hit:
                return hit
        return self._from_name(ref, playlist)

    def _by_words(self, title: str, artists: list[str], duration: float = 0) -> int | None:
        cands = self.by_title.get(norm(title)) or []
        names = [norm(a) for a in artists if a and norm(a)]
        fits = [c for c in cands if any(n and (n == c[1] or n == c[2] or n in c[1] or c[1] and c[1] in n) for n in names)]
        if not fits:
            return None
        if duration:
            fits.sort(key=lambda c: abs((c[3] or 0) - duration))
        return fits[0][0]

    def _from_name(self, ref: str, playlist: str = "") -> int | None:
        """From a file name like "Artist - Album - 03 - Title.mp3" or "01 - Title - Artist.mp3":
        any part may be the title (the last first), and the artist must show up in the entry's
        path or where the playlist lives."""
        stem = os.path.splitext(ref.rsplit("/", 1)[-1])[0]
        stem = re.sub(r"^[.\\/]*\s*\d{1,3}\s*[-._)]?\s*", "", stem)
        parts = [re.sub(r"^\d{1,3}\s*[-._]?\s*", "", p.strip()) for p in re.split(r"\s+-\s+", stem) if p.strip()]
        hint = f" {norm(f'{playlist} {ref}')} "   # whole words: "air" isn't in "pair"
        for title in [stem, *reversed(parts)]:
            fits = [c for c in self.by_title.get(norm(title)) or []
                    if (c[1] and f" {c[1]} " in hint) or (c[2] and f" {c[2]} " in hint)]
            if fits:
                return fits[0][0]
        return None


# ---------------------------------------------------------------- storing

def scan(ctx, found: list[tuple[int, str]], root_ids: list[int]):
    """Stores the playlist files found under the scanned roots; returns how many were kept."""
    kept, seen = 0, set()
    with db.session() as s:
        matcher = Matcher(s)
        for root_id, path in found:
            try:
                entries = read(path)
            except OSError as e:
                log.warning("cannot read playlist %s: %s", path, e)
                continue
            if not entries or own_folder_only(path, entries):
                continue
            ids = [t for t in (matcher.find(path, e) for e in entries) if t]
            if not ids:
                continue
            seen.add(path)
            pl = s.scalar(select(FilePlaylist).where(FilePlaylist.path == path))
            if pl is None:
                pl = FilePlaylist(path=path, root_id=root_id)
                s.add(pl)
            pl.name = os.path.splitext(os.path.basename(path))[0]
            pl.entries = len(entries)
            s.flush()
            s.execute(delete(FilePlaylistItem).where(FilePlaylistItem.playlist_id == pl.id))
            s.add_all(FilePlaylistItem(playlist_id=pl.id, position=i, track_id=t) for i, t in enumerate(ids))
            kept += 1
            ctx.log(f"  playlist {pl.name}: {len(ids)} of {len(entries)} songs found")
        for pl in s.scalars(select(FilePlaylist).where(FilePlaylist.root_id.in_(root_ids))):
            if pl.path not in seen:
                s.delete(pl)
    return kept

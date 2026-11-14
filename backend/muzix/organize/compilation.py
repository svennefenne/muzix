"""Own compilations: a folder of songs from different albums put together by the admin (not a release, so
MusicBrainz has nothing to match it with), filed as one album by Various Artists named after the folder, rather
than each song by itself (a folder whose songs are of different albums is split by them, organize/beetsplug/
musicorg.py, and a song by itself from an album goes to Uncategorized).

Its songs' tags are written before it's filed (as its tags say, organize/importer.py: own=True): the album
and album artist, the compilation flag, numbers 1, 2, 3... in the folder's order (a folder in it is a disc of
its own), and the year (the folder's, "Name - 2024", else its newest song's), each song's own year kept as its
original year. What the songs' own albums left in them (MusicBrainz's album ids, the album's type, label,
catalogue number) is taken away: it isn't this album's. A song keeps its artist, title and genre.

Where a folder is said to be one: in the watch folder's _Compilations folder (watch.py), or marked so on the
upload page (api/upload.py). One in the library already is made one by its album artist (Admin mode: Make
compilation, manage.edit_album)."""

import os
import re
from pathlib import Path

import mediafile

from .. import formats

VA = "Various Artists"
VA_NAMES = {"various artists", "various artist", "various", "va", "v.a.", "v/a", "v.a"}
MUSIC = ("native", "decode")
YEAR = re.compile(r"[(\[]?((?:19|20)\d\d)[)\]]?")
# the album's own, from the songs' albums: nothing of this one
CLEARED = ("mb_albumid", "mb_albumartistid", "mb_albumartistids", "mb_releasegroupid", "albumartist_sort",
           "albumartists", "albumartists_sort", "albumartist_credit", "albumartists_credit", "label", "catalognum",
           "barcode", "asin", "albumdisambig", "releasegroupdisambig", "albumstatus", "country", "media",
           "month", "day", "albumtype", "albumtypes")


def title_of(folder: str) -> tuple[str, int]:
    """(the compilation's name, its year or 0) from its folder's name: "Various Artists - 2024 - Summer Mix",
    "VA - Summer Mix", "Summer Mix (2024)" are all "Summer Mix"."""
    parts = [p.strip() for p in re.split(r"\s+[-–—]\s+", folder.strip()) if p.strip()]
    year = 0
    kept = []
    for p in parts:
        m = YEAR.fullmatch(p)
        if m and not year:
            year = int(m.group(1))
        else:
            kept.append(p)
    if len(kept) > 1 and kept[0].casefold() in VA_NAMES:
        kept = kept[1:]
    name = " - ".join(kept) or folder.strip()
    m = re.search(r"\s*[(\[]((?:19|20)\d\d)[)\]]\s*$", name)
    if m and m.start() > 0:
        year = year or int(m.group(1))
        name = name[:m.start()].strip()
    return name, year


def _natural(path: str) -> list:
    return [int(x) if x.isdigit() else x.casefold() for x in re.split(r"(\d+)", path)]


def songs_in(folder: Path) -> list[list[Path]]:
    """Its songs, disc by disc (the songs right in it, then each folder in it, by name), each in name order."""
    discs: dict[str, list[Path]] = {}
    for r, dirs, fs in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in fs:
            if not f.startswith(".") and formats.family(f) in MUSIC:
                p = Path(r) / f
                discs.setdefault(os.path.relpath(r, folder), []).append(p)
    order = sorted(discs, key=lambda d: (d != ".", _natural(d)))
    return [sorted(discs[d], key=lambda p: _natural(p.name)) for d in order]


def make(folder: Path, name: str = "", year: int = 0) -> dict:
    """The songs in `folder` tagged as one compilation (`name`: the folder's, without one): {"album", "year",
    "songs"}. A file whose tags can't be written stops it before any is: all or none of them."""
    folder = Path(folder)
    got_name, got_year = title_of(folder.name)
    name, year = (name or got_name).strip(), year or got_year
    discs = songs_in(folder)
    files = [(d, n, p) for d, songs in enumerate(discs, 1) for n, p in enumerate(songs, 1)]
    if not files:
        raise ValueError("there are no songs in it")
    read = [(d, n, p, mediafile.MediaFile(str(p))) for d, n, p in files]     # every one read first
    own_years = [(m.original_year or m.year or 0) for *_, m in read]
    year = year or max(own_years)
    for (d, n, p, m), own in zip(read, own_years):
        m.album, m.albumartist, m.comp = name, VA, True
        m.track, m.tracktotal = n, len(discs[d - 1])
        m.disc, m.disctotal = d, len(discs)
        for field in CLEARED:
            if hasattr(mediafile.MediaFile, field):
                setattr(m, field, None)
        m.albumtypes = ["album", "compilation"]     # an album: its length doesn't make it a single (releases.py)
        if own and not m.original_year:
            m.original_year = own
        m.year = year or None
        m.save()
    return {"album": name, "year": year, "songs": len(files)}

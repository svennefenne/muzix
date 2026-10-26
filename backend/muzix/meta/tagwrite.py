"""Writing an admin's metadata edits into audio files, and a cover into them.

`write(path, changes)` sets the given fields (title, artist, albumartist, album, track_no,
disc_no, year, genre); an empty value removes the tag. Track and disc totals already in the file
("3/12") are kept. Chip and tracker formats have no tags to write: `writable()` says no, and
their edits are kept in the database instead (TagOverride).
"""

import base64

import mutagen
from mutagen.apev2 import APEv2, APEValue, BINARY
from mutagen.asf import ASF
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK
from mutagen.mp4 import MP4, MP4Cover
from mutagen.ogg import OggFileType

from .. import formats
from . import tags  # noqa: F401  (mutagen's WavPack fix comes with it)

FIELDS = ("title", "artist", "albumartist", "album", "track_no", "disc_no", "year", "genre")
WRITABLE = {"mp3", "flac", "ogg", "oga", "opus", "m4a", "m4b", "mp4", "aac", "wv", "ape", "mpc", "tta",
            "wma", "aif", "aiff", "aifc", "wav", "dsf"}

ID3_FRAMES = {"title": TIT2, "artist": TPE1, "albumartist": TPE2, "album": TALB, "year": TDRC, "genre": TCON}
VORBIS = {"title": "TITLE", "artist": "ARTIST", "albumartist": "ALBUMARTIST", "album": "ALBUM",
          "track_no": "TRACKNUMBER", "disc_no": "DISCNUMBER", "year": "DATE", "genre": "GENRE"}
MP4_KEYS = {"title": "\xa9nam", "artist": "\xa9ART", "albumartist": "aART", "album": "\xa9alb",
            "year": "\xa9day", "genre": "\xa9gen"}
APE = {"title": "Title", "artist": "Artist", "albumartist": "Album Artist", "album": "Album",
       "track_no": "Track", "disc_no": "Disc", "year": "Year", "genre": "Genre"}
ASF_KEYS = {"title": "Title", "artist": "Author", "albumartist": "WM/AlbumArtist", "album": "WM/AlbumTitle",
            "track_no": "WM/TrackNumber", "disc_no": "WM/PartOfSet", "year": "WM/Year", "genre": "WM/Genre"}


class TagError(Exception):
    pass


def writable(path: str) -> bool:
    return formats.ext_of(path) in WRITABLE


def _text(v) -> str:
    return "" if v in (None, 0) else str(v)


def _numbered(new, old: str) -> str:
    """A track or disc number, keeping the total the file already had ("3/12")."""
    if not new:
        return ""
    total = old.split("/", 1)[1] if "/" in (old or "") else ""
    return f"{new}/{total}" if total else str(new)


def write(path: str, changes: dict):
    """Writes `changes` (FIELDS) into the file's tags."""
    try:
        audio = mutagen.File(path)
    except Exception as e:
        raise TagError(f"{path}: {e}") from e
    if audio is None:
        raise TagError(f"{path}: not a file whose tags can be written")
    if audio.tags is None:
        audio.add_tags()
    t = audio.tags
    changes = {k: v for k, v in changes.items() if k in FIELDS}
    if isinstance(t, ID3):
        for k, v in changes.items():
            if k in ("track_no", "disc_no"):
                frame = "TRCK" if k == "track_no" else "TPOS"
                value = _numbered(v, str(t[frame]) if frame in t else "")
                t.delall(frame)
                if value:
                    t.add((TRCK if k == "track_no" else TPOS)(encoding=3, text=value))
            else:
                cls = ID3_FRAMES[k]
                t.delall(cls.__name__)
                if _text(v):
                    t.add(cls(encoding=3, text=_text(v)))
        _save_id3(audio, path)
    elif isinstance(audio, MP4):
        for k, v in changes.items():
            if k in ("track_no", "disc_no"):
                key = "trkn" if k == "track_no" else "disk"
                total = t[key][0][1] if key in t and t[key] else 0
                if v:
                    t[key] = [(int(v), total)]
                else:
                    t.pop(key, None)
            elif _text(v):
                t[MP4_KEYS[k]] = [_text(v)]
            else:
                t.pop(MP4_KEYS[k], None)
        audio.save()
    elif isinstance(audio, ASF):
        for k, v in changes.items():
            if _text(v):
                t[ASF_KEYS[k]] = [_text(v)]
            else:
                t.pop(ASF_KEYS[k], None)
        audio.save()
    elif isinstance(audio, (FLAC, OggFileType)):
        for k, v in changes.items():
            key = VORBIS[k]
            value = _numbered(v, (t.get(key) or [""])[0]) if k in ("track_no", "disc_no") else _text(v)
            if value:
                t[key] = [value]
            elif key in t:
                del t[key]
        audio.save()
    elif isinstance(t, APEv2):
        for k, v in changes.items():
            key = APE[k]
            old = str(t[key]) if key in t else ""
            value = _numbered(v, old) if k in ("track_no", "disc_no") else _text(v)
            if value:
                t[key] = value
            elif key in t:
                del t[key]
        audio.save()
    else:
        raise TagError(f"{path}: {type(t).__name__} tags aren't supported")


def embed_cover(path: str, jpeg: bytes):
    """Makes `jpeg` the file's front cover, replacing the one it had."""
    audio = mutagen.File(path)
    if audio is None:
        raise TagError(f"{path}: not a file a cover can go into")
    if audio.tags is None:
        audio.add_tags()
    t = audio.tags
    if isinstance(t, ID3):
        t.delall("APIC")
        t.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=jpeg))
        _save_id3(audio, path)
    elif isinstance(audio, MP4):
        t["covr"] = [MP4Cover(jpeg, imageformat=MP4Cover.FORMAT_JPEG)]
        audio.save()
    elif isinstance(audio, FLAC):
        audio.clear_pictures()
        audio.add_picture(_picture(jpeg))
        audio.save()
    elif isinstance(audio, OggFileType):
        t["METADATA_BLOCK_PICTURE"] = [base64.b64encode(_picture(jpeg).write()).decode("ascii")]
        audio.save()
    elif isinstance(t, APEv2):
        t["Cover Art (Front)"] = APEValue(b"cover.jpg\x00" + jpeg, BINARY)
        audio.save()
    else:
        raise TagError(f"{path}: a cover can't be embedded in {type(audio).__name__}")


def _save_id3(audio, path: str):
    if formats.ext_of(path) == "mp3":
        audio.save(v2_version=4)
    else:
        audio.save()        # ID3 inside AIFF, WAV and DSF files


def _picture(jpeg: bytes) -> Picture:
    pic = Picture()
    pic.type, pic.mime, pic.desc, pic.data = 3, "image/jpeg", "Cover", jpeg
    return pic

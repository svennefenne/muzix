"""Writing an admin's metadata edits into audio files, and a cover into them.

`write(path, changes)` sets the given fields (title, artist, albumartist, album, track_no,
disc_no, year, genre); an empty value removes the tag. Track and disc totals already in the file
("3/12") are kept. Chip and tracker formats have no tags to write: `writable()` says no, and
their edits are kept in the database instead (TagOverride).

`snapshot(path, fields)` keeps the tags behind those fields exactly as the file has them (absent
ones too), and `put_back(path, snap)` restores them: what undoing an edit needs. `pictures(path)`
and `put_pictures(path, snap)` do the same for the embedded pictures a new cover replaces.
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

ID3_KEYS = {"title": "TIT2", "artist": "TPE1", "albumartist": "TPE2", "album": "TALB", "track_no": "TRCK",
            "disc_no": "TPOS", "year": "TDRC", "genre": "TCON"}
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


def _open(path: str):
    try:
        audio = mutagen.File(path)
    except Exception as e:
        raise TagError(f"{path}: {e}") from e
    if audio is None:
        raise TagError(f"{path}: not a file whose tags can be written")
    return audio


def _kind(audio) -> tuple[str, dict]:
    """Which tag system the file uses, and its keys for FIELDS."""
    t = audio.tags
    if isinstance(t, ID3):
        return "id3", ID3_KEYS
    if isinstance(audio, MP4):
        return "mp4", {**MP4_KEYS, "track_no": "trkn", "disc_no": "disk"}
    if isinstance(audio, ASF):
        return "asf", ASF_KEYS
    if isinstance(audio, (FLAC, OggFileType)):
        return "vorbis", VORBIS
    if isinstance(t, APEv2):
        return "ape", APE
    raise TagError(f"{type(t).__name__} tags aren't supported")


def snapshot(path: str, fields) -> dict:
    """{"kind": tag system, "keys": {key: [values] or None}} for the tags behind `fields`."""
    audio = _open(path)
    if audio.tags is None:
        audio.add_tags()        # not saved: only to know which tags an edit will give it
    kind, keys = _kind(audio)
    t, out = audio.tags, {}
    for f in fields:
        if f not in keys:
            continue
        key = keys[f]
        if kind == "ape":       # APE keys ignore case: keep the file's own spelling
            key = next((k for k in t.keys() if k.lower() == key.lower()), key)
        if key not in t:
            out[key] = None
        elif kind == "id3":
            out[key] = [str(x) for x in t[key].text]
        elif kind == "mp4" and key in ("trkn", "disk"):
            out[key] = [list(x) for x in t[key]]
        elif kind == "ape":
            out[key] = [str(t[key])]
        else:
            out[key] = [str(x) for x in t[key]]
    return {"kind": kind, "keys": out}


def put_back(path: str, snap: dict):
    """The tags of a `snapshot`, back as they were."""
    audio = _open(path)
    if audio.tags is None:
        audio.add_tags()
    kind, _ = _kind(audio)
    if snap["kind"] != kind:
        raise TagError(f"{path}: its tags are {kind} now, not {snap['kind']}")
    t = audio.tags
    for key, values in snap["keys"].items():
        if snap["kind"] == "id3":
            t.delall(key)
            if values:
                frame = {"TRCK": TRCK, "TPOS": TPOS}.get(key) or next(c for c in ID3_FRAMES.values() if c.__name__ == key)
                t.add(frame(encoding=3, text=values))
        elif values is None:
            if key in t:
                del t[key]
        elif snap["kind"] == "mp4" and key in ("trkn", "disk"):
            t[key] = [tuple(v) for v in values]
        elif snap["kind"] == "ape":
            if key in t:
                del t[key]      # whatever its case now, then with the case it had
            t[key] = values[0]
        else:
            t[key] = values
    if snap["kind"] == "id3":
        _save_id3(audio, path)
    else:
        audio.save()


def _picture_kind(audio) -> str:
    return "flac" if isinstance(audio, FLAC) else _kind(audio)[0]


def pictures(path: str) -> dict:
    """The file's embedded pictures as they are, for `put_pictures`: {"kind", "items"}."""
    audio = _open(path)
    if audio.tags is None and not isinstance(audio, FLAC):
        return {"kind": "none", "items": []}
    kind, t = _picture_kind(audio), audio.tags
    enc = lambda b: base64.b64encode(bytes(b)).decode("ascii")
    if kind == "id3":
        items = [{"mime": f.mime, "type": int(f.type), "desc": f.desc, "data": enc(f.data)} for f in t.getall("APIC")]
    elif kind == "mp4":
        items = [{"format": int(c.imageformat), "data": enc(c)} for c in t.get("covr", [])]
    elif kind == "flac":
        items = [{"block": enc(p.write())} for p in audio.pictures]
    elif kind == "vorbis":
        items = [{"text": v} for v in t.get("METADATA_BLOCK_PICTURE", [])]
    elif kind == "ape":
        items = [{"key": k, "data": enc(t[k].value)} for k in t.keys() if k.lower().startswith("cover art")]
    else:
        items = []      # a cover isn't embedded in these
    return {"kind": kind, "items": items}


def put_pictures(path: str, snap: dict):
    """The embedded pictures of a `pictures` snapshot back, instead of whatever is there now."""
    audio = _open(path)
    if audio.tags is None and not isinstance(audio, FLAC):
        if not snap["items"]:
            return
        audio.add_tags()
    kind, t, items = _picture_kind(audio), audio.tags, snap["items"]
    if snap["kind"] not in (kind, "none"):
        raise TagError(f"{path}: its tags are {kind} now, not {snap['kind']}")
    if kind == "id3":
        t.delall("APIC")
        for i in items:
            t.add(APIC(encoding=3, mime=i["mime"], type=i["type"], desc=i["desc"], data=base64.b64decode(i["data"])))
        _save_id3(audio, path)
        return
    if kind == "mp4":
        if items:
            t["covr"] = [MP4Cover(base64.b64decode(i["data"]), imageformat=i["format"]) for i in items]
        else:
            t.pop("covr", None)
    elif kind == "flac":
        audio.clear_pictures()
        for i in items:
            audio.add_picture(Picture(base64.b64decode(i["block"])))
    elif kind == "vorbis":
        if items:
            t["METADATA_BLOCK_PICTURE"] = [i["text"] for i in items]
        elif "METADATA_BLOCK_PICTURE" in t:
            del t["METADATA_BLOCK_PICTURE"]
    elif kind == "ape":
        for k in [k for k in t.keys() if k.lower().startswith("cover art")]:
            del t[k]
        for i in items:
            t[i["key"]] = APEValue(base64.b64decode(i["data"]), BINARY)
    else:
        return
    audio.save()


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

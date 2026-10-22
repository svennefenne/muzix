"""Tags of regular audio files (MP3, FLAC, Ogg, MP4/M4B, WavPack, APE, WMA...)."""

from dataclasses import dataclass, field

import mediafile

from . import wavpack_patch  # noqa: F401  (patches mutagen on import)


@dataclass
class AudioInfo:
    title: str = ""
    artist: str = ""
    albumartist: str = ""
    album: str = ""
    track_no: int = 0
    disc_no: int = 0
    year: int = 0
    genre: str = ""
    duration: float = 0
    bitrate: int = 0
    sample_rate: int = 0
    bit_depth: int = 0
    channels: int = 0
    codec: str = ""
    embedded_art: bool = False
    compilation: bool = False
    mbid: str = ""
    album_mbid: str = ""
    artist_mbid: str = ""
    albumartist_mbid: str = ""
    chapters: list = field(default_factory=list)   # m4b: [{title, start}]
    extra: dict = field(default_factory=dict)


def _s(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        v = v[0] if v else ""
    return str(v).strip()


def read(path: str) -> AudioInfo:
    f = mediafile.MediaFile(path)
    info = AudioInfo(
        title=_s(f.title), artist=_s(f.artist), albumartist=_s(f.albumartist), album=_s(f.album),
        track_no=f.track or 0, disc_no=f.disc or 0, year=f.original_year or f.year or 0,
        genre=_s(f.genres[0] if f.genres else f.genre), duration=f.length or 0,
        bitrate=f.bitrate or 0, sample_rate=f.samplerate or 0, bit_depth=f.bitdepth or 0,
        channels=f.channels or 0, codec=(f.type or "").lower(),
        compilation=bool(f.comp), mbid=_s(f.mb_trackid), album_mbid=_s(f.mb_albumid),
        artist_mbid=_s(f.mb_artistid), albumartist_mbid=_s(f.mb_albumartistid),
    )
    try:
        info.embedded_art = bool(f.images)
    except Exception:  # broken picture frames shouldn't hide the track
        info.embedded_art = False
    if info.codec in ("aac", "alac", "mp4") or path.lower().endswith((".m4b", ".m4a")):
        info.chapters = mp4_chapters(f.mgfile)
        if hasattr(f.mgfile, "info") and getattr(f.mgfile.info, "codec", ""):
            info.codec = f.mgfile.info.codec.split(".")[0].lower()   # "mp4a" | "alac"
    if f.mgfile is not None and f.mgfile.tags is not None:
        for key in ("©nrt", "©wrt"):   # narrator / composer in audiobooks
            try:
                if key in f.mgfile.tags:
                    info.extra["narrator"] = _s(f.mgfile.tags[key])
            except (TypeError, ValueError):
                pass
    return info


def mp4_chapters(mg) -> list:
    try:
        chapters = mg.chapters
    except AttributeError:
        return []
    if not chapters:
        return []
    return [{"title": c.title or f"Chapter {i + 1}", "start": float(c.start)}
            for i, c in enumerate(chapters)]


def picture(path: str) -> bytes | None:
    """The front cover (or first image) embedded in a file."""
    try:
        f = mediafile.MediaFile(path)
        images = f.images or []
    except Exception:
        return None
    if not images:
        return None
    for img in images:
        if getattr(img, "type", None) == mediafile.ImageType.front:
            return img.data
    return images[0].data

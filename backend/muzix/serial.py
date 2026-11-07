"""JSON shapes of library objects, shared by the API routes."""

import time
from datetime import datetime, timezone

from sqlalchemy import select

from . import art, db, formats, render
from .lengths import display_duration
from .models import Album, Artist, Peer, Track

_peers: tuple[float, dict[int, str]] = (0.0, {})


def iso(when: datetime | None) -> str | None:
    """A time for the page. SQLite gives times back without their zone; they're UTC."""
    if when is None:
        return None
    return (when if when.tzinfo else when.replace(tzinfo=timezone.utc)).isoformat()


def peer(peer_id: int | None) -> str | None:
    """The name of the server in the Library Network something is from (None: this one's)."""
    global _peers
    if peer_id is None:
        return None
    at, names = _peers
    if peer_id not in names or time.time() - at > 30:
        with db.session() as s:
            names = dict(s.execute(select(Peer.id, Peer.name)).all())
        _peers = (time.time(), names)
    return names.get(peer_id) or "another server"


def art_url(kind: str, id_: int | None) -> str | None:
    return art.url(kind, id_) if id_ else None


def track(t: Track, liked: set[int] | None = None, artist_tags: dict | None = None) -> dict:
    ext = t.format
    extra = t.extra or {}
    return {
        "id": t.id, "title": t.title, "artist": t.artist, "albumartist": t.albumartist,
        "album": t.album, "album_id": t.album_id, "artist_id": t.artist_id,
        "track_no": t.track_no, "disc_no": t.disc_no, "year": t.year, "genre": t.genre,
        "duration": display_duration(t), "format": ext, "kind": t.kind,
        "family": formats.family(ext), "subsong": t.subsong,
        "sample_rate": t.sample_rate, "bit_depth": t.bit_depth, "bitrate": t.bitrate,
        # a Cast speaker gets the file itself (and seeks in it) rather than a converted stream
        "cast_native": not render.needs_transcode(ext, t.codec, t.sample_rate, "cast"),
        "system": (extra.get("system") or formats.system_for(ext)) if t.kind == "vgm" else "",
        "art": art_url("album", t.album_id),
        "stream": f"/api/stream/{t.id}",
        "liked": bool(liked and t.id in liked),
        "tags": (artist_tags or {}).get(t.artist_id, []),
        "peer": peer(t.peer_id),
    }


def album(a: Album, liked: set[int] | None = None) -> dict:
    return {
        "id": a.id, "title": a.title, "artist": a.artist_name, "artist_id": a.artist_id,
        "year": a.year, "genre": a.genre, "kind": a.kind, "track_count": a.track_count,
        "duration": a.duration, "formats": a.formats.split(",") if a.formats else [],
        "art": art_url("album", a.id) if a.art else None,
        "added_at": iso(a.added_at),
        "liked": bool(liked and a.id in liked),
        "peer": peer(a.peer_id),
    }


def artist(a: Artist, liked: set[int] | None = None, album_count: int | None = None) -> dict:
    return {
        "id": a.id, "name": a.name, "genre": a.genre,
        "tags": [t[0] for t in (a.tags or [])[:8]],
        "art": art_url("artist", a.id),
        "album_count": album_count,
        "liked": bool(liked and a.id in liked),
    }

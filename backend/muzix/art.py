"""Cover art: found next to the music or embedded in it, resized once and cached."""

import hashlib
import io
import os
import threading

from PIL import Image, ImageOps
from sqlalchemy import select

from . import db, env
from .meta import tags
from .models import Album, Artist, ArtVersion

SIZES = (64, 160, 300, 600, 1200)
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def _lock(key: str) -> threading.Lock:
    with _guard:
        return _locks.setdefault(key, threading.Lock())


def pick_size(want: int) -> int:
    for s in SIZES:
        if want <= s:
            return s
    return SIZES[-1]


def source_bytes(ref: str, track_path_of=None) -> tuple[bytes | None, str]:
    """(image bytes, cache identity) for an album art reference."""
    if not ref:
        return None, ""
    if ref.startswith("embedded:"):
        if track_path_of is None:
            return None, ""
        path = track_path_of(int(ref.split(":", 1)[1]))
        if not path:
            return None, ""
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None, ""
        return tags.picture(path), f"{path}:{mtime}"
    try:
        with open(ref, "rb") as f:
            data = f.read()
        return data, f"{ref}:{os.path.getmtime(ref)}"
    except OSError:
        return None, ""


def resized(data: bytes, ident: str, size: int) -> str | None:
    """Path of a cached WebP rendition of `data` at `size` px (longest side)."""
    size = pick_size(size)
    key = hashlib.sha1(f"{ident}|{size}".encode()).hexdigest()
    out = env.ART_DIR / key[:2] / f"{key}.webp"
    if out.exists():
        return str(out)
    with _lock(key):
        if out.exists():
            return str(out)
        try:
            img = Image.open(io.BytesIO(data))
            img = ImageOps.exif_transpose(img)
            img.thumbnail((size, size), Image.LANCZOS)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".tmp")
            img.save(tmp, "WEBP", quality=85, method=4)
            os.replace(tmp, out)
        except Exception:
            return None
    return str(out)


def dominant_colors(path: str, n: int = 3) -> list[str]:
    """A few representative colours of an image (for tinting the UI)."""
    try:
        img = Image.open(path).convert("RGB")
    except Exception:
        return []
    img.thumbnail((64, 64))
    pal = img.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    counts = sorted(pal.getcolors() or [], reverse=True)
    rgb = pal.getpalette() or []
    out = []
    for _, idx in counts[:n]:
        r, g, b = rgb[idx * 3:idx * 3 + 3]
        out.append(f"#{r:02x}{g:02x}{b:02x}")
    return out


# ---------------------------------------------------------------- addresses
# Browsers keep a picture for a week, so one that changes gets a new address: its version goes
# up. Every picture starts at version 1; only the ones that changed are in the table.

_versions: dict[tuple[str, int], int] | None = None
_versions_lock = threading.Lock()


def _known() -> dict[tuple[str, int], int]:
    global _versions
    with _versions_lock:
        if _versions is None:
            with db.session() as s:
                _versions = {(v.kind, v.item_id): v.version for v in s.scalars(select(ArtVersion))}
        return _versions


def url(kind: str, id_: int) -> str:
    return f"/api/art/{kind}/{id_}?v={_known().get((kind, id_), 1)}"


def changed(kind: str, *ids: int | None) -> None:
    """New addresses for pictures that changed. Call it once the change is committed: a browser
    that asks for the new address straight away must get the new picture. An artist without a
    picture of its own shows one of its albums' covers, so it changes with them."""
    ids = {i for i in ids if i}
    if not ids:
        return
    with db.session() as s:
        rows = {v.item_id: v for v in s.scalars(select(ArtVersion).where(ArtVersion.kind == kind, ArtVersion.item_id.in_(ids)))}
        for i in ids:
            if i not in rows:
                rows[i] = ArtVersion(kind=kind, item_id=i, version=1)
                s.add(rows[i])
            rows[i].version += 1
        now = {(kind, i): v.version for i, v in rows.items()}
        artists = s.scalars(select(Album.artist_id).join(Artist, Artist.id == Album.artist_id)
                            .where(Album.id.in_(ids), Artist.image == "")).all() if kind == "album" else []
    _known().update(now)
    changed("artist", *artists)

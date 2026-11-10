"""Colour schemes of the users' own, as in Hooden: made from one of the schemes, with their colours for
dark and light, fonts, corners, glass, the frame, the backdrop and a picture of their own. They're the
account's, on every device (which one a device uses is its own setting, "custom:<id>" in its prefs), and
a shared one is there for everyone on the server to use, or copy and change.

What's kept is checked here: it's drawn on other people's devices, so only colours, the app's own names
for fonts and decorations, numbers in their ranges and pictures uploaded here."""

import hashlib
import io
import os
import time
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import env, serial
from ..db import get_db_with_copies
from ..models import AuthSession, Scheme, User, now
from ..security import current_user

router = APIRouter(prefix="/api/schemes", tags=["schemes"])

HEX = r"^#[0-9a-fA-F]{6}$"
NAME = r"^[a-z0-9-]{0,40}$"
PICTURE = r"^(/api/schemes/pictures/[0-9a-f]{24}\.webp)?$"
MAX_PICTURE = 16 * 1024 * 1024
PICTURE_SIDE = 2560


class Colors(BaseModel):
    bg: str = Field(pattern=HEX)
    surface: str = Field(pattern=HEX)
    text: str = Field(pattern=HEX)
    primary: str = Field(pattern=HEX)
    secondary: str = Field(pattern=HEX)
    error: str = Field(pattern=HEX)
    warning: str = Field(pattern=HEX)
    success: str = Field(pattern=HEX)
    border: str = Field(pattern=HEX)


class Picture(BaseModel):
    desktop: str = Field("", pattern=PICTURE)     # the computer's and tablet's
    mobile: str = Field("", pattern=PICTURE)      # a phone's own (tall), if it has one
    dim: int = Field(35, ge=0, le=90)             # darkened, in %
    blur: int = Field(0, ge=0, le=20)             # px
    size: Literal["cover", "contain", "tile"] = "cover"


class SchemeData(BaseModel):
    base: str = Field("muzix", pattern=NAME)       # the scheme it was made from
    modes: Literal["both", "dark", "light"] = "both"
    dark: Colors
    light: Colors
    display: str = Field("", pattern=NAME)         # the titles' font ("": the house's)
    ui: str = Field("", pattern=NAME)              # everything else's
    caps: bool = True                              # titles in capitals
    headline: str = Field("none", pattern=NAME)    # a genre skin's lettering for the titles
    radius: int = Field(10, ge=0, le=28)
    glass: int = Field(42, ge=0, le=100)           # how solid the frame is, in %
    frame: str = Field("plain", pattern=NAME)
    backdrop: str = Field("space", pattern=NAME)
    picture: Picture = Picture()


class SchemeBody(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    data: SchemeData
    shared: bool = False


def _uses(db: Session) -> dict[str, int]:
    """How many devices use each scheme now."""
    out: dict[str, int] = {}
    for prefs in db.scalars(select(AuthSession.prefs).where(AuthSession.prefs.is_not(None))):
        s = (prefs or {}).get("scheme")
        if isinstance(s, str) and s.startswith("custom:"):
            out[s] = out.get(s, 0) + 1
    return out


def scheme_json(s: Scheme, user: User, uses: dict[str, int]) -> dict:
    return {"id": s.id, "name": s.name, "data": s.data, "shared": s.shared, "mine": s.user_id == user.id,
            "owner": {"id": s.user_id, "name": s.user.username if s.user else ""},
            "uses": uses.get(f"custom:{s.id}", 0), "updated_at": serial.iso(s.updated_at)}


def _mine(db: Session, user: User, sid: int) -> Scheme:
    s = db.get(Scheme, sid)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "No such scheme of yours")
    return s


def _tidy_pictures(db: Session):
    """Pictures no scheme has any more go (a day after they came, so one being made keeps its own)."""
    kept = set()
    for data in db.scalars(select(Scheme.data)):
        pic = (data or {}).get("picture") or {}
        kept |= {os.path.basename(pic.get(k) or "") for k in ("desktop", "mobile")}
    for f in env.SCHEME_DIR.glob("*.webp"):
        if f.name not in kept and time.time() - f.stat().st_mtime > 86400:
            f.unlink(missing_ok=True)


@router.get("")
def schemes(db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    """Your own, and the ones others share."""
    uses = _uses(db)
    rows = db.scalars(select(Scheme).where((Scheme.user_id == user.id) | Scheme.shared).order_by(Scheme.name)).all()
    return {"mine": [scheme_json(s, user, uses) for s in rows if s.user_id == user.id],
            "shared": [scheme_json(s, user, uses) for s in rows if s.user_id != user.id]}


@router.get("/{sid}")
def scheme(sid: int, db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    s = db.get(Scheme, sid)
    if s is None or (s.user_id != user.id and not s.shared):
        raise HTTPException(404, "No such scheme")
    return scheme_json(s, user, _uses(db))


@router.post("")
def create(body: SchemeBody, db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    s = Scheme(user_id=user.id, name=body.name.strip(), data=body.data.model_dump(), shared=body.shared)
    db.add(s)
    db.commit()
    return scheme_json(s, user, _uses(db))


@router.put("/{sid}")
def update(sid: int, body: SchemeBody, db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    s = _mine(db, user, sid)
    s.name, s.data, s.shared, s.updated_at = body.name.strip(), body.data.model_dump(), body.shared, now()
    db.commit()
    _tidy_pictures(db)
    return scheme_json(s, user, _uses(db))


@router.delete("/{sid}")
def delete(sid: int, db: Session = Depends(get_db_with_copies), user: User = Depends(current_user)):
    db.delete(_mine(db, user, sid))
    db.commit()
    _tidy_pictures(db)
    return {"ok": True}


# ---------------------------------------------------------------- pictures

@router.post("/pictures")
async def upload_picture(file: UploadFile = File(...), user: User = Depends(current_user)):
    """A picture for a scheme: made a WebP at most 2560 px on a side, kept by its contents."""
    data = await file.read(MAX_PICTURE + 1)
    if len(data) > MAX_PICTURE:
        raise HTTPException(413, "That picture is too big (16 MB at most)")
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        img.thumbnail((PICTURE_SIDE, PICTURE_SIDE), Image.LANCZOS)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        out = io.BytesIO()
        img.save(out, "WEBP", quality=84, method=4)
    except Exception:
        raise HTTPException(400, "That isn't a picture Muzix can read")
    name = hashlib.sha256(out.getvalue()).hexdigest()[:24] + ".webp"
    path = env.SCHEME_DIR / name
    if not path.exists():
        env.SCHEME_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(out.getvalue())
        os.replace(tmp, path)
    return {"url": f"/api/schemes/pictures/{name}"}


@router.get("/pictures/{name}")
def picture(name: str, user: User = Depends(current_user)):
    path = env.SCHEME_DIR / os.path.basename(name)
    if not name.endswith(".webp") or not path.is_file():
        raise HTTPException(404, "No such picture")
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "private, max-age=31536000, immutable"})

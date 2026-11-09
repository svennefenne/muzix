"""The setup a new server goes through once its admin account exists: the library's folders,
the modules it runs (modules.py) and their settings, and what it's called and where it's
reached. Until it's done or skipped, the admin sees it instead of Muzix."""

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import db as database, env, jobs, modules, network, settings
from ..db import get_db
from ..models import Root, Setting
from ..security import admin_user

router = APIRouter(prefix="/api/setup", tags=["setup"], dependencies=[Depends(admin_user)])

PENDING = "setup_pending"
GENERAL = ("site_name", "public_url", "allow_signup")
# for the music: where genres, pictures and lyrics come from (the setup's optional part)
METADATA = ("artist_tags", "lastfm_api_key", "discogs_token", "fanarttv_api_key", "brave_api_key", "lyrics_online")
SKIP = ("Other formats", "Duplicates")     # the library's own side folders (mp3 reorg), not scanned


def pending() -> bool:
    with database.session() as s:
        return s.get(Setting, PENDING) is not None


def begin():
    """The admin account is made: the setup comes next."""
    with database.session() as s:
        s.merge(Setting(key=PENDING, value=True))


def _done():
    with database.session() as s:
        row = s.get(Setting, PENDING)
        if row is not None:
            s.delete(row)


def mounted() -> list[dict]:
    """The folders the container mounts for the library (MUZIX_DEFAULT_ROOTS) that are there."""
    out = []
    for item in env.DEFAULT_ROOTS.split(","):
        if ":" not in item:
            continue
        path, kind = item.rsplit(":", 1)
        path = path.rstrip("/") or "/"
        if os.path.isdir(path):
            out.append({"path": path, "kind": kind})
    return out


def add_root(db: Session, path: str, kind: str):
    """A library folder, unless it's one already; uploaded music goes to the first music folder."""
    path = os.path.normpath(path)
    if db.scalar(select(Root.id).where(Root.path == path)):
        return
    target = kind == "music" and db.scalar(select(Root.id).where(Root.kind == kind, Root.upload_target.is_(True))) is None
    db.add(Root(path=path, kind=kind, name=os.path.basename(path) or path,
                excludes=[d for d in SKIP if os.path.isdir(os.path.join(path, d))], upload_target=target))
    db.flush()


def add_default_roots(db: Session):
    """Register the folders the container mounts, if they exist and aren't known yet."""
    for f in mounted():
        add_root(db, f["path"], f["kind"])
    db.commit()


@router.get("")
def setup_info(db: Session = Depends(get_db)):
    """What the setup asks, with what it suggests: the mounted folders, and the modules whose
    folders are there (and those that need nothing set up elsewhere)."""
    folders = mounted()
    known = [{"path": r.path, "kind": r.kind} for r in db.scalars(select(Root).where(Root.kind != "peer"))]
    have = {f["kind"] for f in folders + known}
    suggest = {"vgm": "vgm" in have, "audiobooks": "audiobooks" in have, "podcasts": True, "radio": True, "network": False}
    return {
        "pending": pending(),
        "folders": folders + [f for f in known if f["path"] not in {x["path"] for x in folders}],
        "modules": [{"key": m.key, "label": m.label, "about": m.about, "kinds": list(m.kinds),
                     "suggested": suggest[m.key],
                     "settings": [settings.public(settings.spec(k)) for k in m.settings],
                     "more": [settings.public(settings.spec(k)) for k in m.more]} for m in modules.MODULES],
        "general": [settings.public(settings.spec(k)) for k in GENERAL],
        "metadata": [settings.public(settings.spec(k)) for k in METADATA],
    }


class Folder(BaseModel):
    path: str = Field(min_length=1)
    kind: str = Field(pattern="^(music|vgm|audiobooks)$")


class Finish(BaseModel):
    folders: list[Folder] = []
    modules: dict[str, bool] = {}
    settings: dict[str, object] = {}
    share: bool = False                  # the Library Network open for links right away


@router.post("/finish")
def finish(body: Finish, db: Session = Depends(get_db)):
    if not pending():
        raise HTTPException(409, "Muzix is already set up")
    allowed = {*GENERAL, *METADATA, *modules.OWNER}
    unknown = [k for k in body.settings if k not in allowed] + [k for k in body.modules if k not in modules.BY_KEY]
    if unknown:
        raise HTTPException(400, f"Unknown setting {unknown[0]}")
    missing = [f.path for f in body.folders if not os.path.isdir(os.path.normpath(f.path))]
    if missing:
        raise HTTPException(400, f"{missing[0]} is not a folder inside the container")
    values = {k: v for k, v in body.settings.items() if not (settings.spec(k).type == "secret" and v == "••••••")}
    values.update({modules.setting(k): on for k, on in body.modules.items()})
    try:
        settings.set_many(values)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    for f in body.folders:
        add_root(db, f.path, f.kind)
    db.commit()
    if body.share and modules.on("network") and network.code() is None:
        network.new_code()
    _done()
    jobs.submit("scan", "First library scan")
    return {"code": network.code() if modules.on("network") else None}


@router.post("/skip")
def skip(db: Session = Depends(get_db)):
    """Everything as it comes: the mounted folders, every module on."""
    if not pending():
        raise HTTPException(409, "Muzix is already set up")
    add_default_roots(db)
    _done()
    jobs.submit("scan", "First library scan")
    return {"ok": True}

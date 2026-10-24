import os
import shutil

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import __version__, env, jobs, render, settings
from ..db import get_db
from ..meta import gme, openmpt
from ..models import Album, Artist, Book, Feed, Job, Root, Track, User
from ..security import admin_user, hash_password

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(admin_user)])


# ---------------------------------------------------------------- settings

@router.get("/settings")
def get_settings():
    return settings.public_schema()


@router.put("/settings")
def put_settings(values: dict):
    clean = {}
    for k, v in values.items():
        spec = next((s for s in settings.SCHEMA if s.key == k), None)
        if spec is None:
            raise HTTPException(400, f"Unknown setting {k}")
        if spec.type == "secret" and v == "••••••":
            continue   # unchanged
        clean[k] = v
    try:
        settings.set_many(clean)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    return settings.public_schema()


# ---------------------------------------------------------------- library folders

class RootBody(BaseModel):
    path: str = Field(min_length=1)
    kind: str = Field(pattern="^(music|vgm|audiobooks)$")
    name: str = ""
    enabled: bool = True
    upload_target: bool = False
    excludes: list[str] = []


def root_json(r: Root, db: Session):
    if r.kind == "audiobooks":
        count = db.scalar(select(func.count()).select_from(Book).where(Book.root_id == r.id))
    else:
        count = db.scalar(select(func.count()).select_from(Track).where(Track.root_id == r.id))
    return {"id": r.id, "path": r.path, "kind": r.kind, "name": r.name, "enabled": r.enabled,
            "upload_target": r.upload_target, "excludes": r.excludes or [], "items": count,
            "exists": os.path.isdir(r.path), "last_scan": r.last_scan.isoformat() if r.last_scan else None,
            "writable": os.access(r.path, os.W_OK)}


@router.get("/roots")
def roots(db: Session = Depends(get_db)):
    return [root_json(r, db) for r in db.scalars(select(Root).order_by(Root.kind, Root.path))]


@router.post("/roots")
def add_root(body: RootBody, db: Session = Depends(get_db)):
    path = os.path.normpath(body.path)
    if not os.path.isdir(path):
        raise HTTPException(400, f"{path} is not a folder inside the container")
    if db.scalar(select(Root.id).where(Root.path == path)):
        raise HTTPException(409, "That folder is already in the library")
    r = Root(**{**body.model_dump(), "path": path, "name": body.name or os.path.basename(path)})
    if r.upload_target:
        _clear_upload_target(db, r.kind)
    db.add(r)
    db.commit()
    jobs.submit("scan" if r.kind != "audiobooks" else "scan_books", f"Scan {r.name}")
    return root_json(r, db)


def _clear_upload_target(db, kind):
    for other in db.scalars(select(Root).where(Root.kind == kind, Root.upload_target.is_(True))):
        other.upload_target = False


@router.put("/roots/{root_id}")
def edit_root(root_id: int, body: RootBody, db: Session = Depends(get_db)):
    r = db.get(Root, root_id)
    if r is None:
        raise HTTPException(404, "No such folder")
    if body.upload_target and not r.upload_target:
        _clear_upload_target(db, body.kind)
    for k in ("kind", "name", "enabled", "upload_target", "excludes"):
        setattr(r, k, getattr(body, k))
    db.commit()
    return root_json(r, db)


@router.delete("/roots/{root_id}")
def delete_root(root_id: int, db: Session = Depends(get_db)):
    r = db.get(Root, root_id)
    if r is None:
        raise HTTPException(404, "No such folder")
    db.delete(r)   # its tracks go with it (files on disk are untouched)
    db.commit()
    jobs.submit("cleanup", "Tidy the library")
    return {"ok": True}


@router.get("/browse")
def browse(path: str = "/"):
    """Folder picker for adding library folders."""
    path = os.path.normpath(path or "/")
    try:
        dirs = sorted(e.name for e in os.scandir(path) if e.is_dir() and not e.name.startswith("."))
    except OSError as e:
        raise HTTPException(400, str(e))
    return {"path": path, "parent": os.path.dirname(path) if path != "/" else None, "folders": dirs[:500]}


# ---------------------------------------------------------------- jobs

class ScanBody(BaseModel):
    root_id: int | None = None
    full: bool = False


@router.post("/scan")
def scan(body: ScanBody):
    return {"job_id": jobs.submit("scan", "Library scan", root_id=body.root_id, full=body.full)}


@router.post("/jobs/{type_}")
def start_job(type_: str):
    allowed = {"scan_books": "Scan audiobooks", "artist_tags": "Fetch artist genres",
               "refresh_feeds": "Refresh podcasts", "cleanup": "Tidy the library"}
    if type_ not in allowed:
        raise HTTPException(400, "Unknown job")
    return {"job_id": jobs.submit(type_, allowed[type_])}


def job_json(j: Job, with_log=False):
    out = {"id": j.id, "type": j.type, "title": j.title, "status": j.status, "progress": j.progress,
           "message": j.message, "result": j.result,
           "created_at": j.created_at.isoformat() if j.created_at else None,
           "started_at": j.started_at.isoformat() if j.started_at else None,
           "finished_at": j.finished_at.isoformat() if j.finished_at else None}
    if with_log:
        out["log"] = j.log
    return out


@router.get("/jobs")
def list_jobs(limit: int = 50, db: Session = Depends(get_db)):
    return [job_json(j) for j in db.scalars(select(Job).order_by(Job.id.desc()).limit(limit))]


@router.get("/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if j is None:
        raise HTTPException(404, "No such job")
    return job_json(j, True)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int):
    jobs.cancel(job_id)
    return {"ok": True}


# ---------------------------------------------------------------- users

class UserBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str | None = Field(default=None, min_length=6, max_length=256)
    is_admin: bool = False


@router.get("/users")
def users(db: Session = Depends(get_db)):
    return [{"id": u.id, "username": u.username, "is_admin": u.is_admin,
             "created_at": u.created_at.isoformat()} for u in db.scalars(select(User).order_by(User.id))]


@router.post("/users")
def add_user(body: UserBody, db: Session = Depends(get_db)):
    if not body.password:
        raise HTTPException(400, "A new user needs a password")
    if db.scalar(select(User.id).where(func.casefold(User.username) == body.username.casefold())):
        raise HTTPException(409, "That username is taken")
    u = User(username=body.username, password_hash=hash_password(body.password), is_admin=body.is_admin)
    db.add(u)
    db.commit()
    return {"id": u.id}


@router.put("/users/{user_id}")
def edit_user(user_id: int, body: UserBody, db: Session = Depends(get_db), me: User = Depends(admin_user)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "No such user")
    if u.id == me.id and not body.is_admin:
        raise HTTPException(400, "You can't remove your own admin rights")
    u.username, u.is_admin = body.username, body.is_admin
    if body.password:
        u.password_hash = hash_password(body.password)
    db.commit()
    return {"ok": True}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), me: User = Depends(admin_user)):
    if user_id == me.id:
        raise HTTPException(400, "You can't delete yourself")
    u = db.get(User, user_id)
    if u is not None:
        db.delete(u)
        db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- status

def _dir_size(path) -> int:
    total = 0
    for r, _, fs in os.walk(path):
        for f in fs:
            try:
                total += os.path.getsize(os.path.join(r, f))
            except OSError:
                pass
    return total


@router.get("/status")
def status(db: Session = Depends(get_db)):
    tools = {name: render.have(name) for name in ("ffmpeg", "ffprobe", "sidplayfp", "fluidsynth", "ymtool", "furnace", "beet")}
    tools["libgme"] = gme.available()
    tools["libopenmpt"] = openmpt.available()
    count = lambda m, *w: db.scalar(select(func.count()).select_from(m).where(*w))
    disk = shutil.disk_usage(env.DATA_DIR)
    return {
        "version": __version__,
        "tools": tools,
        "counts": {"tracks": count(Track, Track.kind == "music"), "vgm": count(Track, Track.kind == "vgm"),
                   "albums": count(Album), "artists": count(Artist), "books": count(Book),
                   "feeds": count(Feed), "users": count(User)},
        "cache_bytes": _dir_size(env.CACHE_DIR),
        "art_bytes": _dir_size(env.ART_DIR),
        "data_dir": str(env.DATA_DIR),
        "data_free_bytes": disk.free,
    }


@router.post("/cache/clear")
def clear_cache(what: str = "render"):
    target = {"render": env.CACHE_DIR / "render", "art": env.ART_DIR}.get(what)
    if target is None:
        raise HTTPException(400, "Unknown cache")
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)
    return {"ok": True}

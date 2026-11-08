import os
import shutil
import threading
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import __version__, env, jobs, modules, network, render, serial, settings
from ..db import get_db, get_db_with_copies
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


# ---------------------------------------------------------------- modules

def module_json(m: modules.Module):
    return {"key": m.key, "label": m.label, "about": m.about, "kinds": list(m.kinds), "on": modules.on(m.key),
            "settings": [settings.public(settings.spec(k)) for k in (*m.settings, *m.more)]}


@router.get("/modules")
def module_list():
    return [module_json(m) for m in modules.MODULES]


class Turn(BaseModel):
    on: bool


@router.put("/modules/{key}")
def turn_module(key: str, body: Turn):
    """A module on or off. Turned on, it catches up on what it missed while it was off."""
    m = modules.BY_KEY.get(key)
    if m is None:
        raise HTTPException(404, "No such module")
    was = modules.on(key)
    settings.set_many({modules.setting(key): body.on})
    if body.on and not was:
        if key == "vgm":
            jobs.submit("scan", "Scan the library")
        elif key == "audiobooks":
            jobs.submit("scan_books", "Scan audiobooks")
        elif key == "podcasts":
            jobs.submit("refresh_feeds", "Refresh podcasts")
        elif key == "network" and network.linked():
            jobs.submit("network_sync", "Sync linked servers")
    return module_json(m)


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
            "exists": os.path.isdir(r.path), "last_scan": serial.iso(r.last_scan),
            "writable": os.access(r.path, os.W_OK)}


@router.get("/roots")
def roots(db: Session = Depends(get_db_with_copies)):
    # not the ones holding what other servers share (mirror.py)
    mine = select(Root).where(Root.kind != "peer").order_by(Root.kind, Root.path)
    return [root_json(r, db) for r in db.scalars(mine)]


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
           "created_at": serial.iso(j.created_at),
           "started_at": serial.iso(j.started_at),
           "finished_at": serial.iso(j.finished_at)}
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
             "created_at": serial.iso(u.created_at)} for u in db.scalars(select(User).order_by(User.id))]


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


# Adding up folder sizes can take half a minute on a busy Unraid user share, so the
# status page never waits for it: sizes are worked out in the background, at most
# every ten minutes, and the page shows the last known values.
_sizes = {"at": 0.0, "cache": None, "art": None}
_sizes_busy = threading.Lock()


def _refresh_sizes():
    try:
        _sizes.update(cache=_dir_size(env.CACHE_DIR), art=_dir_size(env.ART_DIR), at=time.time())
    finally:
        _sizes_busy.release()


def _folder_sizes(force=False):
    if (force or time.time() - _sizes["at"] > 600) and _sizes_busy.acquire(blocking=False):
        threading.Thread(target=_refresh_sizes, daemon=True, name="folder-sizes").start()
    return _sizes["cache"], _sizes["art"]


@router.get("/status")
def status(db: Session = Depends(get_db_with_copies)):
    tools = {name: render.have(name) for name in ("ffmpeg", "ffprobe", "sidplayfp", "fluidsynth", "ymtool", "furnace", "zxtune123", "uade123", "beet")}
    tools["libgme"] = gme.available()
    tools["libgme-sgc"] = gme.available("x.sgc")
    tools["libopenmpt"] = openmpt.available()
    count = lambda m, *w: db.scalar(select(func.count()).select_from(m).where(*w))
    bare = db.execute(select(func.count(), func.coalesce(func.sum(Album.track_count), 0)).where(*_without_art())).one()
    disk = shutil.disk_usage(env.DATA_DIR)
    cache_bytes, art_bytes = _folder_sizes()
    return {
        "version": __version__,
        "tools": tools,
        # this server's own library (not what it mirrors from the Library Network)
        "counts": {"tracks": count(Track, Track.kind == "music", Track.peer_id.is_(None)),
                   "vgm": count(Track, Track.kind == "vgm", Track.peer_id.is_(None)),
                   "albums": count(Album, Album.peer_id.is_(None)), "artists": count(Artist),
                   "books": count(Book, Book.peer_id.is_(None)),
                   "feeds": count(Feed), "users": count(User)},
        "without_art": {"albums": bare[0], "tracks": bare[1]},
        "cache_bytes": cache_bytes,       # None until the first background count is done
        "art_bytes": art_bytes,
        "data_dir": str(env.DATA_DIR),
        "data_free_bytes": disk.free,
    }


def _without_art():
    """This server's own music albums without a cover (none in their folder or their songs)."""
    return Album.kind == "music", Album.peer_id.is_(None), Album.art == ""


@router.get("/without-art")
def without_art(limit: int = 100, offset: int = 0, db: Session = Depends(get_db_with_copies)):
    """The albums without a cover, by artist and title, with their folder (to find them), a page at a time."""
    q = select(Album).where(*_without_art())
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(func.lower(Album.artist_name), func.lower(Album.title), Album.id)
                      .limit(max(1, min(limit, 500))).offset(offset))
    return {"total": total, "items": [{**serial.album(a), "folder": a.folder} for a in rows]}


@router.post("/cache/clear")
def clear_cache(what: str = "render"):
    target = {"render": env.CACHE_DIR / "render", "art": env.ART_DIR}.get(what)
    if target is None:
        raise HTTPException(400, "Unknown cache")
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)
    _folder_sizes(force=True)
    return {"ok": True}

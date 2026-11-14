"""Upload area on the admin page: files dropped or picked in the browser land in
/config/uploads/<batch>/ (folder structure kept) and are imported on request. A folder in it can be marked an
own compilation first (organize/compilation.py): its songs filed as one album by Various Artists."""

import json
import os
import re
import shutil
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import env, formats, jobs, settings
from ..db import get_db
from ..models import Album, Job, UploadedFile
from ..organize import compilation, duplicates
from ..organize.importer import compilations, own_file
from ..security import admin_user
from ..serial import iso

router = APIRouter(prefix="/api/upload", tags=["upload"], dependencies=[Depends(admin_user)])
BATCH_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-z0-9]{4}$")
DISC = re.compile(r"^(cd|dis[ck])[\s._-]*\d{1,2}$", re.I)       # an album's disc, in a folder of its own


def batch_dir(batch: str):
    if not BATCH_RE.match(batch):
        raise HTTPException(400, "Bad batch name")
    return env.UPLOAD_DIR / batch


def album_folder(rel_dir: str) -> str:
    """The album folder a song's folder is: the one above a disc's folder (CD1, Disc 2)."""
    return os.path.dirname(rel_dir) if DISC.match(os.path.basename(rel_dir)) else rel_dir


def safe_rel(rel: str, fallback: str) -> str:
    parts = [p for p in re.split(r"[\\/]+", rel or fallback) if p not in ("", ".", "..")]
    return os.path.join(*parts) if parts else os.path.basename(fallback) or "file"


@router.post("/batch")
def new_batch():
    name = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(2).hex()
    batch_dir(name).mkdir(parents=True)
    return {"batch": name}


class Pending(BaseModel):
    path: str
    size: int


class CheckBody(BaseModel):
    files: list[Pending]


@router.post("/check")
def check(body: CheckBody, db: Session = Depends(get_db)):
    """Before files go up: which look like duplicates (organize/duplicates.py)."""
    if not settings.get("upload_check_duplicates"):
        return {"found": [], "skip": [], "off": True}
    return duplicates.check([(f.path, f.size) for f in body.files], db)


@router.post("/batch/{batch}/files")
async def upload_files(batch: str, files: list[UploadFile], paths: list[str] = Form(default=[]),
                       db: Session = Depends(get_db)):
    d = batch_dir(batch)
    if not d.is_dir():
        raise HTTPException(404, "No such upload batch")
    saved = []
    for i, f in enumerate(files):
        rel = safe_rel(paths[i] if i < len(paths) else "", f.filename or "file")
        dest = d / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as out:
            while chunk := await f.read(1024 * 1024):
                out.write(chunk)
        saved.append({"path": rel, "size": dest.stat().st_size, "kind": formats.family(rel) or "other"})
    duplicates.remember(db, batch, saved)
    return {"saved": saved}


@router.post("/batch/{batch}/part")
async def upload_part(batch: str, data: UploadFile, path: str = Form(...), offset: int = Form(..., ge=0),
                      total: int = Form(..., ge=0), db: Session = Depends(get_db)):
    """One piece of a big file. Proxies such as Cloudflare refuse request bodies
    over 100 MiB, so the browser sends large files in pieces, in order."""
    d = batch_dir(batch)
    if not d.is_dir():
        raise HTTPException(404, "No such upload batch")
    rel = safe_rel(path, data.filename or "file")
    dest = d / rel
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    if offset and offset != have:
        raise HTTPException(409, f"Expected the piece at {have}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(part, "r+b" if offset else "wb") as out:
        out.seek(offset)
        out.truncate()
        while chunk := await data.read(1024 * 1024):
            out.write(chunk)
        size = out.tell()
    if size > total:
        part.unlink()
        raise HTTPException(400, "More data than announced")
    if size < total:
        return {"received": size}
    os.replace(part, dest)
    saved = [{"path": rel, "size": size, "kind": formats.family(rel) or "other"}]
    duplicates.remember(db, batch, saved)
    return {"saved": saved}


def batch_json(d, db: Session):
    """A batch as the upload area lists it, or None when it's gone: an import moves its files into
    the library and takes the emptied folder away, maybe while they're being listed."""
    try:
        created = datetime.fromtimestamp(d.stat().st_ctime, timezone.utc).isoformat()
    except FileNotFoundError:
        return None
    files = []
    for r, _, fs in os.walk(d):
        for f in fs:
            p = os.path.join(r, f)
            try:
                size = os.path.getsize(p)
            except FileNotFoundError:
                continue
            files.append({"path": os.path.relpath(p, d), "size": size, "kind": formats.family(f) or "other"})
    job = db.scalar(select(Job).where(Job.type == "import_upload",
                                      Job.params["batch"].as_string() == d.name).order_by(Job.id.desc()).limit(1))
    own = compilations(d.name)
    return {"batch": d.name, "files": files, "created": created, "albums": albums_of(d.name, files, db, own),
            "compilations": own,
            "job": {"id": job.id, "status": job.status, "progress": job.progress, "message": job.message} if job else None}


def albums_of(batch: str, files: list[dict], db: Session, own: list[str] = ()) -> list[dict]:
    """A batch's songs by album, as their tags say (by folder for songs without an album tag), those in a folder
    marked an own compilation as it: {artist, album, year, songs, formats, size, folder (its album folder),
    compilation}."""
    tagged = {u.path: u for u in db.scalars(select(UploadedFile).where(UploadedFile.batch == batch))}
    out: dict[tuple, dict] = {}
    for f in files:
        if f["kind"] not in duplicates.MUSIC:
            continue
        u = tagged.get(f["path"])
        folder = album_folder(os.path.dirname(f["path"]))
        mine = next((c for c in own if f["path"].startswith(c + "/")), None)
        if mine is not None:
            name, year = compilation.title_of(os.path.basename(mine))
            a = out.setdefault(("\0own", mine), {"artist": compilation.VA, "album": name, "year": year, "songs": 0,
                                                 "formats": [], "size": 0, "folder": mine, "compilation": True})
        else:
            album = (u.album if u else "") or os.path.basename(folder)
            artist = u.artist if u else ""
            key = (artist.casefold(), album.casefold()) if u and u.album else ("", "\0" + folder)
            a = out.setdefault(key, {"artist": artist, "album": album, "year": 0, "songs": 0, "formats": [], "size": 0,
                                     "folder": folder, "compilation": False})
        a["songs"] += 1
        a["size"] += f["size"]
        if not (a["compilation"] and compilation.title_of(os.path.basename(a["folder"]))[1]):     # the folder's says
            a["year"] = max(a["year"], u.year if u else 0)
        ext = formats.ext_of(f["path"])
        if ext not in a["formats"]:
            a["formats"].append(ext)
    return sorted(out.values(), key=lambda a: (a["artist"].casefold(), a["album"].casefold()))


def filed(r: dict, db: Session) -> list[dict]:
    """An import's albums, with where each was filed, its page here (once scanned) and how it was matched:
    "musicbrainz" (it has a MusicBrainz release: the import's word, or the library's for older imports),
    "bandcamp", or "none" (as its tags said)."""
    out = []
    root = r.get("music_root") or ""
    for a in r.get("albums") or []:
        folder = a.get("folder") or ""
        row = db.execute(select(Album.id, Album.mbid).where(Album.folder.in_((folder, os.path.dirname(folder)))).limit(1)).first() \
            if folder else None
        match = a.get("match") or ("musicbrainz" if a.get("mbid") or (row and row.mbid) else "none" if row else "")
        out.append({**a, "where": os.path.relpath(folder, root) if root and folder.startswith(root) else folder,
                    "album_id": row.id if row else None, "match": match})
    return out


@router.get("/imports")
def imports(limit: int = 8, db: Session = Depends(get_db)):
    """The latest imports, uploaded or from the watch folder (watch.py), with where their albums were filed."""
    out = []
    for job in db.scalars(select(Job).where(Job.type.in_(("import_upload", "import_watched"))).order_by(Job.id.desc()).limit(limit)):
        r = job.result or {}
        albums = filed(r, db)
        out.append({"id": job.id, "batch": (job.params or {}).get("batch", ""), "status": job.status,
                    "watched": (job.params or {}).get("name", "") if job.type == "import_watched" else "",
                    "duplicate": bool(r.get("duplicate")),
                    "message": job.message, "progress": job.progress, "started_at": iso(job.started_at),
                    "finished_at": iso(job.finished_at), "music": r.get("music"), "vgm": r.get("vgm"),
                    "vgm_folder": r.get("vgm_folder") or "", "albums": albums, "left": r.get("left") or []})
    return out


@router.get("/batches")
def batches(db: Session = Depends(get_db)):
    if not env.UPLOAD_DIR.is_dir():
        return []
    dirs = sorted((d for d in env.UPLOAD_DIR.iterdir() if d.is_dir() and BATCH_RE.match(d.name)), reverse=True)
    return [b for b in (batch_json(d, db) for d in dirs) if b]


class Own(BaseModel):
    folder: str
    on: bool = True


@router.put("/batch/{batch}/compilation")
def set_compilation(batch: str, body: Own, db: Session = Depends(get_db)):
    """A folder of the batch marked an own compilation (`on`), or not any more. One in it, or one it's in, marked
    before isn't: the folder marked last is the compilation."""
    d = batch_dir(batch)
    folder = safe_rel(body.folder, "")
    if not folder or not (d / folder).is_dir():
        raise HTTPException(404, "No such folder in the upload")
    def nested(a: str, b: str) -> bool:
        return a == b or a.startswith(b + "/") or b.startswith(a + "/")
    own = [f for f in compilations(batch) if not nested(f, folder)] + ([folder] if body.on else [])
    if own:
        own_file(batch).write_text(json.dumps(sorted(own), ensure_ascii=False))
    else:
        own_file(batch).unlink(missing_ok=True)
    return batch_json(d, db)


@router.post("/batch/{batch}/import")
def start_import(batch: str):
    if not batch_dir(batch).is_dir():
        raise HTTPException(404, "No such upload batch")
    return {"job_id": jobs.submit("import_upload", f"Import upload {batch}", batch=batch, _allow_parallel=True)}


@router.delete("/batch/{batch}")
def discard(batch: str, db: Session = Depends(get_db)):
    shutil.rmtree(batch_dir(batch), ignore_errors=True)
    own_file(batch).unlink(missing_ok=True)
    duplicates.forget(db, batch)
    return {"ok": True}

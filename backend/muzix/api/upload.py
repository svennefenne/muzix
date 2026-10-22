"""Upload area on the admin page: files dropped or picked in the browser land in
/config/uploads/<batch>/ (folder structure kept) and are imported on request."""

import os
import re
import shutil
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import env, formats, jobs
from ..db import get_db
from ..models import Job
from ..security import admin_user

router = APIRouter(prefix="/api/upload", tags=["upload"], dependencies=[Depends(admin_user)])
BATCH_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-z0-9]{4}$")


def batch_dir(batch: str):
    if not BATCH_RE.match(batch):
        raise HTTPException(400, "Bad batch name")
    return env.UPLOAD_DIR / batch


def safe_rel(rel: str, fallback: str) -> str:
    parts = [p for p in re.split(r"[\\/]+", rel or fallback) if p not in ("", ".", "..")]
    return os.path.join(*parts) if parts else os.path.basename(fallback) or "file"


@router.post("/batch")
def new_batch():
    name = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(2).hex()
    batch_dir(name).mkdir(parents=True)
    return {"batch": name}


@router.post("/batch/{batch}/files")
async def upload_files(batch: str, files: list[UploadFile], paths: list[str] = Form(default=[])):
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
    return {"saved": saved}


def batch_json(d, db: Session):
    files = []
    for r, _, fs in os.walk(d):
        for f in fs:
            p = os.path.join(r, f)
            files.append({"path": os.path.relpath(p, d), "size": os.path.getsize(p),
                          "kind": formats.family(f) or "other"})
    job = db.scalar(select(Job).where(Job.type == "import_upload",
                                      Job.params["batch"].as_string() == d.name).order_by(Job.id.desc()).limit(1))
    return {"batch": d.name, "files": files, "created": datetime.fromtimestamp(d.stat().st_ctime, timezone.utc).isoformat(),
            "job": {"id": job.id, "status": job.status, "progress": job.progress, "message": job.message} if job else None}


@router.get("/batches")
def batches(db: Session = Depends(get_db)):
    if not env.UPLOAD_DIR.is_dir():
        return []
    dirs = sorted((d for d in env.UPLOAD_DIR.iterdir() if d.is_dir() and BATCH_RE.match(d.name)), reverse=True)
    return [batch_json(d, db) for d in dirs]


@router.post("/batch/{batch}/import")
def start_import(batch: str):
    if not batch_dir(batch).is_dir():
        raise HTTPException(404, "No such upload batch")
    return {"job_id": jobs.submit("import_upload", f"Import upload {batch}", batch=batch, _allow_parallel=True)}


@router.delete("/batch/{batch}")
def discard(batch: str):
    shutil.rmtree(batch_dir(batch), ignore_errors=True)
    return {"ok": True}

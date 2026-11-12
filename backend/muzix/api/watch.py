"""The watch folder on the admin page (watch.py): where it is (on this server, or on a computer whose Muzix
Desktop lets this server pick one), what's waiting in it, its albums set aside, and the latest ones filed."""

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import jobs, settings, tunnel, watch
from ..db import get_db
from ..models import Job, Peer
from ..security import admin_user
from ..serial import iso
from .admin import browse as browse_server
from .upload import filed

router = APIRouter(prefix="/api/admin/watch", tags=["watch"], dependencies=[Depends(admin_user)])


def _computer(db: Session, sid: str) -> Peer:
    peer = db.scalar(select(Peer).where(Peer.server_id == sid, Peer.kind == "computer"))
    if peer is None:
        raise HTTPException(404, "No such computer in the Library Network")
    return peer


def _ask(peer: Peer, op: str, **args):
    try:
        return tunnel.get(peer.id).ask(op, **args)
    except tunnel.Refused as e:
        raise HTTPException(403, str(e))
    except tunnel.Gone as e:
        raise HTTPException(409, f"{peer.name}: {e}")


@router.get("")
def get_watch(db: Session = Depends(get_db)):
    computers = [{"id": p.server_id, "name": p.name, "online": tunnel.connected(p.id)}
                 for p in db.scalars(select(Peer).where(Peer.kind == "computer", Peer.sent.is_(True), Peer.received.is_(True)))]
    where = watch.place()
    held = {"_Duplicates": [], "_Failed": []}
    if where is not None:
        try:
            held = where.held()
        except Exception:       # a computer gone meanwhile
            pass
    recent = []
    for j in db.scalars(select(Job).where(Job.type == "import_watched").order_by(Job.id.desc()).limit(12)):
        r = j.result or {}
        albums = filed(r, db)
        got = {a["match"] for a in albums if a["match"]}
        recent.append({"id": j.id, "name": (j.params or {}).get("name", ""), "status": j.status,
                       "error": j.message if j.status == "failed" else "",
                       # each album's own match counts (an import's own word from before 0.4.20 was the whole folder's)
                       "match": (got.pop() if len(got) == 1 else "mixed") if got else r.get("match", ""),
                       "duplicate": bool(r.get("duplicate")), "albums": albums, "finished_at": iso(j.finished_at)})
    return {"folder": settings.get("watch_folder"), "computer": settings.get("watch_computer"), "computers": computers,
            "reachable": where is not None, "state": watch.state(), "held": held, "recent": recent}


class WatchBody(BaseModel):
    folder: str = ""
    computer: str = ""      # a computer's id, or "" for a folder on this server


@router.put("")
def set_watch(body: WatchBody, db: Session = Depends(get_db)):
    folder = body.folder.strip()
    if folder and body.computer:
        _ask(_computer(db, body.computer), "watch_set", path=folder)     # its Muzix Desktop says yes, or why not
    elif folder and not (os.path.isdir(folder) and os.access(folder, os.W_OK)):
        raise HTTPException(400, "Muzix can't write to that folder (its albums are moved out of it)")
    settings.set_many({"watch_folder": folder, "watch_computer": body.computer if folder else ""})
    return get_watch(db)


@router.get("/browse")
def browse(computer: str = "", path: str = "", db: Session = Depends(get_db)):
    """The folders in a folder, to pick the watch folder: on this server, or on a computer that allows it."""
    if not computer:
        return browse_server(path or "/")
    return _ask(_computer(db, computer), "watch_browse", path=path)


class AgainBody(BaseModel):
    name: str
    held: str               # _Duplicates | _Failed


@router.post("/again")
def again(body: AgainBody):
    """An album set aside, filed anyway (one in _Duplicates without looking for duplicates again)."""
    if body.held not in ("_Duplicates", "_Failed"):
        raise HTTPException(400, "Only albums set aside can be filed again")
    where = watch.place()
    if where is None:
        raise HTTPException(409, "The watch folder can't be reached right now")
    return {"job_id": jobs.submit("import_watched", f"Watch folder: {body.name}", name=body.name, key=where.key, held=body.held)}

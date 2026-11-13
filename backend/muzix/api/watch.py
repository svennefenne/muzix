"""The watch folder on the admin page (watch.py): where it is (on this server, or on a computer whose Muzix
Desktop lets this server pick one), what's waiting in it, its albums set aside, and the latest ones filed."""

import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import jobs, tunnel, watch
from ..db import get_db
from ..models import Job, Peer
from ..security import admin_user
from ..serial import iso
from .admin import browse as browse_server
from .upload import filed

log = logging.getLogger(__name__)
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


def _folder(db: Session, f: dict) -> dict:
    """One watch folder: where, how its albums are matched, how it stands, its albums set aside and why."""
    key = watch.key_of(f)
    where = watch.place(key)
    held = {"_Duplicates": [], "_Failed": []}
    if where is not None:
        try:
            held = where.held()
        except Exception as e:  # a computer gone meanwhile
            log.warning("The watch folder's albums set aside couldn't be listed: %s", e)
    return {**f, "key": key, "reachable": where is not None, "state": watch.state(key), "held": held,
            "why": _why(db, held["_Duplicates"], key), "trash": "deleted" if not f["computer"] else "trash"}


@router.get("")
def get_watch(db: Session = Depends(get_db)):
    """Every watch folder ("folders"), the first one's fields at the top too (as older apps' admin pages read
    them), and the latest filed from them."""
    computers = [{"id": p.server_id, "name": p.name, "online": tunnel.connected(p.id)}
                 for p in db.scalars(select(Peer).where(Peer.kind == "computer", Peer.sent.is_(True), Peer.received.is_(True)))]
    folders = [_folder(db, f) for f in watch.folders()]
    first = folders[0] if folders else {"folder": "", "computer": "", "reachable": False, "state": watch.state(),
                                        "held": {"_Duplicates": [], "_Failed": []}, "why": {}, "trash": "trash"}
    return {**{k: first[k] for k in ("folder", "computer", "reachable", "state", "held", "why", "trash")},
            "computers": computers, "folders": folders, "recent": _recent(db)}


def _why(db: Session, names: list[str], key: str = "") -> dict[str, dict]:
    """Why each album in _Duplicates was set aside: of how many songs, the ones the library seems to have and
    what they're like there, and the library's albums filing it in their place would put aside."""
    out: dict[str, dict] = {}
    if not names:
        return out
    for j in db.scalars(select(Job).where(Job.type == "import_watched", Job.status == "done").order_by(Job.id.desc()).limit(400)):
        name, r = (j.params or {}).get("name", ""), j.result or {}
        if key and (j.params or {}).get("key") not in (key, None):     # another watch folder's
            continue
        if name not in names or name in out or not (r.get("duplicate") or r.get("aside")):
            continue
        r = r if r.get("duplicate") else r["aside"]         # set aside whole, or some of its albums
        found = r.get("found") or []
        out[name] = {"songs": r.get("songs") or 0, "replaces": watch.replaced(found),
                     "found": [{"song": os.path.basename(f.get("path") or ""), "why": f.get("why", ""),
                                **{k: (f.get("match") or {}).get(k, "") for k in ("title", "artist", "album", "format")},
                                "folder": watch._album_folder((f.get("match") or {}).get("path") or "") if f.get("match") else ""}
                               for f in found]}
    return out


def _recent(db: Session) -> list[dict]:
    recent = []
    for j in db.scalars(select(Job).where(Job.type == "import_watched").order_by(Job.id.desc()).limit(12)):
        r = j.result or {}
        albums = filed(r, db)
        got = {a["match"] for a in albums if a["match"]}
        recent.append({"id": j.id, "name": (j.params or {}).get("name", ""), "key": (j.params or {}).get("key", ""),
                       "status": j.status,
                       "error": j.message if j.status == "failed" else "",
                       # each album's own match counts (an import's own word from before 0.4.20 was the whole folder's)
                       "match": (got.pop() if len(got) == 1 else "mixed") if got else r.get("match", ""),
                       "duplicate": bool(r.get("duplicate")), "removed": bool(r.get("removed")),
                       "replaced": len(r.get("replaced") or []), "aside": len((r.get("aside") or {}).get("albums") or []),
                       "albums": albums, "finished_at": iso(j.finished_at)})
    return recent


class WatchBody(BaseModel):
    folder: str = ""        # "": that watch folder no longer watched
    computer: str = ""      # a computer's id, or "" for a folder on this server
    only: str = ""          # watch.ONLY: "bandcamp" for albums matched with Bandcamp alone
    at: int = 0             # which watch folder (one past the last: another one)


def _let(db: Session, computer: str, path: str, was: str = "", alone: bool = True):
    """Muzix Desktop on the computer lets this server watch `path` there (and no longer `was`), or says why not.
    One before 0.4.24 knows one folder only (watch_set): fine when it's the only one there (`alone`)."""
    peer = _computer(db, computer)
    try:
        tunnel.get(peer.id).ask("watch_pick", path=path, was=was)
    except tunnel.Refused as e:
        if "Unknown request" not in str(e):
            raise HTTPException(403, str(e))
        if not path:
            return              # an older one: what it was let watch is replaced when it's let watch another
        if not alone:
            raise HTTPException(409, f"Muzix Desktop on {peer.name} watches one folder for this server: "
                                     "0.4.24 and later can watch more")
        _ask(peer, "watch_set", path=path)
    except tunnel.Gone as e:
        raise HTTPException(409, f"{peer.name}: {e}")


@router.put("")
def set_watch(body: WatchBody, db: Session = Depends(get_db)):
    """A watch folder set (`at`: which; one past the last adds one), its way of matching changed, or (no
    folder) no longer watched."""
    fs = watch.folders()
    at = max(0, min(body.at, len(fs)))
    old = fs[at] if at < len(fs) else None
    folder = body.folder.strip()
    if body.only not in watch.ONLY:
        raise HTTPException(400, "Not a way to match a folder's albums")
    if not folder:
        if old is None:
            return get_watch(db)
        fs.pop(at)
        if old["computer"]:
            try:
                _let(db, old["computer"], "", was=old["folder"])
            except HTTPException:
                pass            # the computer's off: it keeps letting this server watch it until told otherwise
        watch.set_folders(fs)
        return get_watch(db)
    new = {"folder": folder, "computer": body.computer, "only": body.only}
    if any(i != at and f["folder"] == folder and f["computer"] == body.computer for i, f in enumerate(fs)):
        raise HTTPException(400, "That folder is watched already")
    same = old is not None and old["folder"] == folder and old["computer"] == body.computer
    if not same:
        if body.computer:
            others = [f for i, f in enumerate(fs) if i != at and f["computer"] == body.computer]
            _let(db, body.computer, folder, was=old["folder"] if old and old["computer"] == body.computer else "",
                 alone=not others)
        elif not (os.path.isdir(folder) and os.access(folder, os.W_OK)):
            raise HTTPException(400, "Muzix can't write to that folder (its albums are moved out of it)")
        if old and old["computer"] and old["computer"] != body.computer:
            try:
                _let(db, old["computer"], "", was=old["folder"])
            except HTTPException:
                pass
    if old is None:
        fs.append(new)
    else:
        fs[at] = new
    watch.set_folders(fs)
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
    how: str = ""           # from _Duplicates: duplicates (the default) | album | replace (watch.HOW)
    key: str = ""           # which watch folder ("": the first)


def _place(key: str = "") -> watch.Place:
    where = watch.place(key)
    if where is None:
        raise HTTPException(409, "The watch folder can't be reached right now")
    return where


@router.post("/again")
def again(body: AgainBody):
    """An album set aside, filed anyway (one in _Duplicates without looking for duplicates again): from
    _Duplicates into the library's Duplicates folder, as an album of its own, or in place of the library's copy."""
    if body.held not in ("_Duplicates", "_Failed"):
        raise HTTPException(400, "Only albums set aside can be filed again")
    if body.how and (body.held != "_Duplicates" or body.how not in watch.HOW):
        raise HTTPException(400, "Not a way to file it")
    where = _place(body.key)
    how = {"how": body.how} if body.how else {}
    return {"job_id": jobs.submit("import_watched", f"Watch folder: {body.name}", name=body.name, key=where.key,
                                  held=body.held, **how)}


class HeldBody(BaseModel):
    name: str
    held: str               # _Duplicates | _Failed
    key: str = ""           # which watch folder ("": the first)


@router.post("/remove")
def remove(body: HeldBody):
    """An album set aside, thrown away: into the computer's trash (Muzix Desktop 0.4.22 on), or on this server
    deleted."""
    if body.held not in ("_Duplicates", "_Failed") or not body.name or "/" in body.name or body.name in (".", ".."):
        raise HTTPException(400, "Only albums set aside can be thrown away")
    where = _place(body.key)
    try:
        return {"gone": where.trash(body.name, body.held)}
    except tunnel.Refused as e:
        raise HTTPException(409, f"{e} (Muzix Desktop 0.4.22 and later can do it)" if "Unknown request" in str(e) else str(e))
    except tunnel.Gone as e:
        raise HTTPException(409, str(e))


class NowBody(BaseModel):
    key: str = ""           # which watch folder ("": the first)


@router.post("/now")
def transfer_now(body: NowBody | None = None):
    """Transfer now: every album in the folder taken at once, but one still being copied in."""
    try:
        return watch.check(now=True, key=body.key if body else "")
    except (tunnel.Refused, tunnel.Gone, RuntimeError, OSError) as e:
        raise HTTPException(409, str(e) or e.__class__.__name__)
